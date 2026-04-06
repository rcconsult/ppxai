/**
 * StreamHandler — SSE streaming client for the /chat endpoint.
 *
 * Extracted from app.js v1.16.2.
 * Handles fetch, SSE line-buffering, and JSON parsing.
 * Yields parsed event objects as an async generator so callers
 * can process events sequentially without callback nesting.
 *
 * Usage:
 *   this.streamHandler = new StreamHandler({ serverUrl, getHeaders });
 *   for await (const event of this.streamHandler.stream(message, signal)) {
 *       // event.type + event.data
 *   }
 */

class StreamHandler {
    /**
     * @param {object}   opts
     * @param {string}   opts.serverUrl  - Base server URL
     * @param {function} opts.getHeaders - (includeContentType?) => headers object
     */
    constructor({ serverUrl, getHeaders }) {
        this.serverUrl  = serverUrl;
        this.getHeaders = getHeaders;
    }

    /** Update server URL (e.g. when user changes settings). */
    setServerUrl(url) {
        this.serverUrl = url;
    }

    /**
     * POST a message to /chat and yield parsed SSE events.
     *
     * The generator terminates when the stream ends or when the
     * provided AbortSignal fires (throws AbortError).
     *
     * @param {string}      message
     * @param {AbortSignal} [signal]
     * @yields {{ type: string, data: * }}
     */
    async* stream(message, signal, files = []) {
        // v1.17.4 Phase 5.3: include files array when attachments are present.
        // The server ChatRequest model accepts `files: [{name, media_type, data}]`
        // where data is base64. When files is empty the body is identical to
        // the pre-Phase-5 format (just `{message}`) so backward compat is free.
        const body = files.length > 0
            ? { message, files }
            : { message };
        const response = await fetch(`${this.serverUrl}/chat`, {
            method:  'POST',
            headers: this.getHeaders(true),
            body:    JSON.stringify(body),
            signal
        });

        if (!response.ok) {
            throw new Error(`Server error: ${response.statusText}`);
        }

        const reader  = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;

            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split('\n');
            buffer = lines.pop() || '';   // keep any incomplete trailing line

            for (const line of lines) {
                if (!line.startsWith('data: ')) continue;
                let event;
                try {
                    event = JSON.parse(line.slice(6));
                } catch (e) {
                    if (!(e instanceof SyntaxError)) throw e;
                    continue;  // ignore malformed SSE lines
                }
                yield event;
            }
        }
    }
}

// Browser global export
if (typeof window !== 'undefined') {
    window.StreamHandler = StreamHandler;
}
