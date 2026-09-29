#!/usr/bin/env node
/**
 * Launcher for the SSH-Launcher E2E project (ADR 0013).
 *
 * Same reasoning as run-live.js: the gate must be an env var, not an argv
 * flag, because Playwright re-evaluates playwright.config.ts in each worker
 * process without the CLI args ("Project 'ssh' not found" otherwise).
 *
 *   npm run test:ssh
 *   npm run test:ssh:headed
 *
 * Extra args are forwarded: `npm run test:ssh -- --debug`.
 *
 * The spec starts and stops its own hub + remote servers (no `webServer`
 * entry in the config), and is unix-socket-only, so it skips itself on
 * win32.
 */
const { spawnSync } = require('child_process');

const args = ['playwright', 'test', '--project=ssh', ...process.argv.slice(2)];
const res = spawnSync('npx', args, {
    stdio: 'inherit',
    shell: process.platform === 'win32', // npx is a .cmd shim on Windows
    env: { ...process.env, PPXAI_E2E_SSH: '1' },
});
process.exit(res.status === null ? 1 : res.status);
