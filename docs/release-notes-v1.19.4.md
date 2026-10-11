# Release Notes — v1.19.4

> **Scope:** A security patch to v1.19.3, plus ADR 0013's SSH remote hub
> and a round of model, config and tooling fixes that accumulated on the
> same branch. The owner decided on 2026-10-11 that all of it ships as
> 1.19.4.
>
> - **Security:** a shell through the terminal websocket (fixed), and
>   `/task` runs are now confined to their working folder with credentials
>   always denied, and ppxai refuses to start rather than silently drop a
>   configured sandbox (see below).
> - **Who should upgrade first:** anyone who browses the web on a machine
>   that runs `ppxai-server` or `ppxai-desktop`, and anyone running the k8s
>   coder deployment.
> - **New, opt-in: the SSH remote hub and SSH Launcher.** Drive ppxai
>   servers on other hosts from your local browser. Off unless
>   `remote.hosts` is configured.
> - **Model and config changes.** Several shipped model facts changed
>   (which wire a model uses, whether it calls tools in parallel, which
>   sampling parameters it accepts), and the example config was brought in
>   line. Configs copied from an older example can override the new facts;
>   see "Upgrade".
>
> The v1 API gateway (`POST /v1/oneshot`) is **byte-identical to
> v1.19.3**, as is the `/v1/agent/*` surface. ppxai-sre and any other
> consumer of those are unaffected.

## Branch

`feature/v1.19.4`. It merged `fix/v1.19.4` (the security patch, from
master @ v1.19.3) and carries the rest. `CHANGELOG.md` `[1.19.4]` lists
every change; these notes cover what an operator needs to know.

## Security

### A web page could open a shell through the terminal websocket

**What was wrong.** The web UI's terminal is a websocket at `/ws/terminal`
that runs a PTY shell on the server's machine. The server's three
protections are HTTP middleware:

- the Host check that stops DNS rebinding;
- the bearer-token gate (`PPXAI_API_TOKEN`);
- CORS.

Starlette never passes a websocket through HTTP middleware, and browsers do
not apply CORS to websockets. So while `ppxai-server` or `ppxai-desktop`
was running, **any web page the user visited could open
`ws://127.0.0.1:<port>/ws/terminal` and run commands as the user**. Setting
`PPXAI_API_TOKEN` did not help.

**Who was exposed.**

- **Desktop and local web UI users**, whenever the server was running. On
  Windows the terminal reports "requires a Unix host" and runs no shell, but
  the handshake was still accepted unchecked.
- **k8s coder users**, to a lesser degree. The session cookie is
  `SameSite=Lax`, so other sites could not ride it. A page on the same parent
  domain, such as another app under the same `*.example.com`, could.
- **Remote servers announced for ADR 0013** (`ppxai-server --uds --announce`)
  were not reachable from a browser: they listen only on a 0600 unix socket.

**The fix.** A websocket handshake is now refused, and the client sees HTTP
403, unless all three hold:

1. its `Host` passes the same allowlist as HTTP requests;
2. its `Origin`, when it sends one, is allowed: listed in
   `PPXAI_ALLOWED_ORIGINS`, a loopback origin, or the server's own origin
   (the same host and port as a `Host` that passed step 1). A client that
   sends no `Origin` is not a browser and is judged by steps 1 and 3 alone;
3. the bearer-token gate passes, exactly as it would for a GET of the same
   path. The local UI stays exempt on loopback, as it is for HTTP.

The guard wraps the whole app, so a websocket route added later is covered
without further work.

**What this does not change.** "The same auth as HTTP" includes HTTP's
loopback rule. A process on the same machine that sends no `Origin` (not a
browser) still opens the terminal without a token, just as it can already
call the local chat API, tools included, without one. Browsers always send
`Origin`, so a web page can no longer get in. On a machine shared with other
users, the loopback trust model is unchanged by this release.

**What keeps working** (each case is pinned by `tests/test_websocket_guard.py`):

| Client | Result |
|---|---|
| The desktop/web UI's own terminal (`http://127.0.0.1:<port>`, `http://localhost:<port>`) | opens, with or without a token |
| A coder pod (wide bind, `PPXAI_TRUSTED_HOSTS` and `PPXAI_ALLOWED_ORIGINS` as the session-manager sets them) | its UI opens its terminal; a sibling-domain page is refused |
| A gateway bound wide without either variable | its same-origin UI opens its terminal; other origins are refused |
| A non-browser client with no `Origin` | same as before, subject to Host and token |

### `/task` runs are confined to their working folder by default

Until now the `/task` filesystem sandbox was off unless an operator turned
it on. Once the task tier was enabled (`execution.task.enabled`), a run
granted `read_file` could read any file the ppxai process could, including
`~/.ppxai/.env` with every provider key, without a prompt.

- **On by default:** `execution.task.sandbox.enforcement` now defaults to
  `"in_process"`.
- **Confined to the project, not to a scratch folder:** the run's working
  folder (`--work-dir`, or the session's folder, which every client now
  sends) is its only writable root and a read root, plus
  `read_paths.allow` and the skills/specs folders. Before, the sandbox
  always moved a run into an empty scratch folder and ignored `--work-dir`.
  A run with no folder at all, such as a bare API call, still gets one.
- **Credentials are always denied** to `/task` file tools, reads and writes,
  sandbox on or off: `.env` and `.env.*`, `.ssh` and SSH key files,
  `.gnupg`, `.aws`, `.azure`, `.kube`, `.docker`, `.netrc`,
  `.git-credentials`, `.npmrc`, `.pypirc`, `~/.ppxai/run`,
  `~/.ppxai/tokens*`, `~/.config/gcloud`, `~/.config/gh`. Opt out with
  `read_paths.builtin_deny: false`. Your own `read_paths.deny` now applies
  with the sandbox off too.
- **Explicit `"off"` is respected:** a config that writes
  `enforcement: "off"` stays unconfined, apart from the deny lists.
- `/v1/oneshot` and other runs without file tools are unaffected.

### ppxai refuses to start while the config has `tools.agent.sandbox`

ADR 0010 (v1.19.1) moved the `/task` filesystem sandbox from
`tools.agent.sandbox` to `execution.task.sandbox`, with no fallback. An
operator who had configured a jail (`enforcement: "in_process"`) lost it
silently on upgrade: the seal reverted to `"off"`, and the `read_paths.deny`
list (`.env`, `.ssh`, secrets) stopped applying to `/task` runs. With the
new default above, an ignored block would now silently fall back to the
defaults instead, which still loses your own paths and deny rules.

Now every entry point (`ppxai`, `ppxaide`, `ppxai-server`,
`ppxai-desktop`) refuses to start while that key is present, and prints the
file and the fix. An embedder's `EngineClient()` raises
`ppxai.config.RetiredSecurityKeyError`. It refuses even if
`execution.task.sandbox` is also set. No other key refuses; `/doctor` still
warns about the other moved `tools.agent.*` keys.

## New: SSH remote hub and SSH Launcher (ADR 0013)

Keep the client in your local browser while the engine, tools and files
stay on a remote host where ppxai is installed.

- **Turn it on** by listing hosts under `remote.hosts` in
  `ppxai-config.json` (each an `id` and an ssh destination). Without it,
  every hub path answers 404 and no `ssh` ever starts; the k8s coder pods
  are unaffected.
- **Transport:** your own `ssh` (`BatchMode=yes`, your `known_hosts`, your
  agent and `~/.ssh/config`), one `ssh -N -L` per remote server to a 0600
  unix socket on the remote. ppxai stores no keys.
- **Use it:** the header "SSH" button opens the launcher: hosts, their
  ppxai servers and attachment state; launch a server in a chosen
  directory, open its own web UI in a new tab, detach, stop. Everything
  under `/h/<host>/<id>/` is proxied, websockets and streams included.
- **Tokens:** the hub injects each remote server's token itself; it never
  reaches the browser.
- **Tools run on the remote,** under that host's own config
  (`execution.task.*`, sandbox, egress ceiling).
- **Remote hosts need a build from this release** (registry contract 2).
  The hub refuses older remote `ppxai-server` binaries with their version,
  because those failed every chat after a detached launch from a one-file
  build.

- **The hub needs its own token.** Loopback alone is not enough: any local
  program, and any other OS user, is a loopback peer. The hub keeps a token
  in `~/.ppxai/run/hub-token` (readable only by you) and requires it on
  every hub request. `ppxai-server` prints `SSH hub: open
  http://127.0.0.1:<port>/hub/auth?token=…` at startup; opening it sets a
  browser cookie (HttpOnly, SameSite=Strict). `ppxai-desktop` opens that
  URL for you. A script sends the token as `X-Ppxai-Hub-Token`. Without
  it, the launcher shows "The SSH hub is locked".

**Limits:** web UI only (VSCode and TUI clients are future work); one
user; the hub answers loopback requests only. A remote server's pages are
served under the hub's origin, so trust the remote hosts you add.

## Model and config changes

These change what ppxai sends for some models. Each is a shipped seed row
in `ppxai/engine/model_facts.py`, so it applies without a config row. **A
config row outranks the seed**, so a row copied from an older example can
undo it; `/doctor` and the example config show the current values.

| Models | Change | Why |
|---|---|---|
| `gpt-5.4-pro`, `gpt-5.6*`, `gpt-6-sol`, `gpt-6-luna` | Responses wire; native tool calls without a config row | Chat Completions answers 404 (`gpt-5.4-pro`) or 400 on tools |
| `gpt-6-sol`, `gpt-6-luna` | Serial tool calls | Parallel calls not measured yet |
| OpenRouter `anthropic/claude-*` 4.7 and newer | `temperature`, `top_p`, `top_k` not sent; native tools | Under `require_parameters` routing they answer 404 to either |
| Gemini 3.6 Flash and newer, and unlisted (newer) Gemini models | `temperature`, `top_p`, `top_k` not sent | Google: fixed defaults, 400 on upcoming models |
| `gemini-3.5-flash` | Deprecated, replacement `gemini-3.6-flash` | Google redirects every request to 3.6 (and bills 3.6) |
| Gemini 2.5 line | Nothing ppxai ships points at it any more | Sunset from 2026-10-16 (earliest) |

Also:

- **`/doctor` knows OpenAI's current deprecations** (83 rows, was 16),
  including the 2027-04-01 retirement of `gpt-5.3-codex`, `gpt-5.4-nano`
  and `gpt-5.1`.
- **The example config** (which seeds new installs) no longer contradicts
  its seeds, lists current OpenRouter models (Claude 5.5, DeepSeek V4.1
  Flash, Llama 4 Maverick, Qwen 3.8 27B), routes OpenRouter with
  `data_collection: deny` and `require_parameters`, drops the Gemini
  `generation_params` block, and orders web search Gemini first.

## Other fixes

- **Behind a corporate proxy, local connections no longer go to the
  proxy:** `/preview`, `ppxai-desktop`'s start-up check, and providers at
  `localhost` (local vLLM, Ollama, an SSH forward) now bypass
  `HTTP_PROXY`.
- **Saving the config, a session, the restore pointer or `usage.json` can
  no longer leave the file empty;** a failed read no longer wipes the
  config.
- **No hint tells you to `pip install ppxai`:** that PyPI name belongs to
  another project.
- **AGENTS.md hints are no longer sent twice** when the global and project
  files carry the same hints.
- **Benchmarks:** `--agents-md without` runs really are hint-free now, and
  `respects_tool_failure` no longer fails every model. Earlier scores for
  that test are invalid, so earlier overall scores are understated.

## Verification

- `tests/test_websocket_guard.py`: 18 tests. With the guard disabled, the
  9 tests that expect a refusal fail, the attack among them.
- Against a live `ppxai-server` over TCP (uvicorn, not the test client):
  the UI's own origins get a working shell; `http://evil.example` gets
  HTTP 403.
- Full suite on the security patch alone: macOS 6,935 passed / 5 skipped;
  Linux (WSL2 Ubuntu 24.04) 6,933 passed / 7 skipped; Windows 6,890
  passed / 50 skipped (platform gates); 0 failed anywhere.
- Full suite on `feature/v1.19.4`: macOS 7,338 passed / 7 skipped
  (2026-10-11); Windows 7,197 passed / 80 skipped at `0eb4863a`
  (2026-10-04, before the latest model and docs fixes).
- SSH hub: launch, attach, detach and stop against real sshd hosts from
  Windows (TCP local end) and Linux (unix-socket local end), and the
  owner's trial on real hosts and keys; see
  `docs/plan-ssh-remote-backend.md`.
- Linux, live: the fixed server gives the UI's origins a shell and refuses
  `http://evil.example` with 403. The unfixed v1.19.3 binary on the same
  host gave `http://evil.example` a shell, which reproduces the hole.
- Windows, live: the same results with and without `PPXAI_API_TOKEN`. Origin
  `null` and a rebinding Host are refused too, a wrong bearer from the UI's
  own origin is refused, and a right bearer from a foreign origin is still
  refused. The desktop app's terminal view, in a real Chromium, still
  connects and shows its "requires a Unix host" message.

## Upgrade

1. **`/task` sandbox:** runs are now confined to their working folder. A
   task that must read elsewhere needs those paths in
   `execution.task.sandbox.read_paths.allow`. To keep the old unconfined
   behaviour, write `enforcement: "off"` (the credential deny list still
   applies; `read_paths.builtin_deny: false` removes it).
2. **If ppxai refuses to start** with "`tools.agent.sandbox` is no longer
   read": move that block under `execution.task.sandbox` (merge it if that
   key exists) and delete `tools.agent.sandbox`.
3. **Websocket clients:** if a browser client of yours opens the terminal
   from an origin other than the server's own, add that origin to
   `PPXAI_ALLOWED_ORIGINS`.
4. **Model rows copied from an older example config** can override the new
   facts. Run `/doctor`, and compare your `providers.*.models` rows for the
   models in the table above with `ppxai-config.example.json`; delete a
   row's `facts` block to fall back to the shipped seed.
5. **Gemini:** drop `gemini-3.5-flash` and any 2.5 model from your config,
   and drop a Gemini `generation_params` block that sets `temperature` or
   `top_p` (3.6+ ignores it; upcoming models reject it).
6. **SSH hub (optional):** add `remote.hosts`, open the hub URL that
   `ppxai-server` prints (or start `ppxai-desktop`), and install this release on
   each remote host.
