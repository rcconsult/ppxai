/**
 * RunController — web driver for the `/run` one-off family (U3, ADR 0011).
 *
 * `/run` is the UX rename+reshape of the retired `/agentrun`: an async
 * `kind=oneshot` registry run on the same gears as `/task`, with the grant
 * decided by SERVER config, never by the user:
 *
 *   /run <prompt>        launch — no flags by design. The effective grant is
 *                        {} (closed-book) or {web_search} when the operator
 *                        sets execution.run.web_search — the same rule the
 *                        POST /v1/oneshot facade applies ("one brain").
 *   /run ls | get <id> | watch <id> | cancel <id> | collect <id> | help
 *                        shared lifecycle dispatch with /task (U2 grammar:
 *                        verb + run id or empty → lifecycle; anything else
 *                        launches). ls is kind-filtered to oneshot runs;
 *                        /task ls shows only task runs.
 *
 * Extends TaskController for the grammar + watch/pane machinery and only
 * overrides the launch (no flag parsing, POST /v1/agent/run) and the
 * family-facing strings. Results are held (T6) like /task — the pane's
 * Collect button / `collect` verb finalizes; U4 maps execution.collect.
 *
 * @version 1.19.1
 */

// Resolve the base class from the browser global (scripts load in order) or,
// under Node tests, from the sibling module.
const _TaskControllerBase =
    (typeof TaskController !== 'undefined')
        ? TaskController
        : (typeof require === 'function'
            ? require('./task-controller.js').TaskController
            : null);


class RunController extends _TaskControllerBase {
    /** @param {PpxaiApp} app */
    constructor(app) {
        super(app);
        this._cmd = '/run';
        this._kind = 'oneshot';
        this._emptyHint = 'No runs yet — start one with /run <prompt>';
        this._reopenHint = '/run ls';
    }

    /** Launch a one-off run: the whole line is the prompt. No flags. */
    async run(argline) {
        let prompt = (argline || '').trim();
        if (!prompt) {
            this.app.showSystemMessage('Usage: `/run <prompt>`');
            return;
        }
        // No flags by design (the grant is config-decided; provider/model
        // ride from the UI selection) — reject rather than silently feed
        // `--tools x` into the prompt text.
        if (/(^|\s)--\w/.test(prompt)) {
            this.app.showSystemMessage(
                '❌ /run takes no flags — the grant is decided by server config (execution.run.web_search). For explicit tool grants use /task.'
            );
            return;
        }
        // Strip one layer of outer quotes (quoting is allowed, never required).
        const q = prompt[0];
        if ((q === '"' || q === "'") && prompt.endsWith(q) && prompt.length > 1) {
            prompt = prompt.slice(1, -1).trim();
        }
        // Provider/model: same per-run-intent rule as the /agentrun
        // predecessor — UI provider rides along; the UI model only with the
        // UI's own provider (a model id is invalid on another provider).
        const provider = this.app.state.currentProvider;
        const model = this.app.state.currentModel;
        const body = { task: prompt };
        if (provider) body.provider = provider;
        if (model) body.model = model;
        let started;
        try {
            started = await this.app.apiClient.post('/v1/agent/run', body);
        } catch (e) {
            this.app.showSystemMessage(`❌ Run rejected: ${this._errText(e)}`);
            return;
        }
        const runId = started.run_id;
        this._openPane(runId, prompt, {
            tools: [], network: [], budget: {},
            provider, model,
            status: started.status || 'running',
        });
        this._breadcrumb(runId, prompt, `🤖 ${runId} — running… (in panel; chat stays usable)`);
        this._watchDetached(runId);
    }

    help() {
        this.app.showSystemMessage([
            '/run — one-off background runs (async, non-blocking). Launches directly:',
            '  `/run <prompt>` — no flags; the grant is server-config-decided (`execution.run.web_search` on → web_search only, off → closed-book)',
            '  `/run ls` — list one-off runs',
            '  `/run get <id>` — open a run pane',
            '  `/run watch <id>` — open + live-tail a run',
            '  `/run collect <id>` — collect a held result (📬 → finalized)',
            '  `/run cancel <id>` — cancel a run',
            '  A first token that is a verb only counts as one when followed by a run id (or nothing) — anything else launches.',
        ].join('\n'));
    }
}


// CommonJS export for tests; window-global for browser.
if (typeof module !== 'undefined' && module.exports) {
    module.exports = { RunController };
} else if (typeof window !== 'undefined') {
    window.RunController = RunController;
}
