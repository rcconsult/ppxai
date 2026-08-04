import { defineConfig, devices } from '@playwright/test';
import * as path from 'path';

/**
 * Two kinds of E2E here, deliberately separated:
 *
 * - `chromium` (default) — widget specs over `file://` harnesses. No server,
 *   no provider, fast. This is what `npm test` runs.
 * - `live` (opt-in) — `live-app.spec.ts` drives the REAL web app against a
 *   REAL `ppxai-server`, so it covers dispatch/envelope/SSE wiring the
 *   harnesses can't reach. Started via `webServer` below.
 *
 *     npm run test:live
 *     PPXAI_E2E_PROVIDER=qwen36-vllm npm run test:live   # enable LLM steps
 *
 * Gated on PPXAI_E2E_LIVE=1 (the npm scripts set it), so a plain
 * `npx playwright test` never tries to start a server. It must be an ENV var,
 * not argv sniffing: Playwright re-evaluates this config in each worker
 * process without the CLI args, so an argv-derived project list would exist
 * in the runner and vanish in the worker ("Project 'live' not found").
 */
const REPO_ROOT = path.resolve(__dirname, '..', '..');
const LIVE = process.env.PPXAI_E2E_LIVE === '1';
const PORT = Number(process.env.PPXAI_E2E_PORT || 8807);

// Prefer the working-tree server (.venv) so a live run tests THIS checkout,
// not whatever binary happens to be installed — the stale-server trap in
// docs/lessons/stale-server-invalidates-acceptance.md.
const SERVER = process.platform === 'win32'
  ? path.join(REPO_ROOT, '.venv', 'Scripts', 'ppxai-server.exe')
  : path.join(REPO_ROOT, '.venv', 'bin', 'ppxai-server');

export default defineConfig({
  testDir: '.',
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: process.env.CI ? 1 : undefined,
  reporter: 'html',
  use: {
    baseURL: 'file://' + process.cwd(),
    trace: 'on-first-retry',
  },
  projects: [
    {
      name: 'chromium',
      testIgnore: 'live-app.spec.ts',
      use: { ...devices['Desktop Chrome'] },
    },
    ...(LIVE
      ? [{
          name: 'live',
          testMatch: 'live-app.spec.ts',
          use: {
            ...devices['Desktop Chrome'],
            baseURL: `http://127.0.0.1:${PORT}`,
          },
        }]
      : []),
  ],
  // Serve the REPO's web assets, not ~/.ppxai/web (which may be an older
  // installed copy) — otherwise a live run silently tests stale client code.
  webServer: LIVE
    ? {
        command: `"${SERVER}" --port ${PORT}`,
        url: `http://127.0.0.1:${PORT}/status`,
        reuseExistingServer: false,
        timeout: 60_000,
        env: { PPXAI_WEB_DIR: path.join(REPO_ROOT, 'ppxai', 'web') },
      }
    : undefined,
});
