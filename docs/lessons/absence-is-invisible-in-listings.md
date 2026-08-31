# A catalog sweep cannot see what stopped existing

**Verify with:** open [`docs/debt-inventory.md`](../debt-inventory.md) at
**Item 38** and compare the 2026-08-31 sweep to the 2026-07-11 one below it;
then read the `NVIDIA_DEPRECATIONS` rows added on 2026-08-31 in
[`ppxai/engine/model_deprecations.py`](../../ppxai/engine/model_deprecations.py)
— each quotes the HTTP 410 body that the earlier method could not have seen.

## What happened

The model-catalog sweep read each provider's `/models` listing and compared
it against the shipped config. On 2026-08-31 a sweep by that method would
still have passed. Calling the endpoints instead found **four configured
NVIDIA models dead**, one of them the shipped default *and* coding model:

```
qwen/qwen3.5-122b-a10b             410  EOL 2026-07-20   <- shipped default
qwen/qwen3-next-80b-a3b-instruct   410  EOL 2026-07-27
deepseek-ai/deepseek-v4-pro        410  EOL 2026-08-07   -> renamed …-pro-0813
deepseek-ai/deepseek-v4-flash      410  EOL 2026-08-07   -> renamed …-flash-0731
```

Two had died **before** the previous sweep and it missed them.

## Why the listing could not show it

A retired model simply **vanishes** from `/models`. So an id nobody thinks
to look for is indistinguishable from an id that is fine — both are "not
something I noticed in this list". Reading a list of what exists tells you
nothing about what stopped existing, unless you arrive with the specific
names you care about and check each one.

Calling the endpoint is different in kind, not degree. NVIDIA answers:

```
HTTP 410 {"title":"Gone","detail":"The model '…' has reached its end of life
          on 2026-08-07T09:00:00Z and is no longer available."}
```

That is a *dated, per-id* answer. The listing has no way to express it.

## The rule

**Sweep the ids you ship, against the API — do not scan the catalog for
familiar names.** For every configured model: call it, and treat any 4xx as a
finding. The catalog listing is still useful for *discovering successors*;
it is unusable for detecting your own breakage.

The same asymmetry appears elsewhere: a config key that moved is invisible to
every accessor (only a scan of the config *file* finds it — see
[`clean-break-config-moves-need-a-file-scan.md`](clean-break-config-moves-need-a-file-scan.md)),
and a `/models` listing is the accessor here.

## A replacement is a liveness claim, and claims decay

The same sweep found `/doctor` migrating users **from one dead model to
another**: four existing deprecation rows named a model that had since died,
and the "recommended new models" list recommended one dead six weeks.

A `replacement` field asserts that a model is alive *at the moment someone
reads it*, which is always later than when it was written. So re-verify every
replacement whenever its provider is swept — not just the deprecated ids.

Three `/doctor` invariants caught these, one per defect
(`test_example_config_has_no_deprecated_models`, the recommended-default
check, the recommended-new-model check). They are cheap and they earned their
keep: each failure named the exact contradiction.

## Presence is not entitlement either (added the same day, the hard way)

The fix for the above set the NVIDIA default to `moonshotai/kimi-k2.6`,
justified as "verified live" — because the id was **in** the `/models`
listing. Calling it says otherwise:

```
HTTP 404 {"status":404,"title":"Not Found",
          "detail":"Function '…': Not found for account '…'"}
```

The id exists. The account is not entitled to it. `/models` cannot express
that, so a listing check reports success for a model that fails every real
request. `moonshotai/kimi-k3` answers 200 and is the working default.

This was committed **hours after this file was written**, in the very commit
that fixed the defect this file describes. That is worth stating plainly,
because it shows the failure mode is not ignorance of the rule:

> The listing tells you about *names*. Only a call tells you about *your
> ability to use them*. Absence and presence are BOTH uninformative — a
> retired model vanishes, and an un-entitled model is indistinguishable from
> a working one.

So the rule has no "unless you can see it in the catalog" exemption. Reaching
for the listing is fastest exactly when you are confident, which is exactly
when the check is load-bearing.

## Cost of learning it the other way

Four models shipped broken for up to six weeks, including the NVIDIA default,
so every fresh install on that provider pointed at an HTTP 410.
