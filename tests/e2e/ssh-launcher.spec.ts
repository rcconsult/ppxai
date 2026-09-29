/**
 * SSH Launcher E2E (ADR 0013) — the REAL web UI against a REAL hub server
 * and a REAL remote `ppxai-server`, reached exactly the way ADR 0013's
 * `RemoteSessionManager` reaches any host: through the `ssh` binary on PATH.
 *
 * No real host or key is involved: `tests/fake_ssh.py` stands in for `ssh`
 * and runs the "remote" side's commands locally (`sh -c ...`), so the whole
 * flow — discover the binary, launch `ppxai-server --uds --announce
 * --detach`, list `--json`, forward over the resulting unix socket, proxy
 * through `/h/<host>/<id>/`, `POST /shutdown` on Stop — runs for real, one
 * machine standing in for two. Same approach as
 * `scripts/capture-readme-screenshots.js`'s `ssh` group; not imported from
 * there, since that script also drives an LLM chat this spec doesn't need.
 *
 * Opt-in, via `npm run test:ssh` (`tests/e2e/run-ssh.js` sets
 * PPXAI_E2E_SSH=1 — an env var, not an argv flag, because Playwright
 * re-evaluates playwright.config.ts in each worker without the CLI args).
 * The default `chromium` project ignores this file.
 *
 * The spec starts and stops its own servers (a hub, a plain non-hub server,
 * and whatever remote servers the UI launches through the hub) — there is no
 * `webServer` entry for it in playwright.config.ts. Everything is cleaned up
 * in `afterAll`, best-effort, even if a test failed partway.
 *
 * Unix-socket only (ADR 0013): skipped on win32.
 */
import { test, expect, Page, Browser } from '@playwright/test';
import * as fs from 'fs';
import * as path from 'path';
import * as net from 'net';
import { spawn, ChildProcess } from 'child_process';

const REPO_ROOT = path.resolve(__dirname, '..', '..');
const PYTHON = path.join(REPO_ROOT, '.venv', 'bin', 'python');
const SERVER_BIN = path.join(REPO_ROOT, '.venv', 'bin', 'ppxai-server');
const FAKE_SSH = path.join(REPO_ROOT, 'tests', 'fake_ssh.py');

test.describe('SSH Launcher (ADR 0013)', () => {
    // The remote side is a unix-socket forward; nothing here has a Windows
    // shape (ssh shim is a shell script, sockets are AF_UNIX).
    test.skip(process.platform === 'win32', 'remote hub is unix-socket only');
    test.describe.configure({ mode: 'serial' });

    // ---------------------------------------------------------------- world
    let root: string;
    let hubHome: string;
    let hubPort: number;
    let hubProc: ChildProcess;
    let plainHome: string;
    let plainPort: number;
    let plainProc: ChildProcess;
    /** Every server launched through the hub during the run: cleaned up in
     * afterAll even if the test that launched it failed before tidying up. */
    const launched: { id: string; pid: number }[] = [];
    let launcherPage: Page;
    let primaryServerId: string;
    let primaryPopup: Page;

    function freePort(): Promise<number> {
        return new Promise((resolve, reject) => {
            const s = net.createServer();
            s.listen(0, '127.0.0.1', () => {
                const addr = s.address();
                const port = typeof addr === 'object' && addr ? addr.port : 0;
                s.close(() => resolve(port));
            });
            s.on('error', reject);
        });
    }

    function baseConfig(): any {
        return JSON.parse(fs.readFileSync(path.join(REPO_ROOT, 'ppxai-config.json'), 'utf8'));
    }

    function writeHome(dir: string, config: any) {
        const ppxaiHome = path.join(dir, '.ppxai');
        fs.mkdirSync(ppxaiHome, { recursive: true });
        fs.writeFileSync(path.join(ppxaiHome, 'ppxai-config.json'), JSON.stringify(config, null, 2));
    }

    async function waitForStatus(port: number, timeoutMs = 60_000) {
        const deadline = Date.now() + timeoutMs;
        for (;;) {
            try {
                const r = await fetch(`http://127.0.0.1:${port}/status`);
                if (r.ok) return;
            } catch (_) { /* not up yet */ }
            if (Date.now() > deadline) throw new Error(`server on ${port} did not answer /status`);
            await new Promise((r) => setTimeout(r, 200));
        }
    }

    function spawnServer(homeDir: string, port: number, logName: string, extraEnv: Record<string, string> = {}): ChildProcess {
        const env: Record<string, string> = {
            PATH: process.env.PATH || '',
            LANG: 'en_US.UTF-8',
            HOME: homeDir,
            PPXAI_WEB_DIR: path.join(REPO_ROOT, 'ppxai', 'web'),
            ...extraEnv,
        };
        const log = fs.openSync(path.join(root, logName), 'a');
        return spawn(SERVER_BIN, ['--port', String(port)], {
            cwd: homeDir, env, stdio: ['ignore', log, log],
        });
    }

    function isPidAlive(pid: number): boolean {
        try {
            process.kill(pid, 0);
            return true;
        } catch (err: any) {
            return err.code !== 'ESRCH';
        }
    }

    async function hubGet(port: number, urlPath: string): Promise<any> {
        const r = await fetch(`http://127.0.0.1:${port}${urlPath}`);
        if (!r.ok) throw new Error(`GET ${urlPath}: ${r.status}`);
        return r.json();
    }

    async function hubPost(port: number, urlPath: string, body: unknown = {}): Promise<Response> {
        return fetch(`http://127.0.0.1:${port}${urlPath}`, {
            method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
        });
    }

    async function serverByLabel(port: number, host: string, label: string): Promise<{ id: string; pid: number }> {
        const listing = await hubGet(port, `/hub/hosts/${host}/servers`);
        const found = (listing.servers || []).find((s: any) => s.label === label);
        if (!found) throw new Error(`no server labelled ${label} on ${host}: ${JSON.stringify(listing)}`);
        return { id: found.id, pid: found.pid };
    }

    /** Open the app at `port` and wait for it to finish booting. */
    async function openApp(browser: Browser, port: number): Promise<Page> {
        const page = await browser.newPage();
        page.on('dialog', (d) => d.accept().catch(() => {}));
        await page.goto(`http://127.0.0.1:${port}/`);
        await page.waitForFunction(() => {
            const a = (window as any).ppxai;
            return !!(a && a.state && a.commandDispatcher && a.apiClient);
        }, null, { timeout: 30_000 });
        return page;
    }

    async function openLauncher(page: Page) {
        await page.locator('#sshBtn').click();
        await expect(page.locator('.ssh-launcher')).toBeVisible({ timeout: 10_000 });
    }

    async function launchServer(page: Page, host: string, workdir: string, label: string) {
        await page.locator(`button[data-action="new"][data-host="${host}"]`).click();
        const form = page.locator(`form.ssh-new-form[data-host="${host}"]`);
        await expect(form).toBeVisible();
        await form.locator('input[name="workdir"]').fill(workdir);
        await form.locator('input[name="label"]').fill(label);
        await form.locator('button[type="submit"]').click();
        await expect(page.locator('.ssh-server').filter({ hasText: `“${label}”` }))
            .toBeVisible({ timeout: 30_000 });
    }

    test.beforeAll(async () => {
        // A short, fixed base rather than os.tmpdir(): on macOS that resolves
        // to /var/folders/.../T, and the announced server's socket path
        // (<root>/hub-home/.ppxai/run/sock/<id>.sock) then overflows
        // AF_UNIX's ~104-byte sun_path, failing launch with "AF_UNIX path
        // too long" — found running this spec. /tmp keeps it short. Same
        // fixed-root choice as scripts/capture-readme-screenshots.js.
        root = fs.mkdtempSync('/tmp/ppxai-ssh-e2e-');

        // -- the hub: remote.hosts names "lab", reached via the fake_ssh shim.
        hubHome = path.join(root, 'hub-home');
        fs.mkdirSync(hubHome, { recursive: true });
        const shimDir = path.join(root, 'shim');
        fs.mkdirSync(shimDir, { recursive: true });
        fs.writeFileSync(path.join(shimDir, 'ssh'),
            `#!/bin/sh\nexec "${PYTHON}" "${FAKE_SSH}" "$@"\n`, { mode: 0o755 });
        const remoteBin = path.join(shimDir, 'remote-ppxai-server');
        fs.writeFileSync(remoteBin, `#!/bin/sh\nexec "${PYTHON}" -m ppxai.server.http "$@"\n`, { mode: 0o755 });

        const hubConfig = baseConfig();
        hubConfig.remote = { hosts: [{ id: 'lab', ssh: 'lab', ppxai_server: remoteBin }] };
        writeHome(hubHome, hubConfig);

        hubPort = await freePort();
        hubProc = spawnServer(hubHome, hubPort, 'hub.log', { PATH: `${shimDir}:${process.env.PATH}` });
        await waitForStatus(hubPort);

        // -- a plain server, no remote.hosts: the negative case for the button.
        plainHome = path.join(root, 'plain-home');
        fs.mkdirSync(plainHome, { recursive: true });
        writeHome(plainHome, baseConfig());
        plainPort = await freePort();
        plainProc = spawnServer(plainHome, plainPort, 'plain.log');
        await waitForStatus(plainPort);
    });

    test.afterAll(async () => {
        // Best-effort: stop every server the tests launched through the hub,
        // then SIGTERM its pid — a detached remote otherwise keeps running
        // even after a failed test skipped its own cleanup.
        for (const s of launched) {
            await hubPost(hubPort, `/hub/hosts/lab/servers/${s.id}/stop`).catch(() => {});
            try { process.kill(s.pid, 'SIGTERM'); } catch (_) { /* already gone */ }
        }
        if (launcherPage) await launcherPage.context().close().catch(() => {});
        for (const proc of [hubProc, plainProc]) {
            if (proc && proc.exitCode === null) proc.kill('SIGTERM');
        }
        if (root) fs.rmSync(root, { recursive: true, force: true });
    });

    // -------------------------------------------------------------- tests

    test('the header SSH button appears only on a hub server', async ({ browser }) => {
        const hubPage = await openApp(browser, hubPort);
        await expect(hubPage.locator('#sshBtn')).toBeVisible({ timeout: 10_000 });
        await hubPage.close();

        const plainPage = await openApp(browser, plainPort);
        await expect(plainPage.locator('#sshBtn')).toBeHidden();
        await plainPage.close();
    });

    test('the launcher lists the configured host and launches a server', async ({ browser }) => {
        launcherPage = await openApp(browser, hubPort);
        await openLauncher(launcherPage);

        const hostSection = launcherPage.locator('section.ssh-host[data-host="lab"]');
        await expect(hostSection).toBeVisible({ timeout: 10_000 });
        await expect(hostSection.locator('.ssh-host-id')).toHaveText('lab');

        const workdir = path.join(root, 'work-one');
        fs.mkdirSync(workdir, { recursive: true });
        await launchServer(launcherPage, 'lab', workdir, 'e2e-primary');

        const { id, pid } = await serverByLabel(hubPort, 'lab', 'e2e-primary');
        launched.push({ id, pid });
        expect(isPidAlive(pid)).toBe(true);

        // Stash for the following (serial) tests.
        primaryServerId = id;
    });

    test('Open attaches and loads the remote UI under /h/lab/<id>/', async () => {
        const id = primaryServerId;
        const row = launcherPage.locator(`.ssh-server[data-server="${id}"]`);
        await expect(row).toBeVisible();

        const requests: string[] = [];
        const [popup] = await Promise.all([
            launcherPage.waitForEvent('popup'),
            row.locator('button[data-action="open"]').click(),
        ]);
        popup.on('dialog', (d) => d.accept().catch(() => {}));
        popup.on('request', (r) => requests.push(r.url()));

        const prefix = `/h/lab/${id}`;
        await expect(popup).toHaveURL(new RegExp(`${prefix}/?$`), { timeout: 20_000 });
        await popup.waitForFunction(() => {
            const a = (window as any).ppxai;
            return !!(a && a.state && a.commandDispatcher && a.apiClient);
        }, null, { timeout: 30_000 });
        await expect(popup.locator('#serverStatus')).toHaveText('Connected', { timeout: 20_000 });
        await expect(popup.locator('#hostBadge')).toContainText('lab');

        // Every API call the loaded app makes stays under the hub prefix.
        const apiCalls = requests.filter((u) => {
            const p = new URL(u).pathname;
            return p !== '/' && !/\.(js|css|png|svg|ico|woff2?|map)$/.test(p);
        });
        expect(apiCalls.length).toBeGreaterThan(0);
        for (const u of apiCalls) {
            expect(new URL(u).pathname.startsWith(prefix)).toBe(true);
        }

        // Confirmed attached, from the hub's own point of view.
        const hosts = await hubGet(hubPort, '/hub/hosts');
        const lab = hosts.hosts.find((h: any) => h.id === 'lab');
        const attachment = lab.attachments.find((a: any) => a.server_id === id);
        expect(attachment).toBeTruthy();
        expect(attachment.state).toBe('healthy');

        primaryPopup = popup;
    });

    test('Leave on the remote page detaches and returns to /#ssh', async () => {
        const id = primaryServerId;
        const popup = primaryPopup;

        await popup.locator('#quitBtn').click();
        await expect(popup).toHaveURL(/\/#ssh$/, { timeout: 20_000 });
        await expect(popup.locator('.ssh-launcher')).toBeVisible({ timeout: 10_000 });

        const hosts = await hubGet(hubPort, '/hub/hosts');
        const lab = hosts.hosts.find((h: any) => h.id === 'lab');
        const attachment = (lab.attachments || []).find((a: any) => a.server_id === id);
        expect(attachment).toBeFalsy();

        await popup.close();
    });

    test('Stop removes the server from the list and ends its process', async () => {
        const workdir = path.join(root, 'work-two');
        fs.mkdirSync(workdir, { recursive: true });
        await launchServer(launcherPage, 'lab', workdir, 'e2e-stop-me');
        const { id, pid } = await serverByLabel(hubPort, 'lab', 'e2e-stop-me');
        launched.push({ id, pid });
        expect(isPidAlive(pid)).toBe(true);

        launcherPage.once('dialog', (d) => d.accept().catch(() => {}));
        await launcherPage.locator(`.ssh-server[data-server="${id}"] button[data-action="stop"]`).click();

        await expect(launcherPage.locator(`.ssh-server[data-server="${id}"]`))
            .toHaveCount(0, { timeout: 20_000 });
        await expect.poll(() => isPidAlive(pid), { timeout: 10_000, intervals: [250] }).toBe(false);
    });

    test('a refused registry entry renders its message', async () => {
        const refusal = "lab: server 'x' speaks registry contract 1, which this ppxai no "
            + 'longer accepts: no longer supported. Install a ppxai-server of 1.19.4 or '
            + 'newer on the remote host.';
        await launcherPage.route('**/hub/hosts/lab/servers', async (route) => {
            if (route.request().method() !== 'GET') return route.continue();
            await route.fulfill({
                status: 200, contentType: 'application/json',
                body: JSON.stringify({ servers: [], refused: [refusal] }),
            });
        });
        await launcherPage.locator('.ssh-btn[data-action="refresh"]').click();
        await expect(launcherPage.getByText(/speaks registry contract 1/)).toBeVisible({ timeout: 10_000 });

        await launcherPage.unroute('**/hub/hosts/lab/servers');
    });
});
