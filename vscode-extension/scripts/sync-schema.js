#!/usr/bin/env node
/**
 * Copy the canonical AppState JSON schema from the Python package
 * into the VSCode extension resources directory so TypeScript can
 * import it at build time (via `resolveJsonModule`).
 *
 * The schema is maintained in exactly one place:
 *   ppxai/engine/app_state_schema.json
 *
 * This script copies it to:
 *   vscode-extension/resources/app-state-schema.json
 *
 * Runs automatically before every `npm run compile` via the
 * `precompile` script hook in package.json. CI will fail if someone
 * edits the extension's copy manually — test_app_state.py has a
 * byte-for-byte equality check between the canonical file and the
 * bundled copy.
 *
 * Also bundles a copy into the compiled `out/` directory so the
 * extension can find it at runtime (TS JSON imports get compiled
 * into `require('./resources/...')` calls from `out/src/appState.js`,
 * which resolves relative to `out/src/` — we stage the file next to
 * appState.js).
 */

const fs = require('fs');
const path = require('path');

const REPO_ROOT = path.resolve(__dirname, '..', '..');
const CANONICAL = path.join(
    REPO_ROOT,
    'ppxai',
    'engine',
    'app_state_schema.json'
);
const BUNDLED = path.join(
    __dirname,
    '..',
    'resources',
    'app-state-schema.json'
);

if (!fs.existsSync(CANONICAL)) {
    console.error(
        `[sync-schema] ERROR: canonical schema not found at ${CANONICAL}\n` +
        `This script must run from the ppxai repo root. If you are building ` +
        `the VSCode extension in isolation, copy ppxai/engine/app_state_schema.json ` +
        `into vscode-extension/resources/ manually.`
    );
    process.exit(1);
}

// Validate JSON (fail loud on a malformed canonical file)
let canonicalJson;
try {
    canonicalJson = fs.readFileSync(CANONICAL, 'utf-8');
    JSON.parse(canonicalJson);
} catch (err) {
    console.error(
        `[sync-schema] ERROR: canonical schema at ${CANONICAL} is not valid JSON: ${err.message}`
    );
    process.exit(1);
}

// Ensure target directory exists
fs.mkdirSync(path.dirname(BUNDLED), { recursive: true });

// Only write if changed — avoids touching mtime on no-op runs
const existing = fs.existsSync(BUNDLED) ? fs.readFileSync(BUNDLED, 'utf-8') : null;
if (existing === canonicalJson) {
    console.log(`[sync-schema] already in sync: ${BUNDLED}`);
    process.exit(0);
}

fs.writeFileSync(BUNDLED, canonicalJson, 'utf-8');
console.log(`[sync-schema] copied ${CANONICAL} → ${BUNDLED}`);
