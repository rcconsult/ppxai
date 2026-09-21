/**
 * Live web-app E2E — the REAL ppxai web UI against a REAL running server.
 *
 * Distinct from every other spec in this directory: those load a static
 * `*-harness.html` over `file://` and exercise one widget's logic in
 * isolation. This one drives the actual app (`ppxai/web/index.html` +
 * `app.js`) served by `ppxai-server`, so it covers the wiring the harnesses
 * can't see — dispatch paths, the command envelope, SSE, and the AppState
 * mirror that badges render from.
 *
 * Opt-in: only runs under the `live` project, which starts the server via
 * `webServer` in playwright.config.ts. `npm test` (the default `chromium`
 * project) is unaffected and stays server-free.
 *
 *     cd tests/e2e && npm run test:live
 *     PPXAI_E2E_PROVIDER=qwen36-vllm npm run test:live     # pick a provider
 *
 * LLM-dependent assertions are skipped unless PPXAI_E2E_PROVIDER is set, so
 * the suite stays runnable on a box with no provider credentials.
 */
import { test, expect, Page } from '@playwright/test';

const PROVIDER = process.env.PPXAI_E2E_PROVIDER || '';
const LLM = PROVIDER ? test : test.skip;

/** Dismiss the "restore interrupted session?" confirm the app may raise. */
async function dismissRestorePrompt(page: Page) {
    page.on('dialog', (d) => d.dismiss().catch(() => {}));
}

/** Wait until app.js has constructed the global and finished booting. */
async function waitForApp(page: Page) {
    await page.waitForFunction(() => {
        const a = (window as any).ppxai;
        return !!(a && a.state && a.commandDispatcher && a.apiClient);
    }, { timeout: 30_000 });
}

/**
 * Instrument the live app so a test can assert on the MECHANISM, not just
 * the rendered outcome — which path delivered a state change, and whether a
 * bypassed endpoint was touched.
 */
async function installProbes(page: Page) {
    await page.evaluate(() => {
        const app = (window as any).ppxai;
        const spy = {
            ctxSyncs: [] as number[],
            clearSessionCalls: 0,
            stateSyncKeys: [] as string[],
        };
        (window as any).__spy = spy;

        const origSync = app.handleStateSync.bind(app);
        app.handleStateSync = (changes: Record<string, unknown>) => {
            for (const k of Object.keys(changes || {})) spy.stateSyncKeys.push(k);
            if (changes && 'context_percentage' in changes) {
                spy.ctxSyncs.push(Number(changes.context_percentage));
            }
            return origSync(changes);
        };

        // Trip-wire: the bespoke POST /sessions/clear must NOT be used by the
        // Clear button any more (docs/patterns/command-envelope.md).
        const origClear = app.apiClient.clearSession.bind(app.apiClient);
        app.apiClient.clearSession = (...a: unknown[]) => {
            spy.clearSessionCalls++;
            return origClear(...a);
        };
    });
}

const spy = (page: Page) => page.evaluate(() => (window as any).__spy);

/**
 * Point the UI at a provider and wait for the switch to land.
 *
 * Uses selectOption (a real user gesture) rather than assigning `.value` and
 * hand-firing `change`: the app's change handler reads the SELECT, and if it
 * runs while the option list is mid-repopulation (the clear path re-anchors
 * it) the value is empty and the client POSTs /providers with a blank name —
 * a 400 "Failed to set provider:" that only surfaces in the browser console.
 */
async function selectProvider(page: Page, provider: string) {
    const sel = page.locator('#providerSelect');
    await expect(sel.locator(`option[value="${provider}"]`)).toHaveCount(1);
    await sel.selectOption(provider);
    await expect
        .poll(async () =>
            page.evaluate(() => (window as any).ppxai.state.currentProvider),
        { timeout: 15_000 })
        .toBe(provider);
}

/**
 * Send a chat message and wait for the assistant's answer to land.
 *
 * Deliberately does NOT compare against a pre-send bubble count: a preceding
 * Clear wipes the transcript asynchronously, so a count snapshot taken before
 * the send can be HIGHER than the post-clear DOM and the "is there a new
 * bubble?" test never becomes true (cost a 120s timeout to find).
 *
 * Instead: wait for the last assistant bubble to hold real content. The bubble
 * is created immediately with a "Thinking..." placeholder, so requiring
 * non-placeholder text is what distinguishes "answered" from "started".
 */
async function chat(page: Page, message: string) {
    const input = page.locator('#messageInput');
    await input.fill(message);
    // Confirm the text actually landed before submitting: a preceding Clear
    // re-renders and refocuses the composer, which can swallow a fill() that
    // raced it — the send then does nothing and the wait below burns its full
    // budget against an empty transcript.
    await expect(input).toHaveValue(message);
    await page.locator('#sendBtn').click();
    await expect
        .poll(async () => {
            const bubbles = page.locator('.assistant-message');
            if (await bubbles.count() === 0) return '';
            const body = (await bubbles.last().locator('.message-content')
                .textContent()) || '';
            return /thinking\.\.\./i.test(body.trim()) ? '' : body.trim();
        }, { timeout: 120_000 })
        .toMatch(/\S/);
}

const ctxBadge = (page: Page) => page.locator('#contextUsage');

/**
 * Tokens currently shown in the Ctx badge, or null before the first
 * `/context` fetch populates it.
 *
 * The badge starts as the static `0%` in index.html and becomes
 * `NN% (used/limit)` once `updateContextInfo()` runs, so assertions key on
 * this parsed number rather than on the rendered string shape.
 */
async function ctxTokens(page: Page): Promise<number | null> {
    const text = (await ctxBadge(page).textContent()) || '';
    const m = text.match(/\((\d+(?:\.\d+)?)([KM]?)\//);
    if (!m) return null;
    const mult = m[2] === 'M' ? 1e6 : m[2] === 'K' ? 1e3 : 1;
    return Number(m[1]) * mult;
}

test.beforeEach(async ({ page }) => {
    // Surface client-side failures in the Playwright output. Without this a
    // broken client request shows up only as a mystery timeout — the 400
    // "Failed to set provider:" behind one such timeout took a while to find
    // precisely because it was invisible from the test's side.
    page.on('pageerror', (e) => console.log(`[browser:pageerror] ${e.message}`));
    page.on('response', async (r) => {
        if (r.status() >= 400) {
            let body = '';
            try { body = (await r.text()).slice(0, 200); } catch { /* streamed */ }
            console.log(`[browser:http] ${r.status()} ${r.request().method()} `
                + `${new URL(r.url()).pathname} :: ${body}`);
        }
    });
    await dismissRestorePrompt(page);
    await page.goto('/');
    await waitForApp(page);
    await installProbes(page);
    if (PROVIDER) await selectProvider(page, PROVIDER);
});

test.describe('live web app — boot', () => {
    test('serves the real app shell, not a harness', async ({ page }) => {
        await expect(page).toHaveTitle(/ppxai/i);
        await expect(page.locator('#messageInput')).toBeVisible();
        await expect(page.locator('#clearBtn')).toBeVisible();
    });

    test('header badges render from AppState', async ({ page }) => {
        await expect(ctxBadge(page)).toContainText('%');
        // The provider SELECT is populated from the server on boot (GET
        // /providers). An empty option list means the client never reached
        // the server. `state.currentProvider` is deliberately NOT asserted:
        // it only fills in once a provider is chosen, so it is legitimately
        // empty on a fresh load with no PPXAI_E2E_PROVIDER.
        await expect
            .poll(() => page.locator('#providerSelect option').count(), { timeout: 15_000 })
            .toBeGreaterThan(0);
    });
});

test.describe('live web app — command envelope', () => {
    test('a typed slash command round-trips through POST /command/*', async ({ page }) => {
        const response = page.waitForResponse(
            (r) => r.url().includes('/command/') && r.request().method() === 'POST'
        );
        await page.locator('#messageInput').fill('/help');
        await page.locator('#messageInput').press('Escape'); // close autocomplete
        await page.locator('#messageInput').press('Enter');

        const body = await (await response).json();
        expect(body).toHaveProperty('ok');
        expect(body).toHaveProperty('result');
        expect(body).toHaveProperty('side_effects');
        expect(body).toHaveProperty('events'); // the piggyback channel
        expect(body.version).toBe(1);
    });

    test('Clear BUTTON dispatches /clear instead of the bespoke endpoint', async ({ page }) => {
        // Regression fence for the bypass fixed in v1.19.1: the button used to
        // call POST /sessions/clear, which discards the envelope's events[] —
        // so every pushed AppState field needed a manual refresh and a missed
        // one was a silently stale badge (debt Item 48).
        const commandCall = page.waitForResponse(
            (r) => r.url().includes('/command/clear') && r.request().method() === 'POST'
        );
        await page.locator('#clearBtn').click();
        expect((await commandCall).status()).toBe(200);

        expect(
            (await spy(page)).clearSessionCalls,
            'Clear button must not call the bespoke POST /sessions/clear'
        ).toBe(0);
    });

    test('the welcome screen returns after clearing', async ({ page }) => {
        await page.locator('#clearBtn').click();
        await expect(page.locator('.welcome-message')).toBeVisible();
    });
});

test.describe('live web app — chat + Ctx badge (needs a provider)', () => {
    /**
     * Serial: these share ONE server, so they share ONE engine session. Run in
     * parallel and each sees the other's messages (and context tokens) — the
     * reset assertions would fail against a legitimately non-empty session.
     * Scoped to this block so an unrelated failure elsewhere doesn't cascade.
     */
    test.describe.configure({ mode: 'serial' });

    // A real model round-trip (plus a clear + a second turn) does not fit in
    // Playwright's 30s default. Must exceed the inner poll budget in chat(),
    // or the test dies before the reply lands.
    test.setTimeout(180_000);

    LLM('a chat turn streams a reply and moves the Ctx badge', async ({ page }) => {
        await page.locator('#clearBtn').click();
        await expect(page.locator('.welcome-message')).toBeVisible();
        await expect.poll(() => ctxTokens(page), { timeout: 15_000 }).toBe(0);
        await selectProvider(page, PROVIDER);

        await chat(page, 'Reply with the single word: pong');

        await expect(
            page.locator('.assistant-message').last().locator('.message-content')
        ).toContainText(/pong/i);
        // Context is derived from session messages — non-zero after a turn.
        await expect.poll(() => ctxTokens(page), { timeout: 15_000 }).toBeGreaterThan(0);
    });

    LLM('clearing resets the Ctx badge via the envelope push, not a poll', async ({ page }) => {
        // Settle the clear before chatting — the transcript reset is async and
        // the envelope's state_sync can re-anchor the provider selector, so
        // re-assert the provider afterwards.
        await page.locator('#clearBtn').click();
        await expect(page.locator('.welcome-message')).toBeVisible();
        await selectProvider(page, PROVIDER);
        await chat(page, 'Reply with the single word: pong');
        await expect.poll(() => ctxTokens(page), { timeout: 15_000 }).toBeGreaterThan(0);

        // Reset probes so we observe only what the CLEAR produces.
        await page.evaluate(() => {
            const s = (window as any).__spy;
            s.ctxSyncs = []; s.clearSessionCalls = 0; s.stateSyncKeys = [];
        });

        await page.locator('#clearBtn').click();

        // The badge resets...
        await expect.poll(() => ctxTokens(page), { timeout: 15_000 }).toBe(0);
        // ...because a discrete context_percentage state_sync arrived on the
        // envelope's events[] — the mechanism, not just the outcome.
        await expect
            .poll(async () => (await spy(page)).ctxSyncs, { timeout: 10_000 })
            .toContain(0);
        expect((await spy(page)).clearSessionCalls).toBe(0);
    });
});

/**
 * PRE-EXISTING paths that carry a typed slash-command line off the client,
 * independent of dispatch. Recorded here so the fail-closed test below
 * asserts an exact set instead of "nothing" (which was never true):
 *   - POST /client-log — `app.showSystemMessage` mirrors the `> <input>`
 *     chat echo to the server debug log. This is why `/token set` with no
 *     value uses window.prompt, and why the inline form answers with a
 *     "consider rotating this token" warning.
 *   - POST /complete   — autocomplete sends the composer buffer as you type.
 * Neither is command dispatch, and neither is what ADR 0007 step 3a changed;
 * the day either is redacted, this list shrinks and the test says so.
 */
const EXPECTED_ECHO_PATHS = ['/client-log', '/complete'];

test.describe('live web app — command roster (ADR 0007 step 3a)', () => {
    /**
     * Type a slash command into the composer and submit it.
     *
     * The dropdown matters: typing fires POST /complete, and Enter while
     * the dropdown is OPEN selects a completion instead of submitting. So
     * settle the completion round-trip, Escape, and only submit once the
     * dropdown is actually hidden — a bare fill+Escape+Enter wins the race
     * most of the time and then hangs for the full timeout when it loses.
     */
    async function typeCommand(page: Page, text: string) {
        const input = page.locator('#messageInput');
        await input.fill(text);
        await expect(input).toHaveValue(text);
        await page.waitForTimeout(400);
        await input.press('Escape');
        await expect(page.locator('#autocompleteDropdown')).toBeHidden();
        await input.press('Enter');
    }

    /** Text of every system AND error message currently in the transcript. */
    async function systemText(page: Page): Promise<string> {
        const nodes = page.locator('.system-message, .error-message');
        const n = await nodes.count();
        const parts: string[] = [];
        for (let i = 0; i < n; i++) parts.push((await nodes.nth(i).textContent()) || '');
        return parts.join('\n');
    }

    /** Wait for the boot-time GET /commands to land (init() is async). */
    async function rosterReady(page: Page) {
        await expect
            .poll(() => page.evaluate(() => !!(window as any).ppxai.commandRoster?.isLoaded()),
                { timeout: 15_000 })
            .toBe(true);
    }

    test('the roster is fetched at boot and drives routing', async ({ page }) => {
        await rosterReady(page);
        const roster = await page.evaluate(() => {
            const r = (window as any).ppxai.commandRoster;
            return {
                loaded: r.isLoaded(),
                version: r.version,
                count: r.all().length,
                clientDispatched: r.all()
                    .filter((c: any) => c.dispatch === 'client')
                    .map((c: any) => [c.name, c.client_action]),
                aliasResolves: r.resolve('/cat')?.name,
                quitVisible: !!r.resolve('/quit'),
            };
        });
        expect(roster.loaded).toBe(true);
        expect(roster.count).toBeGreaterThan(20);
        // Exactly the four actions web bundles implementations for.
        expect(new Map(roster.clientDispatched as [string, string][])).toEqual(new Map([
            ['auto', 'auto.loop'],
            ['run', 'run.controller'],
            ['task', 'task.controller'],
            ['token', 'token.manage'],
        ]));
        // Aliases are a FIELD, resolved client-side to the canonical entry.
        expect(roster.aliasResolves).toBe('show');
        // /quit is gated to {rich, textual} — web must not even see it.
        expect(roster.quitVisible).toBe(false);
    });

    test('/help renders once and lists /token exactly once', async ({ page }) => {
        // The pre-step-3a bug: the server catalog listed /token (it is
        // clients={web,vscode}) AND `_appendExperimentalHelp()` appended it
        // again from the JS catalog, mislabelled "web-only".
        await rosterReady(page);
        const posted = page.waitForResponse(
            (r) => r.url().includes('/command/help') && r.request().method() === 'POST'
        );
        await typeCommand(page, '/help');
        const response = await posted;
        expect(JSON.parse(response.request().postData() || '{}').client).toBe('web');
        await expect.poll(async () => (await systemText(page)).includes('/token'),
            { timeout: 10_000 }).toBe(true);

        const text = await systemText(page);
        expect(text).not.toContain('Experimental (web-only)');
        // One CATALOG ENTRY each. The entry form is "/name — description";
        // a bare "/task" also occurs inside descriptions ("`/task help` for
        // the full grammar"), so counting bare names would over-count.
        expect((text.match(/\/token —/g) || []).length).toBe(1);
        expect((text.match(/\/task —/g) || []).length).toBe(1);
        expect((text.match(/\/run —/g) || []).length).toBe(1);
    });

    test('/token status is handled client-side — no POST to /command/token', async ({ page }) => {
        await rosterReady(page);
        const seen: string[] = [];
        page.on('request', (r) => {
            if (r.method() === 'POST') seen.push(new URL(r.url()).pathname);
        });
        await typeCommand(page, '/token status');
        await expect.poll(async () => (await systemText(page)).includes('API token'),
            { timeout: 10_000 }).toBe(true);
        expect(seen.filter((p) => p.includes('/command/token'))).toEqual([]);
    });

    test('with no roster the dispatcher fails closed and leaks nothing', async ({ page }) => {
        await rosterReady(page);
        // Simulate the version-skew state: an installed ~/.ppxai/web newer
        // than the running server, whose GET /commands 404s.
        await page.evaluate(() => {
            const r = (window as any).ppxai.commandRoster;
            r._loaded = false;
            r._byName = new Map();
            r.apiClient.getCommandRoster = async () => { throw new Error('HTTP 404'); };
        });
        const bodies: string[] = [];
        page.on('request', (r) => {
            if (r.method() === 'POST') bodies.push(`${new URL(r.url()).pathname} ${r.postData() || ''}`);
        });
        await typeCommand(page, '/token set PLAYWRIGHT-SECRET-XYZ');
        await expect.poll(async () => (await systemText(page)).toLowerCase().includes('skew'),
            { timeout: 10_000 }).toBe(true);

        // The step-3a guarantee: nothing was dispatched.
        expect(bodies.filter((b) => b.includes('/command/'))).toEqual([]);
        // ...and the one place the typed line DOES leave the browser is the
        // PRE-EXISTING `> <input>` chat echo that app.showSystemMessage
        // mirrors to POST /client-log. That is why `/token set` with no
        // value uses window.prompt, and why the inline form answers with a
        // "consider rotating this token" warning. Pinned rather than
        // asserted-away so the day it is fixed (redact the echo), this test
        // says so instead of silently passing.
        const carrying = bodies.filter((b) => b.includes('PLAYWRIGHT-SECRET-XYZ'))
            .map((b) => b.split(' ')[0]);
        expect([...new Set(carrying)].sort()).toEqual(EXPECTED_ECHO_PATHS);
    });
});
