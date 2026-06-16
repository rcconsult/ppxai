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

## Related

- `ppxai/config/loader.py` — `find_config_file()` search order + `initialize()`.
- ADR 0003 §C2 — the `server.secrets` block whose edit location this affects.
- Lesson promotion criteria: [README.md](README.md).
