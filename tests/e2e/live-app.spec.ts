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
