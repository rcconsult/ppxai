/**
 * `/auto` completion detection, kept free of `vscode` so the Node
 * behavioural tests can drive it (tests/test_vscode_auto_loop_behavior.py).
 *
 * Smoke defect 6 (2026-09-26): the loop looked for `TASK_COMPLETE:` only in
 * `chunk` events. A turn that used tools delivers its text whole, in the
 * `done` event, so the marker was never seen and the loop ran every
 * iteration after the model had said it was finished.
 */

export const TASK_COMPLETE_MARKER = 'TASK_COMPLETE:';

/** The shape of a stream event this module reads. */
export interface AutoStreamEvent {
    type: string;
    content?: string;
}

/**
 * One iteration's reply text. Streamed chunks are accumulated; a `done`
 * event's content is the whole reply and wins when present, since the
 * tool path sends no chunks at all.
 */
export class AutoIterationText {
    private chunks = '';
    private final = '';

    add(event: AutoStreamEvent): void {
        if (event.type === 'chunk' && event.content) {
            this.chunks += event.content;
        } else if (event.type === 'done' && event.content) {
            this.final = event.content;
        }
    }

    get text(): string {
        return this.final || this.chunks;
    }
}

/**
 * The summary after the completion marker, or null when the reply does not
 * declare the task complete. A bare marker yields "Done".
 */
export function taskCompleteSummary(text: string, limit = 200): string | null {
    const at = text.indexOf(TASK_COMPLETE_MARKER);
    if (at < 0) { return null; }
    const summary = text.slice(at + TASK_COMPLETE_MARKER.length).trim();
    return summary ? summary.slice(0, limit) : 'Done';
}
