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

## The test suite reads whichever file wins — including yours

The same search order applies **inside pytest**, and nothing in
`tests/conftest.py` pins it. So a test that resolves model facts reads the
first of `PPXAI_CONFIG_FILE` / `./ppxai-config.json` / `~/.ppxai/ppxai-config.json`
that exists — on a developer machine, routinely the developer's own config.

Measured 2026-08-31: `tests/test_perplexity_two_wires.py` failed on a dev host
because that host's `~/.ppxai/ppxai-config.json` carried a
`facts.tool_mode = "native"` override for `perplexity/sonar`, while the test
asserts the shipped `auto`. Nothing was wrong with the repo. The same test
passes on CI, where no user config exists.

Two consequences worth internalising:

- **A red test can be your config, not the code.** Before debugging, check
  what the suite is actually reading:
  ```bash
  python -c "from ppxai.config.facts_config import find_config_file; print(find_config_file())"
  ```
  Run it *inside* pytest if the answer looks surprising — `initialize()` may
  not have run in your shell, so a bare invocation can report the
  project-local file while the suite reads the user-global one.

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
