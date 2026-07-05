# Tauri as the ppxai desktop shell — analysis

**Date:** 2026-07-05
**Status:** Reference (session research; code-verified against `feature/v1.19.0` @ `6add04f6`, Tauri facts web-verified)
**Related:**
- [2026-07-05-http-server-attack-surface-and-transport-options.md](2026-07-05-http-server-attack-surface-and-transport-options.md) — the transport/security question this composes with
- [2026-06-18-pi-coding-agent-comparison.md](2026-06-18-pi-coding-agent-comparison.md)

## Scope correction (read first)

"Switch the ppxai runtime to Tauri" has two readings; only one is viable.

- **Replace the runtime/engine with Tauri — NOT viable.** Tauri is a *desktop
  shell* (Rust core + OS webview + bundler), not a server/agent runtime. ppxai's
  runtime is ~64k LoC Python engine + FastAPI server + the v1.19.0 agent platform
  + ~60k LoC tests, mid-flight. A Rust rewrite is a multi-year non-starter and
  Tauri isn't even the right Rust tool for it.
- **Replace the desktop *delivery shell* with Tauri — worth analyzing**, because
  `ppxai-desktop` today is far thinner than its name suggests.

Everything below is the second reading.

## What ppxai-desktop actually is today (code-verified)

Not a webview app — a ~300-line **browser launcher** ([`ppxai-desktop.py`](../../ppxai-desktop.py)):

1. Finds the `ppxai-server` PyInstaller binary across a config-driven + 7-location
   fallback search (`:83-132`).
2. Spawns it **fully detached** (`start_new_session=True`, output → DEVNULL) (`:207-229`).
3. Copies web assets to `~/.ppxai/web/` via a **name+size** comparison (`:135-184`).
4. Opens the **user's default browser** at `127.0.0.1:54320` and exits.

Documented stop mechanism: `pkill ppxai-server` (`:295`). The macOS `.app` is a
hand-rolled bundle shipping `ppxai-server` alongside the launcher in
`Contents/MacOS` (`:57-67`) — i.e. a manual version of what Tauri's bundler +
sidecar do natively.

## Verified current pain (all real, most already paid)

| Pain | Evidence |
|---|---|
| Orphaned server — close tab, server runs forever | `start_new_session=True`; "To stop: pkill" |
| Web-asset staleness — launcher restores bundled JS to `~/.ppxai/web/` each start; **cost a debugging round** in v1.19.0 | debt 37m lesson; `docs/lessons/web-assets-served-from-ppxai-home.md` |
| Size-equal edits slip the update check | name+size compare (`:147-163`) |
| No app identity — no dock/tray/notifications/single-instance | it's a browser tab |
| No auto-update — users re-download 4 binaries per release | release process |
| Binary-discovery fragility | the 7-path search |

## Tauri state (web-verified 2026-07-05)

Mature, low dependency risk: **v2.11.5** stable (2026-07-01), 109k stars, 1,636
releases, active CI. Rust core, `wry` webview — WebView2 (Win), WKWebView (macOS),
webkit2gtk-4.1 (Linux). Frontend-agnostic. Bundler: NSIS/MSI, DMG/.app, deb/rpm/
AppImage. Built-in updater, tray, notifications. **Sidecar** (`bundle.externalBin`)
ships non-Rust binaries with per-target-triple naming, spawned via the shell
plugin under a capability/permission model. **Caveat (documented):** Tauri does
**not** auto-kill sidecars on exit — teardown is the developer's job.

## Realistic architecture (incremental, not a rewrite)

```
ppxai.app (Tauri ~5–10 MB Rust shell)
  OS webview ──► http://127.0.0.1:<port>   (existing web UI, ~zero change)
  window · tray · updater · single-instance
  sidecar: ppxai-server-<target-triple>    (the EXISTING PyInstaller binary,
                                             spawned + killed by the shell)
```

- **Frontend ~unchanged:** vanilla JS/CSS, no build step; the webview navigates to
  the same localhost URL the browser did. SSE + command envelope work as-is.
- **Engine/server untouched:** Python stays; the sidecar is the same CI-built
  `ppxai-server`, renamed per triple.
- **Other clients untouched:** TUIs, VSCode, plain-browser users, ppxai-sre's
  `/v1/*` consumers all keep talking to the same server. Tauri replaces exactly one
  artifact: `ppxai-desktop`.

## Buys vs costs

**Buys** (each maps to a verified pain): process-lifecycle ownership (server dies
with the window — kills the orphan + `pkill` UX; ~20 lines of Rust since Tauri
won't auto-kill); eliminates the `~/.ppxai/web/` copy dance for desktop (assets in
the bundle); real signed installers + delta auto-updater; app identity (dock/tray/
notifications — tray "server running/Stop", notifications interesting for `/task`
completion); ~5–10 MB shell vs Electron's ~150 MB.

**Costs** (honest): Rust toolchain enters dev + CI (permanent new competency for a
Python+TS team); CI matrix grows (4 platforms × Tauri bundling atop the PyInstaller
matrix; signing/notarization moves into Tauri, replacing `create-macos-app.sh`);
sidecar target-triple naming + capability declarations + **you own crash-path
sidecar teardown** (PID-file/health reaper); Linux gains a webkit2gtk-4.1 runtime
dep (today's Linux binary is dep-free; AppImage mitigates); Windows WebView2 (fine
on Win10/11, NSIS bootstrap for older); adds a 5th artifact type replacing one —
net complexity unless the browser-launcher mode is retired (it shouldn't be —
headless/server users need it).

**Middle option — `pywebview`:** native window, no Rust, slots into PyInstaller —
but no installer/updater/tray/lifecycle, and pywebview+PyInstaller is its own quirk
farm. Solves the least valuable 20%. Skip.

## The security composition (why this matters beyond UX)

Tauri isn't only a packaging upgrade — it's the **web client's in-process transport
escape hatch**. Today the desktop web UI *requires* a localhost HTTP server with
permissive CORS (see the [attack-surface note](2026-07-05-http-server-attack-surface-and-transport-options.md)).
A Tauri shell with Rust↔JS IPC can serve the UI **without a network listener**,
which is the long-horizon (Option B) way to give the desktop the Pi "no server"
security posture *without a rewrite*. So Tauri and the transport-hardening question
are the same roadmap item viewed from two sides: Tauri is *how* the web client goes
in-process.

## Recommendation

**Yes as the desktop shell; no as a "runtime switch"; not now.**

1. Scope it as a **packaging/UX + web-transport** replacement of `ppxai-desktop`
   only. The Python engine/server stay the runtime; Tauri never touches `/v1`, the
   agent platform, or the other three clients.
2. Timing: v1.19.0 is mid-flight (agents API unsealed, `/task` T3–T9 pending).
   Orthogonal but competes for the build/CI/release attention that has historically
   been this project's risky part (v1.18.1's four retags). Land it as a
   **post-v1.19.0 spike**.
3. Cheap spike: Phase 1 (Tauri window → localhost URL, spawn/kill the server
   sidecar, one platform) is ~2–4 days and proves 80% of the risk (sidecar
   lifecycle, WebView2/WKWebView rendering the existing UI, SSE). Productionizing
   (4-platform CI, signing, updater, install-script migration, docs) is the real
   cost — ~2–4 weeks spread out.
4. Trigger: do it when desktop UX becomes a priority — `/task` completion
   notifications with the window closed, or auto-update pain for real users. Until
   then the browser launcher works.

## Sources
- [Tauri GitHub](https://github.com/tauri-apps/tauri)
- [Tauri v2 sidecar docs](https://v2.tauri.app/develop/sidecar/)
