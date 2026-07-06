/**
 * TaskController — web driver for the tool-capable /v1/agent/task tier.
 *
 * The `/task` command family (v1.19.x, build plan T1):
 *   /task run "<desc>" --tools a,b,c [--allow host] [--provider p] [--model m]
 *                      [--budget iters=,time=,tokens=] [--system "…"] [--spec <name>]
 *   /task run "<desc>" --spec <name>   (T3) configure from a spec file under
 *                      tools.agent.sandbox.specs_dir; explicit flags override
 *                      the file. The server resolves the name + clamps the grant.
 *   /task run "<desc>" --skill <name>  (T4) mount a skill dir under
 *                      tools.agent.sandbox.skills_dir: SKILL.md is a spec and the
 *                      skill's references/ join the run read-scope. Repeatable /
 *                      comma-separated; grants union, still ⊆ the operator ceiling.
 *   /task respond <id> approve|deny|"<text>"  (T5) answer a run parked in
 *                      `waiting{consent}` — the pane's consent card is the
 *                      clickable equivalent. Free text rides along as a note
 *                      (a text-only answer to a consent park is a deny).
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
        network: { allow_outbound: [] }, budget: {}, spec: null, skills: [],
        errors: [],
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
            case '--spec':     v = value('--spec');     if (v) out.spec = v;     break;
            case '--skill':
                // T4: repeatable and/or comma-separated — skills compose.
                v = value('--skill');
                if (v) {
                    for (const s of v.split(',').map((x) => x.trim()).filter(Boolean)) {
                        if (!out.skills.includes(s)) out.skills.push(s);
                    }
                }
                break;
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
            case 'respond': return this.respondCmd(rest);
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
                'Usage: /task run "<desc>" --tools <a,b,c> [--spec <name>] [--skill <name>] [--allow host] [--budget iters=,time=,tokens=] [--system "…"]'
            );
            return;
        }
        const hasResolvedSource = Boolean(spec.spec) || spec.skills.length > 0;
        if (!spec.tools.length && !hasResolvedSource) {
            // A grant is required — but a --spec or --skill may supply it (T3/T4).
            // The server clamps the merged grant (no-shell, ceiling); we only
            // guard the "no grant source at all" case here to fail fast.
            this.app.showSystemMessage(
                '❌ /task run needs a tool grant (--tools a,b,c), a --spec, or a --skill that supplies one. A tool-free run belongs on /agentrun.'
            );
            return;
        }

        // With a --spec or --skill, provider/model/grant may come from the file;
        // don't force the session's current provider/model onto the request
        // (that would override the resolved source). Without one, keep the T1
        // behavior of defaulting to the session's provider/model.
        const provider = spec.provider || (hasResolvedSource ? null : this.app.state.currentProvider);
        const model = spec.model || (hasResolvedSource ? null : this.app.state.currentModel);
        const body = { task: spec.task, tools: spec.tools };
        if (spec.spec) body.spec = spec.spec;
        if (spec.skills.length) body.skills = spec.skills;
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
            // disabled + enable hint, 400 shell grant, 400 missing provider,
            // 400 unknown/invalid spec).
            this.app.showSystemMessage(`❌ Task rejected: ${e.message}`);
            return;
        }

        const runId = started.run_id;
        // Optimistic pane info from what the client parsed.
        let paneInfo = {
            tools: spec.tools,
            network: spec.network.allow_outbound,
            budget: spec.budget,
            provider, model,
            status: started.status || 'running',
        };
        // A spec or skill resolved server-side — the client didn't know the
        // file's grant/budget/provider (or the skill's unioned grant). Reflect
        // the authoritative merged meta in the pane so it shows what actually
        // runs (T3/T4 trial expectation).
        if (hasResolvedSource) {
            try {
                const meta = await this.app.apiClient.get(`/v1/agent/runs/${runId}`);
                paneInfo = {
                    tools: meta.tools || spec.tools,
                    network: meta.network || spec.network.allow_outbound,
                    budget: meta.budget || spec.budget,
                    provider: meta.provider || provider,
                    model: meta.model || model,
                    status: meta.status || started.status || 'running',
                };
            } catch (_e) { /* keep optimistic values if the meta fetch fails */ }
        }
        this._openPane(runId, spec.task, paneInfo);
        this._breadcrumb(runId, spec.task, `🛠️ ${runId} — task running… (in panel; chat stays usable)`);
        this._watchDetached(runId);
    }

    /**
     * /task respond <id> approve|deny|"<text>" — answer a parked run (T5).
     *
     * Fetches the run's meta for the resume token (waiting.token), maps the
     * answer word to the wire shape, and POSTs /runs/{id}/respond via the
     * shared base helper. approve/yes → {approved:true}; deny/no →
     * {approved:false}; anything else is free text (which a consent park
     * treats as a deny-with-note — fail-closed).
     */
    async respondCmd(rest) {
        const trimmed = (rest || '').trim();
        const sp = trimmed.search(/\s/);
        const runId = sp === -1 ? trimmed : trimmed.slice(0, sp);
        let answer = sp === -1 ? '' : trimmed.slice(sp + 1).trim();
        if (!runId || !answer) {
            this.app.showSystemMessage('Usage: /task respond <id> approve|deny|"<text>"');
            return;
        }
        // Strip one layer of quotes off a quoted free-text answer.
        const q = answer[0];
        if ((q === '"' || q === "'") && answer.endsWith(q) && answer.length > 1) {
            answer = answer.slice(1, -1);
        }
        let meta;
        try {
            meta = await this.app.apiClient.get(`/v1/agent/runs/${runId}`);
        } catch (e) {
            this.app.showSystemMessage(`❌ Could not fetch ${runId}: ${e.message}`);
            return;
        }
        if (!meta.waiting || !meta.waiting.token) {
            this.app.showSystemMessage(
                `❌ ${runId} is not waiting for a response (status: ${meta.status}).`
            );
            return;
        }
        const word = answer.toLowerCase();
        const payload = { token: meta.waiting.token };
        if (word === 'approve' || word === 'yes' || word === 'y') payload.approved = true;
        else if (word === 'deny' || word === 'no' || word === 'n') payload.approved = false;
        else payload.text = answer;
        return this.respond(runId, payload);
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
            '  /task run "<desc>" --spec <name>   configure from a spec file (specs_dir); flags override the file',
            '  /task run "<desc>" --skill <name>  mount a skill (skills_dir): SKILL.md grant + references/ into read-scope; repeatable',
            '  /task ls                list runs',
            '  /task show <id>         open a run pane',
            '  /task watch <id>        open + live-tail a run',
            '  /task respond <id> approve|deny|"<text>"  answer a run parked in waiting (consent card)',
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
