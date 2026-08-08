# Passing the SDK's client-side validation is not evidence the API accepts it

**TL;DR:** A provider SDK's request model and the provider's REST API are two
different validators, and they disagree. A payload can satisfy the SDK's
pydantic model — no `ValidationError`, mocked unit tests green — and still be
rejected by the server with a 400. Any test that constructs the SDK object
without sending it proves only that the *client* is happy. The gap is
invisible until a real call is made.

**Verify with:**
```bash
# The one key where the two validators disagree, and why it is stripped
grep -n "_RESPONSE_SCHEMA_REJECTED_KEYS" -B18 ppxai/engine/providers/gemini.py

# The SDK-accepted whitelist that KEEPS the same key for the tool path
grep -n "_GEMINI_SCHEMA_KEYS" -A8 ppxai/engine/providers/gemini.py
```

`additionalProperties` is in `_GEMINI_SCHEMA_KEYS` — the whitelist of keys
the google-genai `Schema` model accepts, verified against SDK 1.56.0. It is
correct there: function declarations need it. The same key under
`generation_config.response_schema` produces:

```
400 INVALID_ARGUMENT — Invalid JSON payload received. Unknown name
"additional_properties" at 'generation_config.response_schema':
Cannot find field.
```

Same `Schema` type, same SDK, two different server-side contracts.

## How it played out (2026-08-08)

`response_format` was mapped onto Gemini's `response_mime_type` /
`response_schema`. The first implementation defined its own key whitelist and
stripped `additionalProperties`; it worked live. Review then — correctly, on
DRY grounds — replaced the duplicate with the existing
`_sanitize_schema_for_gemini`, which *keeps* `additionalProperties` because
the SDK model accepts it.

**14 unit tests stayed green.** They patch `genai` and assert on the config
object, so nothing ever sent the payload. The next live call returned 502.

The fix is a composition, not a choice between the two: reuse the shared
sanitizer for the structural work (`oneOf`→`anyOf`, `allOf` merge, list-form
`type`), then strip the keys this endpoint specifically rejects.

## The rule

- **A mocked-SDK test cannot evidence API acceptance.** It evidences that
  your code builds an object the SDK tolerates. Those are different claims.
- **Wire-shape changes need one real call before they are believed.** In this
  repo that is `scripts/gateway-smoke.py`; `--record` also captures the
  response so the change can be diffed rather than asserted.
- **"Both use the same type" is not "both accept the same fields."** Check
  per endpoint, not per class.

This is the same failure family as v1.19.0 Items 45/50/51, where green unit
tests passed while the request 400'd live and the fix had to be validated
through the real SDK type. Two independent occurrences is a pattern, not
bad luck.

Related: [stale-server-invalidates-acceptance.md](stale-server-invalidates-acceptance.md)
— the neighbouring trap. During this same investigation a live re-check
returned 502 against a server started *before* the edit; the code was already
correct. If a live check contradicts the source, confirm the process was
restarted before believing the result.
