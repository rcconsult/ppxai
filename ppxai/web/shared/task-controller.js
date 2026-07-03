/**
 * TaskController — web driver for the tool-capable /v1/agent/task tier.
 *
 * The `/task` command family (v1.19.x, build plan T1):
 *   /task run "<desc>" --tools a,b,c [--allow host] [--provider p] [--model m]
 *                      [--budget iters=,time=,tokens=] [--system "…"]
 *   /task ls | show <id> | watch <id> | cancel <id> | help
 *
 * Extends AgentRunController: the run registry endpoints (list, show, live SSE
 * tail, poll-to-terminal, cancel) are IDENTICAL to the tool-free tier, so this
 * subclass reuses all of that and only overrides the launch (POST
 * /v1/agent/task, with a tool grant + egress + budget) and swaps the pane class
 * to the denser TaskRunView. T1 rides entirely on endpoints that already ship.
 *
 * @version 1.19.0
 */

// Resolve the base class from the browser global (scripts load in order) or,
// under Node tests, from the sibling module.
const _AgentRunControllerBase =
    (typeof AgentRunController !== 'undefined')
        ? AgentRunController
        : (typeof require === 'function'
            ? require('./agent-run-controller.js').AgentRunController
            : null);


/** host or host/prefix → a NetworkSpec.allow_outbound entry. */
function _egressEntry(s) {
    const slash = s.indexOf('/');
    if (slash === -1) return s;                 // bare host, any path
    return { host: s.slice(0, slash), paths: [s.slice(slash)] };
}

/** "100" | "100k" | "1.5m" → number, or null if malformed. */
function _num(s) {
    const m = /^(\d+(?:\.\d+)?)([km]?)$/i.exec(s.trim());
    if (!m) return null;
    let n = parseFloat(m[1]);
    if (m[2].toLowerCase() === 'k') n *= 1e3;
    else if (m[2].toLowerCase() === 'm') n *= 1e6;
    return n;
}

/** Parse --budget "iters=20,time=300,tokens=100k" into the BudgetSpec shape. */
function _parseBudget(v, out) {
    v.split(',').forEach((pair) => {
        const eq = pair.indexOf('=');
        if (eq === -1) { out.errors.push(`bad --budget term: ${pair}`); return; }
        const key = pair.slice(0, eq).trim().toLowerCase();
        const num = _num(pair.slice(eq + 1));
        if (num === null) { out.errors.push(`bad --budget value: ${pair}`); return; }
        if (key === 'iters' || key === 'iterations') out.budget.iterations = Math.round(num);
        else if (key === 'time' || key === 'time_s') out.budget.time_s = num;
        else if (key === 'tokens') out.budget.tokens = Math.round(num);
        else out.errors.push(`unknown --budget key: ${key}`);
    });
}

/** Split a command line into tokens, treating "…"/'…' as single tokens. */
function _tokenize(s) {
    const toks = [];
    const re = /"([^"]*)"|'([^']*)'|(\S+)/g;
    let m;
    while ((m = re.exec(s)) !== null) {
        toks.push(m[1] !== undefined ? m[1] : (m[2] !== undefined ? m[2] : m[3]));
    }
    return toks;
}

/**
 * Parse a `/task run` argument line into an AgentTaskRequest-shaped object.
 * The description is the leading run of tokens before the first `--flag`
 * (quoted or bare). Returns `{task, tools, provider, model, system, network,
 * budget, errors}`; a non-empty `errors` means don't send.
 */
function parseTaskArgs(argline) {
    const toks = _tokenize((argline || '').trim());
    const out = {
        task: '', tools: [], provider: null, model: null, system: null,
        network: { allow_outbound: [] }, budget: {}, errors: [],
    };
    let i = 0;
    const desc = [];
    while (i < toks.length && !toks[i].startsWith('--')) { desc.push(toks[i]); i++; }
    out.task = desc.join(' ').trim();

    const value = (name) => {
        if (i + 1 >= toks.length || toks[i + 1].startsWith('--')) {
            out.errors.push(`${name} needs a value`);
            return null;
        }
        i += 1;
        return toks[i];
    };

    for (; i < toks.length; i += 1) {
        const t = toks[i];
        let v;
        switch (t) {
            case '--tools':
                v = value('--tools');
                if (v) out.tools = v.split(',').map((x) => x.trim()).filter(Boolean);
                break;
            case '--allow':
                v = value('--allow');
                if (v) out.network.allow_outbound = v.split(',').map((x) => x.trim()).filter(Boolean).map(_egressEntry);
                break;
            case '--provider': v = value('--provider'); if (v) out.provider = v; break;
            case '--model':    v = value('--model');    if (v) out.model = v;    break;
            case '--system':   v = value('--system');   if (v) out.system = v;   break;
            case '--budget':   v = value('--budget');   if (v) _parseBudget(v, out); break;
            default:
                out.errors.push(`unknown flag: ${t}`);
        }
    }
    return out;
}


class TaskController extends _AgentRunControllerBase {
    /** @param {PpxaiApp} app */
    constructor(app) {
        super(app);
        if (typeof TaskRunView !== 'undefined') this._viewClass = TaskRunView;
        this._emptyHint = 'No task runs yet — start one with /task run "<desc>" --tools <a,b,c>';
        this._reopenHint = '/task ls';
    }

    /** Route `/task <verb> <rest>` to a handler. */
    async handle(argline) {
        const trimmed = (argline || '').trim();
        const sp = trimmed.search(/\s/);
        const verb = (sp === -1 ? trimmed : trimmed.slice(0, sp)).toLowerCase();
        const rest = sp === -1 ? '' : trimmed.slice(sp + 1).trim();
        switch (verb) {
            case '':
            case 'help':   return this.help();
            case 'run':    return this.run(rest);
            case 'ls':
            case 'list':   return this.list();
            case 'show':
            case 'open':   return this.show(rest);
            case 'watch':  return this.show(rest);
            case 'cancel': return this.cancel(rest.trim());
            default:
                this.app.showSystemMessage(`Unknown /task subcommand: ${verb}. Try /task help.`);
                return undefined;
        }
    }

    /** /task run — launch a tool-capable sandboxed run. */
    async run(argline) {
        const spec = parseTaskArgs(argline);
        if (spec.errors.length) {
            this.app.showSystemMessage(`❌ /task run: ${spec.errors.join('; ')}`);
            return;
        }
        if (!spec.task) {
            this.app.showSystemMessage(
                'Usage: /task run "<desc>" --tools <a,b,c> [--allow host] [--budget iters=,time=,tokens=] [--system "…"]'
            );
            return;
        }
        if (!spec.tools.length) {
            this.app.showSystemMessage(
                '❌ /task run needs a tool grant (--tools a,b,c). A tool-free run belongs on /agentrun.'
            );
            return;
        }

        const provider = spec.provider || this.app.state.currentProvider;
        const model = spec.model || this.app.state.currentModel;
        const body = { task: spec.task, tools: spec.tools };
        if (provider) body.provider = provider;
        if (model) body.model = model;
        if (spec.system) body.system = spec.system;
        if (spec.network.allow_outbound.length) body.network = { allow_outbound: spec.network.allow_outbound };
        if (Object.keys(spec.budget).length) body.budget = spec.budget;

        let started;
        try {
            started = await this.app.apiClient.post('/v1/agent/task', body);
        } catch (e) {
            // Surface the tier's own guardrail messages verbatim (403 tier
            // disabled + enable hint, 400 shell grant, 400 missing provider).
            this.app.showSystemMessage(`❌ Task rejected: ${e.message}`);
            return;
        }

        const runId = started.run_id;
        this._openPane(runId, spec.task, {
            tools: spec.tools,
            network: spec.network.allow_outbound,
            budget: spec.budget,
            provider, model,
            status: started.status || 'running',
        });
        this._breadcrumb(runId, spec.task, `🛠️ ${runId} — task running… (in panel; chat stays usable)`);
        this._watchDetached(runId);
    }

    /** /task show|open|watch <id> — focus (and live-tail) a run's pane. */
    show(runId) {
        const id = (runId || '').trim();
        if (!id) { this.app.showSystemMessage('Usage: /task show <id>'); return undefined; }
        return this.focus(id, '');
    }

    help() {
        this.app.showSystemMessage([
            '/task — tool-capable background runs (sandboxed tier; default-off):',
            '  /task run "<desc>" --tools a,b,c [--allow host] [--provider p] [--model m] [--budget iters=,time=,tokens=] [--system "…"]',
            '  /task ls                list runs',
            '  /task show <id>         open a run pane',
            '  /task watch <id>        open + live-tail a run',
            '  /task cancel <id>       cancel a run',
        ].join('\n'));
    }
}

TaskController.parseArgs = parseTaskArgs;


// CommonJS export for tests; window-global for browser.
if (typeof module !== 'undefined' && module.exports) {
    module.exports = { TaskController, parseTaskArgs };
} else if (typeof window !== 'undefined') {
    window.TaskController = TaskController;
    window.parseTaskArgs = parseTaskArgs;
}
