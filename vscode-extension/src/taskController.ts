/**
 * TaskController — VSCode driver for the tool-capable /v1/agent/task tier
 * (v1.19.x build plan T8a: cross-client port of the web `/task` family).
 *
 * Verb-for-verb parity with `ppxai/web/shared/task-controller.js` +
 * `agent-run-controller.js` (the parity sentinel in
 * tests/test_vscode_task_controller.py enforces it):
 *
 *   /task run "<desc>" --tools a,b,c [--allow host] [--provider p] [--model m]
 *                      [--budget iters=,time=,tokens=] [--system "…"]
 *                      [--spec <name>] [--skill <name>]
 *                      [--work-dir <path>]  (default: the session's working dir)
 *   /task ls | list          list runs
 *   /task show <id> | watch <id>   print a run's meta/result + (re)watch it
 *   /task respond <id> approve|deny|"<text>"   answer a waiting{consent} park
 *   /task ack <id>           collect a held result (completed_pending_ack)
 *   /task resume <id>        continue an interrupted/cancelled run
 *   /task cancel <id>        cooperative cancel
 *
 * Per-client idiom (the deliberate differences from the web client):
 *   - No right-panel pane stack: runs render into the chat transcript
 *     (ui.system lines + ui.result for bodies).
 *   - The T5 consent park surfaces as a native QuickPick (the same idiom as
 *     the existing shell/file consent dialogs in handlers/consent.ts), raised
 *     automatically by the watcher when a run parks — the token from the
 *     run meta rides along to POST /respond.
 *   - The watcher mirrors the web tail→poll cycle: it tails the run's live
 *     SSE events stream (tool_call / tool_denied / network_* / path_denied
 *     as one-line transcript entries — the same "what the agent DID" set the
 *     web live log shows), reacts to a T5 park (`agent_waiting`) immediately,
 *     and falls back to meta polling with the same backoff/give-up contract
 *     as the web degraded path: no run-duration ceiling, gives up only after
 *     consecutive GET failures.
 *
 * Dependency-injected (Inversion of Control, like handlers/consent.ts):
 * `TaskBackend` is the httpClient slice, `TaskUi` the webview/QuickPick
 * adapter — so the controller itself is VSCode-free and testable.
 *
 * @version 1.19.0
 */

// ============================================================================
// Wire types (the /v1/agent/* projections this controller consumes)
// ============================================================================

/** RunMetaResponse projection (routes/agent_v1.py). */
export interface AgentRunMeta {
    run_id: string;
    task: string;
    status: string;
    parent_run_id?: string | null;
    owner?: string | null;
    provider?: string | null;
    model?: string | null;
    workdir?: string | null;
    tools?: string[];
    network?: any[];
    budget?: Record<string, number>;
    resumable?: boolean;
    waiting?: {
        kind?: string;
        prompt?: string;
        token?: string;
        expires_at?: number;
    } | null;
    acked_at?: number | null;
    result?: string | null;
    error?: string | null;
}

/** The httpClient slice this controller drives (see httpClient.ts). */
export interface TaskBackend {
    agentTask(body: Record<string, any>): Promise<{ run_id: string; status: string; workdir_ignored?: boolean }>;
    agentRuns(): Promise<{ runs: AgentRunMeta[] }>;
    agentRun(runId: string): Promise<AgentRunMeta>;
    agentRunEvents(runId: string): AsyncIterable<any>;
    agentRunCancel(runId: string): Promise<any>;
    agentRunRespond(runId: string, body: Record<string, any>): Promise<any>;
    agentRunAck(runId: string): Promise<any>;
    agentRunResume(runId: string): Promise<any>;
}

/** Consent answer from the QuickPick adapter; undefined = dismissed (deny). */
export interface ConsentAnswer {
    approved?: boolean;
    text?: string;
}

/** UI adapter — chatPanel wires this to the webview + native dialogs. */
export interface TaskUi {
    /** One-line status/info into the chat transcript. */
    system(text: string): void;
    /** A run's result body (markdown) into the chat transcript. */
    result(text: string): void;
    /** T5 consent park → native QuickPick (Approve/Deny). */
    askConsent(runId: string, kind: string, prompt: string): Promise<ConsentAnswer | undefined>;
}

/** Session defaults (UI provider/model/workdir) — mirrors the web fallback rule. */
export interface TaskDefaults {
    provider?: string | null;
    model?: string | null;
    workingDir?: string | null;
}

// ============================================================================
// Argument parsing — same grammar as web/shared/task-controller.js
// ============================================================================

export interface ParsedTaskArgs {
    task: string;
    tools: string[];
    provider: string | null;
    model: string | null;
    system: string | null;
    network: { allow_outbound: any[] };
    budget: Record<string, number>;
    spec: string | null;
    skills: string[];
    workdir: string | null;
    errors: string[];
}

/** host or host/prefix → a NetworkSpec.allow_outbound entry. */
function egressEntry(s: string): any {
    const slash = s.indexOf('/');
    if (slash === -1) { return s; }                 // bare host, any path
    return { host: s.slice(0, slash), paths: [s.slice(slash)] };
}

/** "100" | "100k" | "1.5m" → number, or null if malformed. */
function num(s: string): number | null {
    const m = s.trim().match(/^(\d+(?:\.\d+)?)([km]?)$/i);
    if (!m) { return null; }
    let n = parseFloat(m[1]);
    if (m[2].toLowerCase() === 'k') { n *= 1e3; }
    else if (m[2].toLowerCase() === 'm') { n *= 1e6; }
    return n;
}

/** Parse --budget "iters=20,time=300,tokens=100k" into the BudgetSpec shape. */
function parseBudget(v: string, out: ParsedTaskArgs): void {
    v.split(',').forEach((pair) => {
        const eq = pair.indexOf('=');
        if (eq === -1) { out.errors.push(`bad --budget term: ${pair}`); return; }
        const key = pair.slice(0, eq).trim().toLowerCase();
        const n = num(pair.slice(eq + 1));
        if (n === null) { out.errors.push(`bad --budget value: ${pair}`); return; }
        if (key === 'iters' || key === 'iterations') { out.budget.iterations = Math.round(n); }
        else if (key === 'time' || key === 'time_s') { out.budget.time_s = n; }
        else if (key === 'tokens') { out.budget.tokens = Math.round(n); }
        else { out.errors.push(`unknown --budget key: ${key}`); }
    });
}

/** Split a command line into tokens, treating "…"/'…' as single tokens. */
function tokenize(s: string): string[] {
    const toks: string[] = [];
    for (const m of s.matchAll(/"([^"]*)"|'([^']*)'|(\S+)/g)) {
        toks.push(m[1] !== undefined ? m[1] : (m[2] !== undefined ? m[2] : m[3]));
    }
    return toks;
}

/**
 * Parse a `/task run` argument line into an AgentTaskRequest-shaped object.
 * Grammar-identical to the web parser; a non-empty `errors` means don't send.
 */
export function parseTaskArgs(argline: string): ParsedTaskArgs {
    const toks = tokenize((argline || '').trim());
    const out: ParsedTaskArgs = {
        task: '', tools: [], provider: null, model: null, system: null,
        network: { allow_outbound: [] }, budget: {}, spec: null, skills: [],
        workdir: null,
        errors: [],
    };
    let i = 0;
    const desc: string[] = [];
    while (i < toks.length && !toks[i].startsWith('--')) { desc.push(toks[i]); i++; }
    out.task = desc.join(' ').trim();

    const value = (name: string): string | null => {
        if (i + 1 >= toks.length || toks[i + 1].startsWith('--')) {
            out.errors.push(`${name} needs a value`);
            return null;
        }
        i += 1;
        return toks[i];
    };

    for (; i < toks.length; i += 1) {
        const t = toks[i];
        let v: string | null;
        switch (t) {
            case '--tools':
                v = value('--tools');
                if (v) { out.tools = v.split(',').map((x) => x.trim()).filter(Boolean); }
                break;
            case '--allow':
                v = value('--allow');
                if (v) { out.network.allow_outbound = v.split(',').map((x) => x.trim()).filter(Boolean).map(egressEntry); }
                break;
            case '--provider': v = value('--provider'); if (v) { out.provider = v; } break;
            case '--model':    v = value('--model');    if (v) { out.model = v; }    break;
            case '--system':   v = value('--system');   if (v) { out.system = v; }   break;
            case '--budget':   v = value('--budget');   if (v) { parseBudget(v, out); } break;
            case '--spec':     v = value('--spec');     if (v) { out.spec = v; }     break;
            // v1.19.x workdir-alignment: explicit per-run working dir. Without
            // it the session's working dir rides along (see run()).
            case '--work-dir': v = value('--work-dir'); if (v) { out.workdir = v; } break;
            case '--skill':
                // T4: repeatable and/or comma-separated — skills compose.
                v = value('--skill');
                if (v) {
                    for (const s of v.split(',').map((x) => x.trim()).filter(Boolean)) {
                        if (!out.skills.includes(s)) { out.skills.push(s); }
                    }
                }
                break;
            default:
                out.errors.push(`unknown flag: ${t}`);
        }
    }
    return out;
}

// ============================================================================
// Controller
// ============================================================================

/** Statuses that end the poll watcher (parity with the web _TERMINAL set). */
export const TERMINAL_STATUSES = new Set([
    'completed', 'completed_pending_ack', 'finalized',
    'failed', 'cancelled', 'interrupted',
]);

/** Success statuses whose record carries a result body to render. */
export const SUCCESS_STATUSES = new Set([
    'completed', 'completed_pending_ack', 'finalized',
]);

/**
 * Terminal SSE run-event types (parity with the web _TERMINAL_EVENTS set).
 * The live stream stays open after the run ends, so the tail loop must
 * break on these; `agent_run_cancelling` is a transition, NOT terminal.
 */
export const TERMINAL_EVENTS = new Set([
    'agent_run_complete', 'agent_result_ready', 'agent_run_finalized',
    'agent_run_error', 'agent_run_cancelled', 'agent_run_interrupted',
]);

/**
 * One-line transcript text for a streamed action event, or null to skip.
 * Same "what the agent DID" set as the web live log (task-run-view.js
 * _eventText): tools, egress, fs denials, spawns, parks. Heartbeats
 * (agent_beat), lifecycle (agent_run_*), and unknown types render nothing —
 * the status line and renderRun() already convey those.
 */
export function eventText(ev: any): string | null {
    if (!ev || !ev.type) { return null; }
    const d = ev.data || {};
    const short = (s: any, n = 60): string => {
        const t = String(s == null ? '' : s);
        return t.length > n ? t.slice(0, n) + '…' : t;
    };
    switch (ev.type) {
        case 'tool_call':    return `→ ${d.tool || d.name || 'tool'}`;
        case 'tool_result':  return `✓ ${d.tool || 'tool'}  ${short(d.result)}`;
        case 'tool_denied':  return `⛔ tool denied: ${d.tool || ''} (off-grant)`;
        case 'network_policy_allowed': return `↗ allow ${short((d.target_host || '') + (d.target_path || ''), 80)}`;
        case 'network_policy_denied':  return `⛔ egress denied ${short((d.target_host || '') + (d.target_path || ''), 80)}`;
        case 'path_denied':            return `⛔ fs denied (${d.mode || ''}) ${short(d.target_path, 70)}`;
        case 'spawn_denied':  return `⛔ spawn denied: ${short(d.reason, 80)}`;
        case 'agent_waiting': return `✋ waiting (${d.kind || 'consent'}): ${short(d.prompt, 80)}`;
        case 'agent_resumed': return `▶ resumed — ${d.approved ? 'approved' : 'denied'}${d.via === 'timeout' ? ' (timed out)' : ''}`;
        default: return null;
    }
}

const STATUS_ICONS: Record<string, string> = {
    completed: '✅', completed_pending_ack: '📬', finalized: '✅',
    failed: '❌', running: '🤖', waiting: '✋',
    cancelled: '⏹️', cancelling: '⏹️', interrupted: '⏸️', pending: '⏳',
};

export class TaskController {
    private backend: TaskBackend;
    private ui: TaskUi;
    private getDefaults: () => TaskDefaults;
    // Poll cadence for the watcher (overridable in tests). Same contract as
    // the web degraded path: back off, no run-duration ceiling, give up only
    // after consecutive GET failures.
    pollIntervalMs = 1500;
    pollMaxIntervalMs = 30000;
    pollMaxFailures = 20;
    private watching = new Set<string>();
    // Consent parks already asked, keyed by resume token, so a still-parked
    // run doesn't re-raise the QuickPick on every poll tick.
    private consentSeen = new Set<string>();

    constructor(backend: TaskBackend, ui: TaskUi, getDefaults?: () => TaskDefaults) {
        this.backend = backend;
        this.ui = ui;
        this.getDefaults = getDefaults || (() => ({}));
    }

    /** Route `/task <verb> <rest>` to a handler (verb parity with web). */
    async handle(argline: string): Promise<void> {
        const trimmed = (argline || '').trim();
        const sp = trimmed.search(/\s/);
        const verb = (sp === -1 ? trimmed : trimmed.slice(0, sp)).toLowerCase();
        const rest = sp === -1 ? '' : trimmed.slice(sp + 1).trim();
        // Run ids never contain whitespace — id-taking verbs use only the
        // first token so a multi-line paste degrades to acting on the first
        // id instead of sending the whole blob as one bogus id (web parity).
        const firstTok = (rest.split(/\s/, 1)[0]) || '';
        switch (verb) {
            case '':
            case 'help':    return this.help();
            case 'run':     return this.run(rest);
            case 'ls':
            case 'list':    return this.list();
            case 'show':
            case 'open':
            case 'watch':   return this.show(firstTok);
            case 'cancel':  return this.cancel(firstTok);
            case 'respond': return this.respondCmd(rest);
            case 'ack':     return void await this.ack(firstTok);
            case 'resume':  return void await this.resume(firstTok);
            default:
                this.ui.system(`Unknown /task subcommand: ${verb}. Try /task help.`);
        }
    }

    /**
     * Error → transcript text. A 401 from the /v1 surface almost always
     * means "no bearer attached" — point at the in-chat fix instead of
     * only relaying the bare FastAPI detail (Item 40 VSCode trial
     * feedback: the raw 401 gave no clue that `/token` exists).
     */
    private errText(e: any): string {
        const msg = e?.message ?? String(e);
        if (e?.status === 401) {
            return `${msg} — 💡 no /v1 API token attached: run \`/token mint\` (local server) or \`/token set\` (paste one).`;
        }
        return msg;
    }

    /** /task run — launch a tool-capable sandboxed run. */
    async run(argline: string): Promise<void> {
        const spec = parseTaskArgs(argline);
        if (spec.errors.length) {
            this.ui.system(`❌ /task run: ${spec.errors.join('; ')}`);
            return;
        }
        if (!spec.task) {
            this.ui.system(
                'Usage: `/task run "<desc>" --tools <a,b,c> [--spec <name>] [--skill <name>] [--allow host] [--budget iters=,time=,tokens=] [--system "…"] [--work-dir <path>]`'
            );
            return;
        }
        const hasResolvedSource = Boolean(spec.spec) || spec.skills.length > 0;
        if (!spec.tools.length && !hasResolvedSource) {
            this.ui.system(
                '❌ /task run needs a tool grant (--tools a,b,c), a --spec, or a --skill that supplies one.'
            );
            return;
        }

        // Same fallback rule as the web client: without a --spec/--skill the
        // session's provider/model ride along as explicit per-run intent.
        const defaults = this.getDefaults() || {};
        const provider = spec.provider || (hasResolvedSource ? null : defaults.provider);
        const model = spec.model || (hasResolvedSource ? null : defaults.model);
        const body: Record<string, any> = { task: spec.task, tools: spec.tools };
        if (spec.spec) { body.spec = spec.spec; }
        if (spec.skills.length) { body.skills = spec.skills; }
        if (provider) { body.provider = provider; }
        if (model) { body.model = model; }
        if (spec.system) { body.system = spec.system; }
        if (spec.network.allow_outbound.length) { body.network = { allow_outbound: spec.network.allow_outbound }; }
        if (Object.keys(spec.budget).length) { body.budget = spec.budget; }
        // v1.19.x workdir-alignment: the session's working dir rides along as
        // per-run intent (like provider/model) so "summarize README.md" means
        // the same thing in chat and in /task run; --work-dir overrides.
        const workdir = spec.workdir || defaults.workingDir || null;
        if (workdir) { body.workdir = workdir; }

        let started: { run_id: string; status: string; workdir_ignored?: boolean };
        try {
            started = await this.backend.agentTask(body);
        } catch (e: any) {
            // Surface the tier's own guardrail messages verbatim (403 tier
            // disabled, 400 shell grant / unknown spec / missing provider).
            this.ui.system(`❌ Task rejected: ${this.errText(e)}`);
            return;
        }
        if (started.workdir_ignored) {
            this.ui.system('⚠️ sandbox seal active — --work-dir ignored; the run stays in its per-run jail.');
        }
        this.ui.system(`🛠️ ${started.run_id} — task ${started.status} (watching; /task show ${started.run_id})`);
        void this.watchDetached(started.run_id);
    }

    /** /task ls — list runs, newest first. */
    async list(): Promise<void> {
        let data: { runs: AgentRunMeta[] };
        try {
            data = await this.backend.agentRuns();
        } catch (e: any) {
            this.ui.system(`❌ Could not list runs: ${this.errText(e)}`);
            return;
        }
        const runs = data.runs || [];
        if (!runs.length) {
            this.ui.system('No task runs yet — start one with /task run "<desc>" --tools <a,b,c>');
            return;
        }
        const lines = runs.slice(0, 20).map((r) => {
            const icon = STATUS_ICONS[r.status] || 'ℹ️';
            return `${icon} ${r.run_id}  ${r.status}  ${(r.task || '').slice(0, 50)}`;
        });
        this.ui.system(['Agent runs (newest first):', ...lines].join('\n'));
    }

    /** /task show|watch <id> — print the run's state (+ result) and re-watch. */
    async show(runId: string): Promise<void> {
        if (!runId) { this.ui.system('Usage: `/task show <id>`'); return; }
        let run: AgentRunMeta;
        try {
            run = await this.backend.agentRun(runId);
        } catch (e: any) {
            this.ui.system(`❌ Could not fetch ${runId}: ${this.errText(e)}`);
            return;
        }
        this.renderRun(run);
        if (!TERMINAL_STATUSES.has(run.status)) {
            void this.watchDetached(runId);
        }
    }

    /** /task cancel <id> — cooperative cancel. */
    async cancel(runId: string): Promise<void> {
        if (!runId) { this.ui.system('Usage: `/task cancel <id>`'); return; }
        try {
            await this.backend.agentRunCancel(runId);
        } catch (e: any) {
            this.ui.system(`❌ Could not cancel ${runId}: ${this.errText(e)}`);
            return;
        }
        this.ui.system(`⏹️ ${runId} — cancel requested`);
    }

    /**
     * /task respond <id> approve|deny|"<text>" — answer a parked run (T5).
     * Fetches the meta for the resume token; approve/deny words map to
     * `approved`, anything else rides as free text (deny-with-note for a
     * consent park — fail-closed).
     */
    async respondCmd(rest: string): Promise<void> {
        const trimmed = (rest || '').trim();
        const sp = trimmed.search(/\s/);
        const runId = sp === -1 ? trimmed : trimmed.slice(0, sp);
        let answer = sp === -1 ? '' : trimmed.slice(sp + 1).trim();
        if (!runId || !answer) {
            this.ui.system('Usage: `/task respond <id> approve|deny|"<text>"`');
            return;
        }
        const q = answer[0];
        if ((q === '"' || q === "'") && answer.endsWith(q) && answer.length > 1) {
            answer = answer.slice(1, -1);
        }
        let meta: AgentRunMeta;
        try {
            meta = await this.backend.agentRun(runId);
        } catch (e: any) {
            this.ui.system(`❌ Could not fetch ${runId}: ${this.errText(e)}`);
            return;
        }
        if (!meta.waiting || !meta.waiting.token) {
            this.ui.system(`❌ ${runId} is not waiting for a response (status: ${meta.status}).`);
            return;
        }
        const word = answer.toLowerCase();
        const payload: Record<string, any> = { token: meta.waiting.token };
        if (word === 'approve' || word === 'yes' || word === 'y') { payload.approved = true; }
        else if (word === 'deny' || word === 'no' || word === 'n') { payload.approved = false; }
        else { payload.text = answer; }
        await this.respond(runId, payload);
    }

    /** POST /respond (shared by the verb and the consent QuickPick). */
    async respond(runId: string, payload: Record<string, any>): Promise<boolean> {
        try {
            await this.backend.agentRunRespond(runId, payload);
        } catch (e: any) {
            this.ui.system(`❌ Could not respond to ${runId}: ${this.errText(e)}`);
            return false;
        }
        const label = payload.approved === true ? 'approved'
            : (payload.approved === false ? 'denied' : 'answered');
        this.ui.system(`✋ ${runId} — ${label}; run resumes`);
        return true;
    }

    /** /task ack <id> — collect a held result (T6). */
    async ack(runId: string): Promise<boolean> {
        if (!runId) { this.ui.system('Usage: `/task ack <id>`'); return false; }
        try {
            await this.backend.agentRunAck(runId);
        } catch (e: any) {
            this.ui.system(`❌ Could not ack ${runId}: ${this.errText(e)}`);
            return false;
        }
        this.ui.system(`📬 ${runId} — result collected (finalized)`);
        return true;
    }

    /** /task resume <id> — conditionally continue an interrupted run (T7). */
    async resume(runId: string): Promise<boolean> {
        if (!runId) { this.ui.system('Usage: `/task resume <id>`'); return false; }
        try {
            await this.backend.agentRunResume(runId);
        } catch (e: any) {
            // The 409 refusal reason (resume_refusal matrix) verbatim.
            this.ui.system(`❌ Could not resume ${runId}: ${this.errText(e)}`);
            return false;
        }
        this.ui.system(`▶️ ${runId} — resumed (running)`);
        void this.watchDetached(runId);
        return true;
    }

    help(): void {
        this.ui.system([
            '/task — tool-capable background runs (sandboxed tier; default-off):',
            '  /task run "<desc>" --tools a,b,c [--allow host] [--provider p] [--model m] [--budget iters=,time=,tokens=] [--system "…"] [--work-dir <path>]',
            '  /task run "<desc>" --spec <name>   configure from a spec file (specs_dir)',
            '  /task run "<desc>" --skill <name>  mount a skill (skills_dir); repeatable',
            '  /task ls                list runs',
            '  /task show <id>         print a run (re-watches if still live)',
            '  /task watch <id>        alias of show',
            '  /task respond <id> approve|deny|"<text>"  answer a run parked in waiting (a QuickPick also pops automatically)',
            '  /task ack <id>          collect a held result (📬 completed_pending_ack → finalized)',
            '  /task resume <id>       continue an interrupted/cancelled run from its checkpoint',
            '  /task cancel <id>       cancel a run',
        ].join('\n'));
    }

    // ── Internals ─────────────────────────────────────────────────────────

    /** Render a run's current state into the transcript. */
    private renderRun(run: AgentRunMeta): void {
        const icon = STATUS_ICONS[run.status] || 'ℹ️';
        const bits = [`${icon} ${run.run_id} — ${run.status}`];
        if (run.provider || run.model) { bits.push(`${run.provider || ''} · ${run.model || ''}`); }
        if (run.tools && run.tools.length) { bits.push(`tools: ${run.tools.join(', ')}`); }
        if (run.workdir) { bits.push(`wd: ${run.workdir}`); }
        this.ui.system(bits.join('  |  '));
        if (SUCCESS_STATUSES.has(run.status) && run.result) {
            this.ui.result(run.result);
            if (run.status === 'completed_pending_ack') {
                this.ui.system(`📬 result held — collect with /task ack ${run.run_id}`);
            }
        } else if (run.error) {
            this.ui.system(`   ${run.error}`);
            if (run.resumable && (run.status === 'interrupted' || run.status === 'cancelled')) {
                this.ui.system(`▶️ resumable — /task resume ${run.run_id}`);
            }
        }
    }

    /** Deduped detached poll watcher (parity with the web watcher contract). */
    private async watchDetached(runId: string): Promise<void> {
        if (this.watching.has(runId)) { return; }
        this.watching.add(runId);
        try {
            await this.runWatch(runId);
        } finally {
            this.watching.delete(runId);
        }
    }

    private sleep(ms: number): Promise<void> {
        return new Promise((r) => setTimeout(r, ms));
    }

    /**
     * The tail → poll → render cycle (parity with the web _runWatch).
     *
     * Tail the run's live SSE events first: action events become one-line
     * transcript entries, and a T5 park (`agent_waiting`) raises the consent
     * QuickPick IMMEDIATELY — no poll-backoff latency between the park and
     * the dialog. The stream can end/fail BEFORE the run is terminal
     * (transient outage, older server, proxy buffering), so ALWAYS fall back
     * to meta polling until the run actually finishes, then render.
     */
    private async runWatch(runId: string): Promise<void> {
        try {
            for await (const ev of this.backend.agentRunEvents(runId)) {
                const line = eventText(ev);
                if (line) { this.ui.system(`  ${line}`); }
                if (ev && ev.type === 'agent_waiting') {
                    // Park discovered live — fetch the meta for the resume
                    // token and ask now (deduped per token in maybeAskConsent).
                    let parked: AgentRunMeta | null = null;
                    try { parked = await this.backend.agentRun(runId); } catch { parked = null; }
                    if (parked) { await this.maybeAskConsent(runId, parked); }
                }
                if (ev && TERMINAL_EVENTS.has(ev.type)) {
                    // The stream replays the persisted backlog first, so a
                    // RESUMED run's tail sees the historical
                    // agent_run_interrupted/_cancelled from before the resume —
                    // breaking on that stale replay detaches the fresh tail
                    // (T7 live-trial bug, parity with the web fix). The run
                    // record is the source of truth: break only when the run
                    // is REALLY terminal right now.
                    let now: AgentRunMeta | null = null;
                    try { now = await this.backend.agentRun(runId); } catch { now = null; }
                    if (!now || TERMINAL_STATUSES.has(now.status)) { break; }
                }
            }
        } catch {
            // Live stream unavailable — degrade silently to the poll path.
        }
        const run = await this.pollUntilTerminal(runId);
        if (!run) {
            this.ui.system(`⚠️ ${runId} — lost contact with the server; /task show ${runId} to retry.`);
            return;
        }
        this.renderRun(run);
    }

    /**
     * Degraded-path poll (also the terminal-meta fetch after a clean tail):
     * GET the run until terminal, then return it. On a T5 park, raise the
     * consent QuickPick (once per resume token). Gives up (null) only after
     * pollMaxFailures CONSECUTIVE GET failures — never on run duration.
     */
    private async pollUntilTerminal(runId: string): Promise<AgentRunMeta | null> {
        let delay = this.pollIntervalMs;
        let failures = 0;
        for (;;) {
            let run: AgentRunMeta | null = null;
            try {
                run = await this.backend.agentRun(runId);
            } catch {
                run = null;
            }
            if (run) {
                failures = 0;
                if (TERMINAL_STATUSES.has(run.status)) {
                    return run;
                }
                await this.maybeAskConsent(runId, run);
            } else if (++failures >= this.pollMaxFailures) {
                return null;
            }
            await this.sleep(delay);
            delay = Math.min(delay * 2, this.pollMaxIntervalMs);
        }
    }

    /**
     * Raise the consent QuickPick for a waiting{consent} park — once per
     * resume token (shared by the SSE tail and the poll path, so a park
     * surfaced by both never double-asks).
     */
    private async maybeAskConsent(runId: string, run: AgentRunMeta): Promise<void> {
        if (run.status !== 'waiting' || !run.waiting || !run.waiting.token) { return; }
        if (this.consentSeen.has(run.waiting.token)) { return; }
        this.consentSeen.add(run.waiting.token);
        const answer = await this.ui.askConsent(
            runId, run.waiting.kind || 'consent', run.waiting.prompt || ''
        );
        // Dismissed dialog = no answer sent; the park's TTL is the
        // fail-closed backstop (and /task respond still works).
        if (answer) {
            const payload: Record<string, any> = { token: run.waiting.token };
            if (answer.approved !== undefined) { payload.approved = answer.approved; }
            if (answer.text) { payload.text = answer.text; }
            await this.respond(runId, payload);
        } else {
            this.ui.system(
                `✋ ${runId} is waiting — answer with /task respond ${runId} approve|deny`
            );
        }
    }
}
