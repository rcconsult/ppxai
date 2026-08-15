# Module-level `Path.home()` constants let tests write the user's real state

**TL;DR:** `SESSION_STATE_FILE = Path.home() / ".ppxai" / "session-state.json"`
is resolved **at import time**. A test that isolates `sessions_dir` through a
constructor — or monkeypatches `HOME` after import — still writes the real
file. `tests/test_v1_session_migration.py` did exactly that, and every full
suite run silently clobbered the developer's session pointer, surfacing hours
later as *"session restore is broken in the TUI"*.

**Verify with:**
```bash
# The constants resolved at import time
grep -rn "^[A-Z_]* *= *Path.home()" ppxai/ --include=*.py

# The guard, and why it is autouse
grep -n "_isolate_session_state_pointer" -A20 tests/conftest.py
```

## Corollary: `PPXAI_HOME` is NOT an environment variable

The name invites the wrong fix. Reaching for isolation, the obvious move is
`PPXAI_HOME=/scratch pytest ...` — and it does **nothing**, silently. There
is no reader:

```bash
# The definition: a module constant off Path.home(), resolved at import
grep -n "^PPXAI_HOME" ppxai/config/loader.py     # -> Path.home() / ".ppxai"

# The readers: there are none
grep -rn "PPXAI_HOME" ppxai/ --include=*.py | grep -E "environ|getenv"   # -> empty
```

**Why the trap is so easy to fall into:** six sibling `PPXAI_*` names ARE
read from the environment — `PPXAI_CONFIG_FILE`, `PPXAI_DEBUG`,
`PPXAI_FORWARDED_ALLOW_IPS`, `PPXAI_IMAGE_PROTOCOL`, `PPXAI_TERMINAL`,
`PPXAI_WEB_DIR`. So the convention appears to exist, and the one name that
looks most like a home-directory override is the exception.

The failure mode is the dangerous kind: the run **looks** isolated, still
reads real `~/.ppxai`, and a host-state-dependent failure reproduces
identically while appearing to be ruled out. A false negative, not an error.

**What actually works:**

1. `env HOME=/scratch pytest ...` — set at *process launch*, so
   `Path.home()` resolves elsewhere before `loader` is first imported.
   Caveat: this also moves caches and dotfiles for everything else
   in-process, so a fixture depending on real host config may fail for an
   unrelated reason.
2. Patch `ppxai.config.loader.PPXAI_HOME` — or the constant as bound on the
   *importing* module's namespace — **before** the consumer reads it.
   Patching after import does nothing, for the same import-time reason as
   the main lesson above. Mock the helper, not `HOME`.

Found 2026-08-15 when a sibling-repo session used method-zero, got a clean
result, and checked why before trusting it.

## How it was proven, not inferred

```bash
stat -c '%y' ~/.ppxai/session-state.json      # 22:58:50
uv run pytest tests/test_v1_session_migration.py -q   # 9 passed
stat -c '%y' ~/.ppxai/session-state.json      # 23:08:06  ← the test wrote it
```

The pointer then named a fixture session (`v1_with_image`, `working_dir:
/home/user/projects/ops` — not a path on the machine). The TUI found a pointer
whose session file did not exist, cleared it as stale (correct behaviour), fell
back to newest-on-disk, and restored nothing.

Web and VSCode were unaffected because the server resolves sessions through its
own manager — which is why the symptom looked like a TUI-only regression and
invited a TUI-shaped fix.

## The fix is suite-wide, not per-test

`tests/conftest.py` redirects the constant in an **autouse** fixture. Fixing
only the guilty test leaves the next one free to reintroduce it, and this had
recurred often enough to be a class rather than an incident. Tests that need
their own pointer still patch it themselves — an inner patch wins and unwinds
back to the tmp path.

## Still unguarded — the same class

Only `SESSION_STATE_FILE` is protected today. These resolve `Path.home()` at
import time too, and tests write through them:

| Constant | Consequence |
|---|---|
| the logger's `~/.ppxai/logs/` (`common/logger.py`) | **test runs interleave with the user's real debug logs** — anyone debugging a TUI problem reads a mixture of their session and the last suite run |
| `config/loader.py:30 PPXAI_HOME` | the root under which runs, sessions and uploads live |
| `engine/bootstrap.py:67 HINT_TEMPLATES_FILE` | user hint templates |
| `engine/session_store.py:55 _DEFAULT_STAGING_DIR` | upload staging |
| `server/routes/files.py:38 _PREVIEW_CACHE_ROOT` | preview cache |

The logs one is not hypothetical: it made monitoring a live trial nearly
useless, because fixture runs (`task='x'`, `task='secret'`) appeared in the
same file as the user's session.

## The rule

- A path constant resolved at import time **cannot** be redirected by
  patching `HOME` afterwards. Patch the constant, in `conftest.py`, autouse.
- Isolating a directory through a constructor argument is not isolation if the
  module also holds a home-resolved constant.
- When a user reports "X broke after your change", check whether **running the
  test suite** is what broke it. Here the correlation with engine changes was
  real but the cause was not the changes — it was the suite that followed them.
