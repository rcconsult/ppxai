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
