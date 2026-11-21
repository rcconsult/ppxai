# ADR 0019: One citation contract for chat, `/run` and `/task`

- **Status:** Proposed (2026-11-21). The owner chose option B (below), with
  sources numbered **per turn** and stored **with the message in the
  transcript**. For Gemini's built-in search grounding the owner chose
  **G2** (2026-11-21, after a live probe): sources into the ledger, the
  appended block dropped, `[n]` markers placed from `grounding_supports`
  (§ "Gemini's built-in search grounding").
- **Deciders:** owner
- **Target:** not set.
- **Related:** ADR 0014 (search layer, retrieval grounding,
  `grounding.sources` on `/v1/oneshot`), ADR 0006 (engine-internal message
  fields that are not sent on the wire), ADR 0011 (`/run`, `/task`,
  collecting into a conversation), ADR 0018 (a run's result merges once).
- **Reported by:** tai, against `feature/v1.19.5` @ `a8709026`: "A grounded
  `/run` drops its sources, so its `[n]` citations can't be resolved."

## Context

`/run` and `POST /v1/oneshot` are meant to be one brain (ADR 0011), and
chat, `/run` and `/task` should show the user the same thing when an answer
cites the web. They don't. Each place that finds sources turns them into
text at that point, and the only structured record lives in one HTTP
route.

| Where sources come from | What the model sees | What the client gets | Used by |
|---|---|---|---|
| Retrieval grounding (`engine/search/grounding.py::grounded_prompt`) | A numbered `[n] title url` list; told to cite `[n]` | `/v1/oneshot`: `grounding.sources`, built by `_grounding_record()` in `server/routes/oneshot.py`. `/v1/agent/run`: nothing; `create_agent_run`'s runner (`server/routes/agent_v1.py`) uses the result for the prompt and the usage record, then drops it | `/v1/oneshot`, `/run` |
| The `web_search` tool (`engine/tools/builtin/web_premium.py::_format_search_result`) | An unnumbered `- title url` list per call. A run can search several times, so any `[n]` the model writes uses its own numbering | Nothing structured | chat with tools, `/task`, `/run` with `execution.run.web_search` |
| Gemini's built-in search grounding (`engine/providers/gemini.py`) | No source list; see § "Gemini's built-in search grounding" | A `**Sources:**` block appended to the answer text, plus `metadata["citations"]` that no client reads | chat on Gemini with tools off, `/v1/oneshot` and `/run` under `grounding: native` |
| Chat's system prompt (`engine/chat.py`, added when the provider has the `citations` or `web_search` capability) | "write `[1](https://…)`" | Whatever links the model writes inline | chat |
| `ChatResponse.citations` (`engine/types.py`) | – | Declared, never filled | nobody |

None of the four clients (web, VSCode, Rich, Textual) renders a sources
list. A conversation keeps only the answer text, so a source the model did
not write out as a link is gone once the turn ends, including from exports
and reloaded sessions.

The root cause: there is no engine-owned notion of a source. The one
structured record, `OneshotGrounding.sources`, was added at the route layer
in ADR 0014, so `agent_v1.py` could reuse the search helpers but not the
record, and the engine's own paths (chat, the task runner) never had one.

## Decision

1. **One `Source` type, owned by the engine.** It lives in a new module
   `ppxai/engine/search/sources.py`, so it stays free of providers, which
   `tests/test_search_layer_imports_no_providers.py` already fences.

   ```python
   @dataclass(frozen=True)
   class Source:
       n: int                 # the number the model cites, [n]
       url: str
       title: str | None      # Gemini: the domain, beside an opaque redirect URL
       backend: str | None    # "gemini", "perplexity", "duckduckgo", ...
       query: str | None      # the search that found it
   ```

2. **One source list per turn (`SourceLedger`).** A turn is one user
   message up to the final assistant message, with every tool call in
   between. A `/run` is one turn. A `/task` run is one turn too, however
   many iterations it takes. Numbering starts at 1 for each turn. Adding a
   URL that is already in the list returns its existing number.

3. **Every producer adds to the ledger and numbers from it:**
   - Retrieval grounding: `grounded_prompt` takes its numbers from the
     ledger instead of counting from 1 itself.
   - The `web_search` tool: its output becomes `[n] title url`, numbered on
     from the ledger, so a second search in the same turn continues at the
     next number rather than restarting.
   - Gemini's built-in grounding: its chunks go into the ledger and `[n]`
     markers are placed from `grounding_supports` (option G2 below).

   The model is told one thing on every path: cite as `[n]`.

4. **One shape comes out on every surface:**
   - **`/v1/oneshot`:** `grounding.sources` stays exactly as it is
     (`[{url, title}]`, `[n]` = `sources[n-1]`). That surface's shape has
     been byte-identical since v1.18.4, and this ADR keeps it that way.
   - **`/run` and `/task`:** an additive `sources: list[Source]` field on
     `RunMeta` / `RunMetaResponse`, absent when the run found none, plus
     a `sources` entry in the run's event log each time the list grows, so
     a live view can show sources before the result lands. This settles
     tai's report.
   - **Chat:** `sources` in the `STREAM_END` metadata.

5. **Sources are stored with the message in the transcript.** The final
   assistant message of a turn carries `Message.sources: list[Source] |
   None`. Like `Message.attachments` (ADR 0006), it is engine-internal
   bookkeeping: providers serialize `content` only, so it is **not sent to
   the model** on later turns. It is written to the session JSON as an
   additive key (older sessions load as `None`), survives `/session load`
   and restarts, and exports render it as a Sources list under the answer.
   A run result collected into a conversation (ADR 0018) brings the run's
   sources with it onto the merged assistant message.

6. **Clients render it once each.** All four clients render a message's
   `sources` as a list under the answer and resolve `[n]` against it. A
   parity fence holds them to it, the way `CLIENT_ROUND_TRIP_KINDS` does
   for prompt kinds.

7. **Chat's inline-URL system prompt is removed**, as the last step, once
   every client renders `sources`. Before that, removing it would leave
   bare `[n]` with nothing to resolve them against.

## Why this and not the alternatives

- **A. Only store the grounding record on the run** (tai's suggested fix).
  About a day of work, but it fixes `/run` under retrieval grounding only.
  `/task`, `/run` with `web_search`, chat and Gemini would keep their own
  behaviours, which is the inconsistency this ADR exists to remove. Step 1
  below delivers A's effect, in the final shape.
- **C. Structured lists without one numbering scheme.** Each producer
  attaches its own list and the tool output stays as it is. Cheaper, but
  after two `web_search` calls a model's `[2]` does not map to one list,
  so tool-using runs stay unreliable.
- **D. Rewrite the answer on the server**, turning `[n]` into links before
  returning it. That changes the content, is ambiguous across several
  searches, and still gives clients no list.

## Considered and not chosen: numbering across the whole conversation

Kept on the record for reference. One ledger per conversation instead of
per turn: numbers keep counting across turns, and a URL seen on turn 2 has
the same number on turn 7.

- **For:** a follow-up can refer to an earlier source ("open [3]", "is [3]
  still right?") without ambiguity, and a conversation-wide Sources panel
  is a single list.
- **Against:**
  - Numbers grow without bound in a long conversation.
  - `/session load`, merges of run results (ADR 0018), checkpoint rollback
    and history trimming would all have to keep the conversation's ledger
    consistent with the messages that are still there.
  - A run collected into a conversation would need renumbering, because
    it numbered from 1 on its own.
  - Follow-ups only work if the model sees earlier sources. Decision 5
    keeps them off the wire, so this option would also need them replayed
    into the prompt, which costs tokens on every turn.
- **What would reopen it:** users asking to refer back to sources across
  turns. Decision 5 already stores what this option would need, so moving
  to it later is a change to numbering and replay, not to storage.

## Gemini's built-in search grounding

**Decided 2026-11-21: G2.** The owner asked for the issue to be laid out
and probed live first; the record of both follows.

**What happens today** (`engine/providers/gemini.py`):

1. **It only runs without ppxai tools.** `generate_content` refuses
   `google_search` together with function declarations (400
   INVALID_ARGUMENT), so `_build_config` adds Google Search only when no
   tools are sent. It runs in chat with `/tools off`, and in `/v1/oneshot`
   and `/run` under `execution.run.grounding: native`. With tools on,
   Gemini searches through the `web_search` tool, which decision 3 already
   covers. Gemini as the **retrieval backend** (`engine/search/gemini.py`)
   is a separate path and already produces a `SearchResult`.
2. **The answer has no `[n]` markers.** Google returns the sources as
   `grounding_metadata.grounding_chunks`, and a second list,
   `grounding_supports`, that maps segments of the answer text (start and
   end offsets) to the chunks that support them. ppxai reads only the
   chunks.
3. **ppxai appends a numbered list the text never refers to.**
   `_inject_citations` adds `**Sources:**` with the first five chunks as
   `[i](url) - title` to the end of the answer. The numbers point at
   nothing in the text.
4. **When streaming, the block is not in the stream.** It is appended to
   the `STREAM_END` content after every chunk has been sent, so the live
   text and the stored message differ. Whether a client shows the block
   depends on whether it re-renders from `STREAM_END`; not checked per
   client.
5. **`metadata["citations"]` has two shapes:** a list of URL strings when
   streaming (titles lost) and a list of `{title, url, domain}` dicts when
   not. Neither is capped at the five shown in the text. No client reads
   either.
6. **`/v1/oneshot` under `native` returns no `grounding` record**: the
   route passes it on the retrieve path only. Gemini's sources reach a
   `/v1/oneshot` caller only as the appended text.
7. The URLs are opaque `vertexaisearch.cloud.google.com` redirects and the
   titles are domains. That is the backend's data and none of the options
   change it.

**Options:**

- **G1. Add to the ledger and keep the appended block.** The structured
  list comes from the chunks, and the text stays as it is today. Safe, but
  the sources show twice in a client that renders `sources`, and the
  numbers in the text still point at nothing.
- **G2. Add to the ledger, drop the block, and insert `[n]` markers from
  `grounding_supports`.** Each supported segment gets the numbers of its
  chunks, so the text cites like every other path. This is the closest to
  the rest of the contract. The probe below answers both of its questions:
  the offsets are UTF-8 bytes, and when streaming the supports arrive with
  the last chunk, so markers can only go into the final text.
- **G3. Add to the ledger and drop the block, no markers.** The client
  shows an unnumbered list of sources under the answer. Simple, but this
  path would be the only one where the text cites nothing.

**Live probe, 2026-11-21** (`gemini-3.8-flash`, built-in Google Search,
one German prompt with umlauts, sent once without streaming and once with):

- **The offsets count UTF-8 bytes, not characters.** In both calls the one
  support's `segment.text` equals the answer's bytes `[start:end]`; sliced
  as characters it runs past the sentence (`... Dembélé. Der` instead of
  `... Dembélé`). Any marker insertion must convert byte offsets.
- **Supports cover only part of the answer.** Of two sentences, only the
  first (the 2025 fact, from the search) had a support, pointing at both
  chunks; the second (the 2022 fact) had none. So G2 marks the grounded
  sentences and leaves the rest unmarked, which is accurate.
- **When streaming, the metadata arrives once, on the last chunk** (chunk
  3 of 3, with 2 chunks and 1 support), after all the text has been sent.
  G2 can therefore place markers only in the final `STREAM_END` text, not
  in the live stream.
- **`web.domain` is empty;** `web.title` holds the domain (`uefa.com`,
  `eurosport.de`), and every URI is a `vertexaisearch` redirect. The
  `domain` that `_parse_grounding` reads is always `''`.
- Two chunks per answer, against the five `_inject_citations` allows for.
- `web_search_queries` lists the searches Gemini ran (one or two here).
  They can fill `Source.query`.

Each option also fixes items 5 and 6: one shape in the metadata, and the
sources in `/v1/oneshot`'s `grounding` under `native`. For `/v1/oneshot`
that is a new field value on an existing optional field, so it needs
checking against the byte-identity promise before it ships.

## Implementation order

Each step can ship on its own.

1. `Source`, `SourceLedger`, and `RunMeta.sources` plus the run event, with
   `create_agent_run` filling them from retrieval grounding. This settles
   tai's report.
2. Number the `web_search` tool output from the ledger, and expose sources
   for `/task` and for `/run` with `web_search`.
3. Chat: the ledger per turn, `sources` in the `STREAM_END` metadata,
   `Message.sources` stored in the session JSON, exports, and the merge of
   a collected run.
4. All four clients render `sources`, with the parity fence.
5. Remove chat's inline-URL system prompt and the unused
   `ChatResponse.citations`.

6. Gemini (G2): `_parse_grounding` returns chunks, supports and queries;
   the chunks go into the ledger; `[n]` markers go in at each support's
   end, converting UTF-8 byte offsets to string positions; markers are
   placed in the final `STREAM_END` text only (the live stream stays
   unmarked); `_inject_citations` and its appended block are deleted;
   `metadata` carries the one ledger shape; `/v1/oneshot` under `native`
   gets `grounding.sources`, after checking that against the
   byte-identity promise. It can run in parallel with steps 2 to 4.

**Fences to add:** `/v1/oneshot`'s `grounding` stays byte-identical; no
code outside the ledger formats a source list as text (`Sources:`); every
client renders a message's `sources`; an old session JSON without
`sources` still loads.
