#!/usr/bin/env node
/*
 * Capture the README screenshots from the real app, with Playwright.
 *
 *   node scripts/capture-readme-screenshots.js             # every group
 *   node scripts/capture-readme-screenshots.js web ssh     # just these
 *
 * Groups: `web` (chat with tools, file preview, terminal, /usage, a /task
 * run), `ssh` (the SSH Launcher; its remote is tests/fake_ssh.py, so no
 * real host), `vscode` (the extension in `code serve-web`; needs `code`).
 *
 * Nothing personal can reach a picture: the server runs with a throwaway
 * HOME (config = the repo's shipped ppxai-config.json, the task tier on),
 * inside a generated demo project with its own git history and a neutral
 * shell prompt. The only thing taken from the real HOME is GEMINI_API_KEY,
 * copied into the throwaway ~/.ppxai/.env (0600) and deleted with it.
 * Chat replies are real Gemini replies, so they differ between runs.
 *
 * Needs `npm install` in tests/e2e and the repo venv (`uv sync --all-extras`).
 * Writes PNGs to docs/screenshots/ at 1440x900, device scale 2. A run
 * costs a few cents of Gemini usage; `web` takes about three minutes.
 */
'use strict';

const fs = require('fs');
const os = require('os');
const path = require('path');
const net = require('net');
const { spawn, execFileSync } = require('child_process');

const repo = path.resolve(__dirname, '..');
let chromium;
try {
    ({ chromium } = require(path.join(repo, 'tests', 'e2e', 'node_modules', 'playwright')));
} catch (e) {
    console.error('Playwright not found: run `npm install` in tests/e2e first.');
    process.exit(2);
}

const OUT = path.join(repo, 'docs', 'screenshots');
const VIEWPORT = { width: 1440, height: 900 };
const SERVER_BIN = path.join(repo, '.venv', 'bin', 'ppxai-server');

// ---------------------------------------------------------------- setup ---

function freePort() {
    return new Promise((resolve, reject) => {
        const s = net.createServer();
        s.listen(0, '127.0.0.1', () => { const p = s.address().port; s.close(() => resolve(p)); });
        s.on('error', reject);
    });
}

function realGeminiKey() {
    const envFile = path.join(os.homedir(), '.ppxai', '.env');
    const line = fs.existsSync(envFile) && fs.readFileSync(envFile, 'utf8')
        .split(/\r?\n/).find((l) => /^GEMINI_API_KEY=/.test(l));
    if (!line && !process.env.GEMINI_API_KEY) {
        console.error('No GEMINI_API_KEY in ~/.ppxai/.env or the environment.');
        process.exit(2);
    }
    return line || `GEMINI_API_KEY=${process.env.GEMINI_API_KEY}`;
}

const DEMO_FILES = {
    'README.md': `# weather-cli

A tiny command-line weather forecast.

    python app.py Oslo --days 3

## TODO

- [ ] cache forecasts for 10 minutes
- [ ] add a \`--units imperial\` flag
- [ ] colour the output when stdout is a terminal
`,
    'app.py': `"""weather-cli: print a short forecast for a city."""
import argparse
import json
from pathlib import Path

DATA = Path(__file__).with_name("sample_forecast.json")


def load_forecast(city: str, days: int) -> list[dict]:
    """Return up to \`days\` daily entries for \`city\` (sample data, no network)."""
    forecast = json.loads(DATA.read_text(encoding="utf-8"))
    return forecast.get(city.lower(), [])[:days]


def render(city: str, entries: list[dict]) -> str:
    lines = [f"Forecast for {city.title()}"]
    for e in entries:
        lines.append(f"  {e['day']:<10} {e['summary']:<14} {e['min']:>3}° / {e['max']:>3}°C")
    return "\\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("city")
    parser.add_argument("--days", type=int, default=3)
    args = parser.parse_args()
    print(render(args.city, load_forecast(args.city, args.days)))


if __name__ == "__main__":
    main()
`,
    'test_app.py': `from app import load_forecast, render


def test_render_has_one_line_per_day():
    entries = load_forecast("oslo", 2)
    assert len(render("oslo", entries).splitlines()) == 3
`,
    'sample_forecast.json': JSON.stringify({
        oslo: [
            { day: 'Monday', summary: 'Light rain', min: 6, max: 11 },
            { day: 'Tuesday', summary: 'Cloudy', min: 5, max: 12 },
            { day: 'Wednesday', summary: 'Sunny', min: 4, max: 14 },
        ],
    }, null, 2) + '\n',
    'dashboard.html': `<!doctype html>
<html><head><meta charset="utf-8"><title>Forecast dashboard</title>
<style>
 body{font-family:system-ui,sans-serif;margin:24px;background:#f5f7fb;color:#1f2937}
 h1{font-size:20px} .cards{display:flex;gap:12px}
 .card{background:#fff;border-radius:10px;padding:14px 18px;box-shadow:0 1px 3px #0002;min-width:120px}
 .t{font-size:28px;font-weight:600} .d{color:#6b7280}
</style></head><body>
<h1>Oslo — next 3 days</h1>
<div class="cards">
 <div class="card"><div class="d">Monday</div><div class="t">11°</div>Light rain</div>
 <div class="card"><div class="d">Tuesday</div><div class="t">12°</div>Cloudy</div>
 <div class="card"><div class="d">Wednesday</div><div class="t">14°</div>Sunny</div>
</div></body></html>
`,
};

function makeWorld() {
    // A fixed, short root: its paths appear in pictures (the SSH Launcher
    // lists each server's workdir).
    const root = path.join('/tmp', 'ppxai-demo');
    fs.rmSync(root, { recursive: true, force: true });
    fs.mkdirSync(root);
    const home = path.join(root, 'home');
    const ppxaiHome = path.join(home, '.ppxai');
    fs.mkdirSync(ppxaiHome, { recursive: true });

    const config = JSON.parse(fs.readFileSync(path.join(repo, 'ppxai-config.json'), 'utf8'));
    config.execution = config.execution || {};
    config.execution.task = { ...(config.execution.task || {}), enabled: true };
    fs.writeFileSync(path.join(ppxaiHome, 'ppxai-config.json'), JSON.stringify(config, null, 2));
    fs.writeFileSync(path.join(ppxaiHome, '.env'), realGeminiKey() + '\n', { mode: 0o600 });

    // A neutral prompt for the terminal pane: no user name, no host name.
    fs.writeFileSync(path.join(home, '.zshrc'), "PROMPT='%1~ %# '\n");
    fs.writeFileSync(path.join(home, '.bashrc'), "PS1='\\W $ '\n");
    fs.writeFileSync(path.join(home, '.bash_profile'), '. ~/.bashrc\n');

    const project = path.join(home, 'projects', 'weather-cli');
    fs.mkdirSync(project, { recursive: true });
    const git = (...a) => execFileSync('git', a, {
        cwd: project, stdio: 'ignore',
        env: { ...process.env, HOME: home, GIT_CONFIG_GLOBAL: '/dev/null' },
    });
    git('init', '-q');
    git('symbolic-ref', 'HEAD', 'refs/heads/main'); // `init -b` needs git >= 2.28
    git('config', 'user.name', 'Demo');
    git('config', 'user.email', 'demo@example.com');
    const commit = (files, msg) => {
        for (const f of files) fs.writeFileSync(path.join(project, f), DEMO_FILES[f]);
        git('add', ...files);
        git('commit', '-q', '-m', msg);
    };
    commit(['README.md'], 'Start weather-cli');
    commit(['app.py', 'sample_forecast.json'], 'Print a forecast from sample data');
    commit(['test_app.py'], 'Test the renderer');
    commit(['dashboard.html'], 'Add a static forecast dashboard');
    return { root, home, project };
}

async function startServer(world, port, extraEnv = {}) {
    // A minimal environment, not a copy of ours: nothing from the real
    // session (terminal program, tokens, config overrides) reaches a page.
    const env = {
        PATH: process.env.PATH,
        LANG: 'en_US.UTF-8',
        TERM: 'xterm-256color',
        HOME: world.home,
        USER: 'demo',
        SHELL: '/bin/zsh',
        BASH_SILENCE_DEPRECATION_WARNING: '1',
        PPXAI_WEB_DIR: path.join(repo, 'ppxai', 'web'),
        ...extraEnv,
    };
    const log = fs.openSync(path.join(world.root, `server-${port}.log`), 'a');
    const proc = spawn(SERVER_BIN, ['--port', String(port)], {
        cwd: world.project, env, stdio: ['ignore', log, log],
    });
    const deadline = Date.now() + 60_000;
    while (Date.now() < deadline) {
        try {
            const r = await fetch(`http://127.0.0.1:${port}/status`);
            if (r.ok) return proc;
        } catch (_) { /* not up yet */ }
        if (proc.exitCode !== null) throw new Error(`server exited; see ${world.root}/server-${port}.log`);
        await new Promise((r) => setTimeout(r, 300));
    }
    proc.kill();
    throw new Error('server did not answer /status within 60s');
}

// ---------------------------------------------------------- page helpers ---

async function openApp(browser, port) {
    const context = await browser.newContext({ viewport: VIEWPORT, deviceScaleFactor: 2 });
    const page = await context.newPage();
    page.on('dialog', (d) => d.dismiss().catch(() => {}));
    await page.goto(`http://127.0.0.1:${port}/`);
    await page.waitForFunction(() => {
        const a = window.ppxai;
        return !!(a && a.state && a.commandDispatcher && a.apiClient);
    }, null, { timeout: 30_000 });
    await page.waitForTimeout(800);
    return page;
}

async function send(page, text) {
    const input = page.locator('#messageInput');
    await input.fill(text);
    await input.press('Escape'); // close the autocomplete
    await page.locator('#sendBtn').click();
}

/** Wait until nothing is streaming and the assistant has said something. */
async function waitForReply(page, timeout = 180_000) {
    await page.waitForTimeout(1500);
    await page.waitForFunction(() => {
        const busy = document.querySelector('#streamingBadge:not(.hidden)');
        const replies = document.querySelectorAll('.assistant-message');
        return !busy && replies.length > 0;
    }, null, { timeout });
    await page.waitForTimeout(1000);
}

async function shot(page, name) {
    fs.mkdirSync(OUT, { recursive: true });
    const file = path.join(OUT, `${name}.png`);
    await page.screenshot({ path: file });
    console.log(`  ${path.relative(repo, file)}`);
}

module.exports = { makeWorld, startServer, openApp, send, waitForReply, shot, freePort, repo, OUT };

// ------------------------------------------------------------------ shots ---

async function inProject(page, world) {
    await send(page, `/cd ${world.project}`);
    await page.waitForFunction(() => /weather-cli/.test(
        document.querySelector('#folderPath')?.textContent || ''), null, { timeout: 15_000 });
    await page.locator('#clearBtn').click();
    await page.waitForTimeout(800);
}

async function toolsOn(page) {
    const status = page.locator('#toolsStatus');
    if (!/on/i.test(await status.textContent())) await page.locator('#toolsBadge').click();
    await page.waitForFunction(() => /on/i.test(
        document.querySelector('#toolsStatus')?.textContent || ''), null, { timeout: 15_000 });
}

/** Drop the setup chatter (cd, tools on, clear) so a shot shows the work. */
async function dropSystemMessages(page) {
    await page.evaluate(() => document.querySelectorAll('#messagesContainer .system-message')
        .forEach((e) => e.remove()));
}

async function scrollChatToBottom(page) {
    await page.evaluate(() => {
        const c = document.querySelector('#messagesContainer');
        c.scrollTop = c.scrollHeight;
    });
    await page.waitForTimeout(300);
}

// The web-app shots run as ONE session, in order, so each shows real work.
/** Accept VS Code's trust prompts for the demo folder: restricted mode
 *  disables the extension. It may ask twice (the folder, then the git
 *  repository), and the second prompt can come a few seconds later. */
async function trustDemoFolder(page) {
    for (let i = 0; i < 4; i++) {
        const cont = page.getByRole('button', { name: 'Trust Folder & Continue' });
        if (await cont.isVisible().catch(() => false)) {
            await cont.click();
            await page.waitForTimeout(1500);
            continue;
        }
        const manage = page.locator('.monaco-workbench a:has-text("Manage")').first();
        if (await manage.isVisible().catch(() => false)) {
            await manage.click();
            await page.getByRole('button', { name: /^Trust$/ }).first().click();
            await page.waitForTimeout(1500);
            await page.keyboard.press('Escape');
            await page.waitForTimeout(800);
            continue;
        }
        await page.waitForTimeout(1000);
    }
}

/** Find the (nested) iframe that holds the ppxai chat webview. */
async function chatFrame(page, timeout = 60_000) {
    const deadline = Date.now() + timeout;
    while (Date.now() < deadline) {
        for (const f of page.frames()) {
            try { if (await f.$('#messageInput')) return f; } catch (_) { /* detached */ }
        }
        await page.waitForTimeout(500);
    }
    throw new Error('ppxai chat webview not found');
}

async function vscodeSend(frame, text) {
    await frame.fill('#messageInput', text);
    await frame.press('#messageInput', 'Escape');
    await frame.click('#sendBtn');
}

async function vscodeWaitForReply(frame, page, timeout = 180_000) {
    await page.waitForTimeout(1500);
    await frame.waitForFunction(() => {
        const busy = document.querySelector('.streaming');
        return !busy && document.querySelectorAll('.message.assistant').length > 0;
    }, null, { timeout });
    await page.waitForTimeout(1500);
}

const SHOTS = {
    async web({ browser, port, world }) {
        const page = await openApp(browser, port);
        await inProject(page, world);
        await toolsOn(page);
        await dropSystemMessages(page);

        // 1. A chat that uses tools: the model reads the project, then answers.
        await send(page, 'What does this project do? Read the code and the README, then list the open TODOs with a one-line suggestion for each.');
        await waitForReply(page);
        await page.locator('.tool-turn').last().click(); // expand the tool strip
        await page.waitForTimeout(500);
        await page.evaluate(() => document.querySelector('#messagesContainer').scrollTop = 0);
        await shot(page, 'web-chat-tools');
        await page.locator('.tool-turn').last().click(); // collapse again

        // 2. The file tree and a preview in the right-hand pane.
        await page.locator('#sidebarToggleBtn').click();
        await send(page, '/preview dashboard.html');
        await page.waitForTimeout(3000);
        await dropSystemMessages(page);
        await scrollChatToBottom(page);
        await shot(page, 'web-files-preview');

        // 3. The terminal pane, running the project.
        await send(page, '/terminal');
        await page.waitForSelector('.xterm', { timeout: 15_000 });
        await page.waitForTimeout(1500);
        await dropSystemMessages(page);
        await page.locator('.xterm').last().click();
        await page.keyboard.type('python3 app.py oslo --days 3 && git log --oneline\n', { delay: 15 });
        await page.waitForTimeout(2500);
        await shot(page, 'web-terminal');
        await page.locator('#rpfClose').click();
        await page.locator('#sidebarToggleBtn').click();

        // 4. Usage and cost for the session.
        await send(page, '/usage');
        await page.waitForTimeout(2500);
        await scrollChatToBottom(page);
        await shot(page, 'web-usage');

        // 5. A background task, in the task view.
        await send(page, '/token mint');   // the web client's /v1 bearer, kept in the browser
        await page.waitForTimeout(2500);
        await dropSystemMessages(page);
        await send(page, '/task "Add a --units flag (metric or imperial) to app.py, convert the temperatures, and add a test for it" --tools list_directory,read_file,replace_block,write_file');
        await page.waitForTimeout(45_000);
        await shot(page, 'web-task-running');
        // Then the finished run: wait for its status to leave "running".
        await page.waitForFunction(() => !/running/i.test(
            document.querySelector('#rpfViewport')?.innerText.slice(0, 300) || ''),
            null, { timeout: 300_000 });
        await page.waitForTimeout(2000);
        await shot(page, 'web-task');
        await page.context().close();
    },

    // The VS Code extension, in VS Code for the Web (`code serve-web`) with
    // an isolated data dir, the extension built from this checkout, and the
    // shared ppxai server. Chromium only: Firefox leaves webviews blank.
    async vscode({ browser, port, world }) {
        const vsix = path.join(world.root, 'ppxai.vsix');
        const ext = path.join(repo, 'vscode-extension');
        execFileSync('npm', ['run', 'compile'], { cwd: ext, stdio: 'ignore' });
        execFileSync('npx', ['vsce', 'package', '--allow-missing-repository', '-o', vsix],
            { cwd: ext, stdio: 'ignore' });
        const dataDir = path.join(world.root, 'vscode');
        const settings = JSON.stringify({
            'ppxai.serverUrl': `http://127.0.0.1:${port}`,
            'workbench.startupEditor': 'none',
            'workbench.tips.enabled': false,
            'security.workspace.trust.enabled': false,
            'workbench.colorTheme': 'Default Dark Modern',
            'telemetry.telemetryLevel': 'off',
            'extensions.autoCheckUpdates': false,
            'update.mode': 'none',
            'extensions.ignoreRecommendations': true,
            'chat.disableAIFeatures': true,
            'workbench.secondarySideBar.defaultVisibility': 'hidden',
            'window.commandCenter': false,
        }, null, 2);
        for (const scope of ['Machine', 'User']) {
            fs.mkdirSync(path.join(dataDir, 'data', scope), { recursive: true });
            fs.writeFileSync(path.join(dataDir, 'data', scope, 'settings.json'), settings);
        }
        execFileSync('code', ['--install-extension', vsix, '--force',
            '--extensions-dir', path.join(dataDir, 'extensions')], { stdio: 'ignore' });

        const vsPort = await freePort();
        const log = fs.openSync(path.join(world.root, 'serve-web.log'), 'a');
        const vs = spawn('code', ['serve-web', '--host', '127.0.0.1', '--port', String(vsPort),
            '--without-connection-token', '--accept-server-license-terms',
            '--server-data-dir', dataDir], { stdio: ['ignore', log, log] });
        try {
            const deadline = Date.now() + 180_000;
            for (;;) {
                try { if ((await fetch(`http://127.0.0.1:${vsPort}/`)).ok) break; } catch (_) { /* starting */ }
                if (Date.now() > deadline) throw new Error('code serve-web did not start');
                await new Promise((r) => setTimeout(r, 1000));
            }
            const context = await browser.newContext({ viewport: VIEWPORT, deviceScaleFactor: 2 });
            const page = await context.newPage();
            await page.goto(`http://127.0.0.1:${vsPort}/?folder=${encodeURIComponent(world.project)}`);
            await page.waitForSelector('.monaco-workbench', { timeout: 120_000 });
            await page.waitForTimeout(5000);
            await trustDemoFolder(page);
            // Open app.py in the editor, then the ppxai chat view.
            await page.keyboard.press('Meta+p');
            await page.waitForTimeout(800);
            await page.keyboard.type('app.py');
            await page.waitForTimeout(800);
            await page.keyboard.press('Enter');
            await page.waitForTimeout(1500);
            await trustDemoFolder(page);
            // Close the Welcome tab (middle click), if it opened.
            const welcome = page.locator('.tabs-container .tab').filter({ hasText: 'Welcome' }).first();
            if (await welcome.isVisible().catch(() => false)) await welcome.click({ button: 'middle' });
            await page.locator('.activitybar [aria-label^="PPXAI"]').first().click();
            const frame = await chatFrame(page);
            // Widen the side bar so the chat reads comfortably.
            const bar = await page.locator('.part.sidebar').boundingBox();
            if (bar) {
                const edge = bar.x + bar.width;
                for (const sash of await page.$$('.monaco-sash.vertical')) {
                    const box = await sash.boundingBox();
                    if (!box || Math.abs(box.x + box.width / 2 - edge) > 8) continue;
                    const x = box.x + box.width / 2, y = bar.y + bar.height / 2;
                    await page.mouse.move(x, y);
                    await page.waitForTimeout(400);
                    await page.mouse.down();
                    await page.mouse.move(640, y, { steps: 15 });
                    await page.mouse.up();
                    await page.waitForTimeout(800);
                    break;
                }
            }
            await page.waitForTimeout(3000);
            await vscodeSend(frame, '/tools on');
            await page.waitForTimeout(2500);
            await vscodeSend(frame, 'Explain how render() in app.py lays out each line, and suggest one improvement.');
            await vscodeWaitForReply(frame, page);
            await shot(page, 'vscode-chat');
            await context.close();
        } finally {
            vs.kill('SIGTERM');
        }
    },

    // The SSH Launcher. Its own hub server, whose one remote host "lab" is
    // reached through tests/fake_ssh.py (runs the remote side locally), so
    // no real host or key is involved.
    async ssh({ browser, world }) {
        const shimDir = path.join(world.root, 'ssh-shim');
        fs.mkdirSync(shimDir, { recursive: true });
        const python = path.join(repo, '.venv', 'bin', 'python');
        fs.writeFileSync(path.join(shimDir, 'ssh'),
            `#!/bin/sh\nexec "${python}" "${path.join(repo, 'tests', 'fake_ssh.py')}" "$@"\n`, { mode: 0o755 });
        const remoteBin = path.join(shimDir, 'remote-ppxai-server');
        fs.writeFileSync(remoteBin, `#!/bin/sh\nexec "${python}" -m ppxai.server.http "$@"\n`, { mode: 0o755 });

        const cfgPath = path.join(world.home, '.ppxai', 'ppxai-config.json');
        const original = fs.readFileSync(cfgPath, 'utf8');
        const cfg = JSON.parse(original);
        cfg.remote = { hosts: [{ id: 'lab', ssh: 'lab', ppxai_server: remoteBin }] };
        fs.writeFileSync(cfgPath, JSON.stringify(cfg, null, 2));

        const port = await freePort();
        const hub = await startServer(world, port, { PATH: `${shimDir}:${process.env.PATH}` });
        const launched = [];
        try {
            const docs = path.join(world.home, 'projects', 'docs-site');
            fs.mkdirSync(docs, { recursive: true });
            for (const [label, workdir] of [['docs-site', docs], ['weather-cli', world.project]]) {
                const r = await fetch(`http://127.0.0.1:${port}/hub/hosts/lab/servers`, {
                    method: 'POST', headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ workdir, label }),
                });
                if (r.status !== 201) throw new Error(`launch ${label}: ${r.status} ${await r.text()}`);
                launched.push(await r.json());
            }
            // Attach one, so the launcher shows a live connection and counts.
            await fetch(`http://127.0.0.1:${port}/hub/hosts/lab/servers/${launched[1].id}/attach`, {
                method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}',
            });
            const page = await openApp(browser, port);
            await inProject(page, world);
            await dropSystemMessages(page);
            await page.locator('#sshBtn').click();
            await page.waitForTimeout(4000);
            await shot(page, 'web-ssh-launcher');
            await page.context().close();
        } finally {
            for (const server of launched) {
                await fetch(`http://127.0.0.1:${port}/hub/hosts/lab/servers/${server.id}/stop`, {
                    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}',
                }).catch(() => {});
                // Never leave a detached stand-in remote running.
                try { process.kill(server.pid, 'SIGTERM'); } catch (_) { /* already gone */ }
            }
            hub.kill('SIGTERM');
            fs.writeFileSync(cfgPath, original);
        }
    },
};

if (require.main === module) {
    (async () => {
        const only = process.argv.slice(2);
        const unknown = only.filter((n) => !(n in SHOTS));
        if (unknown.length) {
            console.error(`unknown group(s): ${unknown.join(', ')}; known: ${Object.keys(SHOTS).join(', ')}`);
            process.exit(2);
        }
        const world = makeWorld();
        const port = await freePort();
        let server;
        const browser = await chromium.launch();
        try {
            server = await startServer(world, port);
            for (const [name, run] of Object.entries(SHOTS)) {
                if (only.length && !only.includes(name)) continue;
                console.log(name);
                await run({ browser, port, world });
            }
        } finally {
            await browser.close();
            if (server) server.kill('SIGTERM');
            fs.rmSync(world.root, { recursive: true, force: true });
        }
    })().catch((e) => { console.error(e); process.exit(1); });
}
