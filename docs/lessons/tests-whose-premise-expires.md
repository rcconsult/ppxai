# A test can keep passing after its premise stops being true

**Verifiable:** open
[`tests/test_wire_responses_extraction.py`](../../tests/test_wire_responses_extraction.py)
and find `get_handler("carrier_pigeon")`. The deliberately absurd name is the
lesson — grep the repo and you will not find a wire by that name, which is
the point.

## What happened

ADR 0012 W2 added a fence proving the handler registry **refuses** an
unknown protocol rather than silently falling back:

```python
with pytest.raises(KeyError, match="no wire-protocol handler"):
    get_handler("generate_content")     # W2: not yet implemented
```

W4 then implemented `generate_content`. The test did not fail — it went
green while asserting nothing about refusal, because the name it used had
become a *registered* handler. A fence that cannot fail is worse than no
fence: it reports safety it is no longer checking.

The fix was to pick a name no wire will ever claim, not to weaken the
assertion:

```python
get_handler("carrier_pigeon")           # W4: unclaimable by construction
```

## The pattern to watch for

A test whose subject is **"X is absent / unsupported / not yet built"**
carries a hidden dependency on X staying absent. The roadmap is usually
committed to making X exist. Candidates in this repo:

- "protocol/backend/tool `N` is not registered"
- "config key `K` is not read anywhere"
- "provider `P` has no such capability"
- anything asserting a `NotImplementedError`, a `KeyError`, or an empty
  collection

## The rule

When you assert an absence, ask: **what would make this present, and is it
on the plan?** If yes, express the absence in a form the plan cannot reach —
an impossible name, a synthetic sentinel, a generated id — rather than
borrowing today's unimplemented feature as the example.

Same family as a fixture edited to agree with new code: both produce a test
that passes for a reason unrelated to what it claims to check.

## The mirror image

[`stale-tests-outlive-deleted-behavior.md`](stale-tests-outlive-deleted-behavior.md)
covers the opposite direction: behaviour is **removed** and its tests keep
passing against a path that no longer exists. This lesson is the additive
case — the feature a test relied on being *absent* gets **built**. Both end
in a green test guarding nothing; check for both when a change adds or
removes a capability that any test names.
