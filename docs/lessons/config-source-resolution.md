# PPXAI_CONFIG_FILE (often set in .env) overrides ./ppxai-config.json

**TL;DR:** `find_config_file()` honors `PPXAI_CONFIG_FILE` **first**, before
the project-local `./ppxai-config.json`. A `.env` in the repo root can set
that variable, so editing the obvious project config silently has **no
effect** on a running server — it reads whatever `PPXAI_CONFIG_FILE` points
at instead.

**Verify with:**
```bash
grep -n "PPXAI_CONFIG_FILE" ppxai/config/loader.py    # priority-1 in the search order
grep -rn "PPXAI_CONFIG_FILE" .env 2>/dev/null         # your local .env may pin it
```
Or ask the running server (v1.19.0+ prints it at startup):
```
Config: <the authoritative path>
Auth providers: <chain>
```

## Why this trips people up

The documented search order (`ppxai/config/loader.py` `find_config_file`,
~line 187) is:

1. `PPXAI_CONFIG_FILE` env var (if set)
2. `./ppxai-config.json` (project-local)
3. `~/.ppxai/ppxai-config.json` (user-global)

It's natural to assume the repo-root `ppxai-config.json` wins for a server
launched from the repo root. But `initialize()` loads `./.env` (and
`~/.ppxai/.env`) via `load_dotenv`, and a developer's repo-root `.env` may
contain a line like:

```
PPXAI_CONFIG_FILE=/home/<user>/.ppxai/ppxai-config.json
```

After that load, step 1 wins and the project file is never consulted. The
failure mode is **silent**: you edit `ppxai-config.json`, restart, and your
change appears to do nothing — there's no error, the server just read a
different file. (`.env` is gitignored, so this differs per host, which is
exactly why it belongs here and not in per-host memory: the *mechanism* is
cross-host even though the specific pin is per-developer.)

This bit hard during the v1.19.0 Inc 8a trial: a `server.secrets` block
added to the repo-root config had no effect because the server was pinned
to `~/.ppxai/ppxai-config.json`.

## What's actually true

- `PPXAI_CONFIG_FILE` is **read-only** in ppxai code — it is never *set* by
  the app (`grep -rn "PPXAI_CONFIG_FILE" ppxai/` shows only the `os.getenv`
  read). If it's set in your environment, it came from your shell or a
  `.env` file, not from ppxai.
- To find the authoritative file from a shell:
  ```bash
  python -c "from ppxai.config.loader import initialize, find_config_file; initialize(); print(find_config_file())"
  ```
  Note: call `initialize()` first — it loads `.env`, which is what sets the
  override. Calling `find_config_file()` *without* `initialize()` can return
  a different (project-local) answer than the server actually uses.
- v1.19.0+ `ppxai-server` prints `Config: <path>` at startup
  (`ppxai/server/http.py::run_server`). Read that line before assuming which
  file is live.

## History: the test suite used to read whichever file won — including yours

**This section describes a problem that is fixed.** Until debt Items 69 and
78 landed, the search order above applied **inside pytest too**, and nothing
in `tests/conftest.py` pinned it. A test that resolved model facts read the
first of `PPXAI_CONFIG_FILE` / `./ppxai-config.json` /
`~/.ppxai/ppxai-config.json` that existed — on a developer machine, routinely
the developer's own config. That was measured to fail in the dangerous
direction: a stale personal config masked a real regression on one host while
CI (which has no user config) stayed green.

Since then, `tests/conftest.py::pytest_configure` copies the **tracked**
`ppxai-config.json` into the throwaway test home and pins
`PPXAI_CONFIG_FILE` at that copy (Item 69, `conftest.py:264-296`), and the
session-scoped `_the_developers_config_is_unreachable` fixture points the
`USER_CONFIG_FILE` fallback constant at a path that does not exist
(`conftest.py:336-360`). `_redirect_home_to_tmp()` also moves `HOME` itself
before the first `ppxai` import (Item 78), so the suite cannot resolve the
real `~/.ppxai/ppxai-config.json` even from a cleared environment.

**Practical effect today:** your own `~/.ppxai/ppxai-config.json` cannot
reach the suite unless you explicitly set `PPXAI_CONFIG_FILE` yourself before
running pytest. A red test is very unlikely to be "your config, not the
code" any more — but if you *did* export `PPXAI_CONFIG_FILE`, that override
still wins, so check for it first:
  ```bash
  echo "$PPXAI_CONFIG_FILE"
  python -c "from ppxai.config.loader import find_config_file; print(find_config_file())"
  ```

One consequence still worth internalising:

- **A green suite is not proof either.** The reverse case is worse: a config
  the suite reads can *mask* a defect. The repo-root `ppxai-config.json` is
  **tracked**, and it drifted for a day (a deprecated default, plus NVIDIA ids
  that had answered HTTP 410 for six weeks) with the suite green throughout —
  because every deprecation invariant scoped only `ppxai-config.example.json`.
  Fixed by iterating the tracked set (`git ls-files 'ppxai-config*.json'`) in
  `tests/test_doctor.py::TestDeprecationTableInvariants`.

**Rule:** a test that reads config resolution must either pin the file it
means (`monkeypatch.setattr(fc, "find_config_file", ...)`) or assert against
the shipped table rather than the resolved result. Otherwise its verdict is a
property of the host, not of the code.

## Related

- `ppxai/config/loader.py` — `find_config_file()` search order + `initialize()`.
- ADR 0003 §C2 — the `server.secrets` block whose edit location this affects.
- Lesson promotion criteria: [README.md](README.md).
