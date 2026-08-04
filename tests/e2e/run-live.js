#!/usr/bin/env node
/**
 * Launcher for the LIVE web-app E2E project.
 *
 * Exists so `PPXAI_E2E_LIVE=1` is set cross-platform without adding a
 * cross-env dependency (`VAR=x cmd` is not valid on Windows cmd.exe, and the
 * flag must be an env var — Playwright re-evaluates the config in each worker
 * without the CLI args, so argv sniffing breaks there).
 *
 *   npm run test:live
 *   npm run test:live:headed
 *   PPXAI_E2E_PROVIDER=qwen36-vllm npm run test:live   # enable the LLM steps
 *
 * Extra args are forwarded: `npm run test:live -- --debug`.
 */
const { spawnSync } = require('child_process');

const args = ['playwright', 'test', '--project=live', ...process.argv.slice(2)];
const res = spawnSync('npx', args, {
    stdio: 'inherit',
    shell: process.platform === 'win32', // npx is a .cmd shim on Windows
    env: { ...process.env, PPXAI_E2E_LIVE: '1' },
});
process.exit(res.status === null ? 1 : res.status);
