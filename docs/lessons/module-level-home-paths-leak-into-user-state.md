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

## Corollary 2: it makes *import success* depend on the passwd database

The same constant has a deploy-time half. `Path.home()` resolves `~` via
`$HOME`, falling back to the passwd entry for the current uid. With neither
available it does not return a default — it **raises**:

```python
# measured, not inferred
with patch.dict(os.environ, {}, clear=True), \
     patch('pwd.getpwuid', side_effect=KeyError):
    Path.home()
# RuntimeError: Could not determine home directory.
```

Because `PPXAI_HOME` is module-level (`config/loader.py:30`), that raise
happens **at import of `ppxai.config.loader`** — before any application code
runs. The traceback points at ppxai's loader, not at the change that caused
it, so the cause (a base image or a `runAsUser`) is one indirection away
from the symptom.

**Not a live bug here today, and it is worth knowing why:** every shipped
image creates a real passwd entry — `deploy/docker/Dockerfile` and
`Dockerfile.multistage` use `useradd --uid 1000 ... --create-home`,
`Dockerfile.binary` uses `adduser -D -u 1000`, and
`deploy/k8s/standalone/deployment.yaml:38` pins `runAsUser: 1000`, which
*matches* those images. Safety comes from that alignment, not from the code
tolerating its absence.

**What breaks the alignment** (reasoned from the code path above, not
observed in a live cluster):

- a **distroless or scratch** base, which ships no `/etc/passwd` entries;
- **OpenShift's restricted SCC**, which assigns an arbitrary high uid with
  no passwd entry — the common real-world case;
- any `runAsUser` that does not match the image's `useradd` uid;
- dropping `--create-home`, or clearing `HOME` in the pod spec.

**Verify before changing any of those:**
```bash
grep -rnE "^FROM|^USER|useradd|adduser" deploy/ --include=Dockerfile*
grep -rn "runAsUser" deploy/ --include=*.yaml
```

Surfaced 2026-08-15 by the ppxai-sre session tracing the same constant
through its own deployment; both halves — "your isolation did not isolate"
and "import now depends on the container's passwd database" — are the same
module-level `Path.home()` root cause.

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

## Update (2026-09-21): all of "still unguarded" is now guarded, suite-wide

Debt Item 78 (`docs/debt-inventory.md`, closed 2026-09-21) measured what the
table below only warned about: one clean-tree suite run touched **214
entries** in a developer's real `~/.ppxai` — the logger's interleaved debug
logs, `PPXAI_HOME`-rooted checkpoint directories, real session files, the
`/cost` usage sink, `.preview-cache` PNGs, a staged upload, AND (see the
fourth instance below) `session-state.json` again, despite the guard that
was supposed to already cover it.

The fix is not a longer list of by-name fixtures. `tests/conftest.py`'s
`_redirect_home_to_tmp()` now moves `HOME` itself (and `USERPROFILE` for
Windows) to a fresh throwaway directory in `pytest_configure`, asserted to
run **before any `ppxai` module has been imported** — every constant in the
table below, and every other module-level `Path.home()` site the table
didn't get around to listing, resolves into the throwaway home from then on,
with no per-constant patch required. `tests/test_home_hermeticity.py`
fences it with an **empty** exemption list (a row there is a claim that a
path is read-only everywhere a test can reach it — exactly the claim that
looked true for the checkpoint directory below until someone read its
constructor) and is mutation-verified: reverting the redirect fails it by
naming the real path a component was still aimed at. Verified macOS only;
the `USERPROFILE`/`HOMEDRIVE`/`HOMEPATH` handling is unverified on Windows
and Linux.

The original table is kept below for the historical record of what was
unguarded and why each one mattered — every row is now covered by the
`HOME`-at-configure redirect, not by an added fixture per row.

| Constant | Consequence |
|---|---|
| the logger's `~/.ppxai/logs/` (`common/logger.py`) | **test runs interleave with the user's real debug logs** — anyone debugging a TUI problem reads a mixture of their session and the last suite run |
| `config/loader.py:30 PPXAI_HOME` | the root under which runs, sessions and uploads live |
| `engine/bootstrap.py:67 HINT_TEMPLATES_FILE` | user hint templates |
| `engine/session_store.py:55 _DEFAULT_STAGING_DIR` | upload staging |
| `server/routes/files.py:38 _PREVIEW_CACHE_ROOT` | preview cache |

The logs one was not hypothetical: it made monitoring a live trial nearly
useless, because fixture runs (`task='x'`, `task='secret'`) appeared in the
same file as the user's session.

## Corollary 3: an in-process patch does not survive a spawned subprocess

The most surprising instance of the class. `_isolate_session_state_pointer`
— an autouse fixture that has patched `engine.session.SESSION_STATE_FILE`
since 2026-08-09, specifically to stop the exact regression the main lesson
above describes — kept failing to stop it. `session-state.json` was still
being rewritten by the suite as of 2026-09-21, a FOURTH instance of this
same class found in the same repo.

The reason: that fixture's patch lives inside the **pytest process**. The
actual writer was a **spawned `ppxai-server` subprocess**
(`tests/test_server_smoke_e2e.py`), which gets its own fresh interpreter and
its own real, unpatched `HOME` — an in-process `monkeypatch.setattr` has no
way to reach into a child process's module table. Fixed the same way as the
rest of Item 78: moving `HOME` itself, in the environment, before any import
— since environment variables ARE inherited by spawned subprocesses, unlike
an in-process attribute patch.

**The general form:** an autouse fixture that patches an attribute is
isolation for the test process only. If anything under test spawns a real
subprocess (a smoke test launching `ppxai-server`, an integration test
shelling out), that subprocess re-resolves every module-level constant
against its own inherited environment — so the fixture's protection ends at
the process boundary, silently, with no error to say so.

## Sharpened: what "monkeypatch HOME does nothing" actually means

The main lesson's `env HOME=/scratch pytest ...` example and Item 78's fix
are not in tension, and the distinction is worth stating precisely, because
getting it backwards is how this class of bug recurs:

- **Patching `HOME` (or the constant) AFTER a module has already imported
  and resolved `Path.home()` does nothing.** The constant is a plain string
  by then; nothing reads `HOME` again to produce it. This is what "monkeypatch
  HOME does not work" has always meant in this file.
- **Setting `HOME` in the environment BEFORE the first `ppxai` import is the
  one case that does work** — and it is not a special case, it is the
  general rule working normally: every module-level `Path.home()` site
  resolves against whatever `HOME` says at THAT moment, so moving `HOME`
  first means every one of them resolves into the throwaway home, including
  ones nobody remembered to list. `tests/conftest.py::_redirect_home_to_tmp`
  does exactly this, and asserts the ordering premise instead of trusting
  it (`tests/test_home_hermeticity.py::TestTheRedirectIsInstalled::
  test_no_ppxai_module_was_imported_before_the_redirect`).

## The rule

- A path constant resolved at import time **cannot** be redirected by
  patching `HOME` afterwards. Patch the constant, in `conftest.py`, autouse.
- Isolating a directory through a constructor argument is not isolation if the
  module also holds a home-resolved constant.
- When a user reports "X broke after your change", check whether **running the
  test suite** is what broke it. Here the correlation with engine changes was
  real but the cause was not the changes — it was the suite that followed them.
