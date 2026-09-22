/**
 * The extension's ONE general-purpose output channel ("ppxai").
 *
 * Owner decision 2026-09-22: `SchemaGuard`'s compatibility diagnostics were
 * routed (2026-09-21, owner decision 10) into `HttpClient`'s "ppxai HTTP"
 * channel — a channel privately owned by `HttpClient` for session/SSE/
 * consent tracing. A compatibility diagnostic is not HTTP tracing, so that
 * was a semantic mismatch (flagged by the agent that made the original
 * change). This module gives non-HTTP, user-relevant extension diagnostics
 * a channel of their own instead of overloading "ppxai HTTP" or the
 * Extension Host console, which most users never open.
 *
 * Deliberately minimal: one `vscode.OutputChannel`, one `appendLine` surface.
 * No levels, no formatters, no file sinks — that is a logging framework this
 * module is NOT trying to be. "ppxai HTTP" keeps its own channel and its own
 * existing callers unchanged; this is a SEPARATE, second channel, not a
 * rename or a merge.
 *
 * Lazily created (first call to `getOutputChannel()` or `log()`), and
 * disposed by VSCode because `extension.ts::activate` pushes the channel
 * returned by `getOutputChannel()` into `context.subscriptions`.
 */

import * as vscode from 'vscode';

const CHANNEL_NAME = 'ppxai';

let _channel: vscode.OutputChannel | null = null;

/**
 * The shared "ppxai" output channel. Created on first call; subsequent
 * calls return the same instance. `extension.ts::activate` calls this once
 * and registers the result for disposal — callers elsewhere (e.g. `log()`)
 * never need to think about lifecycle.
 */
export function getOutputChannel(): vscode.OutputChannel {
    if (!_channel) {
        _channel = vscode.window.createOutputChannel(CHANNEL_NAME);
    }
    return _channel;
}

/** Append one line to the "ppxai" output channel. */
export function log(message: string): void {
    getOutputChannel().appendLine(message);
}

/**
 * Drop the cached channel. Extension-host lifecycle disposes the real
 * channel via `context.subscriptions`; this only clears the module-level
 * reference so a later `getOutputChannel()` call (e.g. a fresh
 * `activate()` in a test harness) creates a new one instead of reusing a
 * disposed instance.
 */
export function resetOutputChannel(): void {
    _channel = null;
}
