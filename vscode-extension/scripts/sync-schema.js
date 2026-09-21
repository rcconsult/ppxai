#!/usr/bin/env node
/**
 * Derive the VSCode extension's AppState artefacts from the canonical
 * Python-owned JSON schema. Two outputs, one source:
 *
 *   ppxai/engine/app_state_schema.json          <- the ONLY hand-edited file
 *     |
 *     +-> vscode-extension/resources/app-state-schema.json   (runtime DATA)
 *     +-> vscode-extension/src/appState.generated.ts         (build-time TYPES)
 *
 * **DATA** — the JSON copy is what `src/appState.ts::_loadSchema` reads at
 * runtime to build defaults and the Python<->TS name map. It is tracked in
 * git and pinned byte-identical to the canonical file by
 * `tests/test_app_state.py::test_vscode_bundled_copy_matches_canonical`.
 *
 * **TYPES** — `AppStateFields` used to be a hand-written interface in
 * `src/appState.ts`. It drifted: by 2026-09-21 the schema declared 22
 * fields and the interface 20 (`lastMessageRole` and `modelSupportsVision`
 * were never added), and the header comment promised a constructor
 * assertion that did not exist. It is now GENERATED here, so a field
 * added to the schema cannot be missing from the type.
 *
 * Runs automatically before `npm run compile` / `package` / `watch` via
 * the `precompile` / `prepackage` / `prewatch` hooks in package.json, and
 * on demand with `npm run sync-schema`.
 *
 * Both outputs are deterministic and byte-stable — no timestamps, stable
 * (schema) field order — so `tests/test_app_state_generated_types.py` can
 * regenerate in memory and fail on any difference.
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
const GENERATED_TS = path.join(
    __dirname,
    '..',
    'src',
    'appState.generated.ts'
);

/** Repo-relative path of the canonical schema, for the generated header. */
const CANONICAL_REL = 'ppxai/engine/app_state_schema.json';
/** Repo-relative path of this script, for the generated header. */
const GENERATOR_REL = 'vscode-extension/scripts/sync-schema.js';

/**
 * Schema `type` -> the TypeScript type used when no refinement applies.
 *
 * `array` and `object` are deliberately WIDE here: the canonical schema is
 * language-neutral (Python, JS and TS all read it) and must never carry a
 * TypeScript type name. Narrowing happens in TYPE_REFINEMENTS below.
 */
const BASE_TYPES = {
    string: 'string',
    boolean: 'boolean',
    integer: 'number',
    number: 'number',
    array: 'unknown[]',
    object: 'Record<string, unknown>',
};

/** The schema types a refinement is allowed to narrow. */
const CONTAINER_TYPES = ['array', 'object'];

/**
 * HAND-WRITTEN refinement map — the one place a TypeScript type name may
 * be attached to a canonical field, keyed by the field's `client`
 * (camelCase) name.
 *
 * Only `array` / `object` fields may be refined: the other JSON types are
 * already exact, and narrowing e.g. a `string` to a union would be a
 * client-side restatement of a rule the schema does not make. Refining a
 * field the schema does not declare, or one whose type is not a container,
 * is a hard error below — the drift this whole file exists to prevent.
 *
 * `imports` names the identifiers pulled from `./appStateTypes` (the
 * hand-written element interfaces). Keep them minimal; the generated
 * import list is derived from this map, deduped and sorted.
 */
const TYPE_REFINEMENTS = {
    contextAttachments: {
        type: 'ContextAttachment[]',
        imports: ['ContextAttachment'],
    },
    agentBeat: {
        type: 'AgentBeatSnapshot | Record<string, never>',
        imports: ['AgentBeatSnapshot'],
    },
    backgroundAgents: {
        type: 'BackgroundAgentSummary[]',
        imports: ['BackgroundAgentSummary'],
    },
};

/** Module the refinement element types are imported from. */
const REFINEMENT_MODULE = './appStateTypes';


/**
 * Build the `appState.generated.ts` source text from a parsed schema.
 *
 * Exported so the fence can regenerate in memory (`node -e`) and compare
 * against the tracked file without shelling through the file writes.
 *
 * Throws with an actionable message when a refinement is dishonest.
 */
function renderGeneratedTypes(schema) {
    const fields = (schema && schema.fields) || {};
    const byClient = {};
    for (const [pyName, spec] of Object.entries(fields)) {
        byClient[spec.client] = { pyName, spec };
    }

    // --- refinement honesty, checked before a line is emitted ---------
    const containerClients = Object.entries(fields)
        .filter(([, spec]) => CONTAINER_TYPES.indexOf(spec.type) !== -1)
        .map(([, spec]) => spec.client)
        .sort();

    for (const clientName of Object.keys(TYPE_REFINEMENTS)) {
        const entry = byClient[clientName];
        if (!entry) {
            throw new Error(
                `[sync-schema] TYPE_REFINEMENTS refines '${clientName}', which is ` +
                `not a field in ${CANONICAL_REL}. Either the field was renamed or ` +
                `removed in Python (drop the refinement), or the name is a typo. ` +
                `Refinable fields: ${containerClients.join(', ')}`
            );
        }
        if (CONTAINER_TYPES.indexOf(entry.spec.type) === -1) {
            throw new Error(
                `[sync-schema] TYPE_REFINEMENTS refines '${clientName}', whose ` +
                `canonical type is '${entry.spec.type}'. Only ` +
                `${CONTAINER_TYPES.join('/')} fields may be refined — a ` +
                `'${entry.spec.type}' field already has an exact TypeScript type, ` +
                `and narrowing it here would restate a rule ${CANONICAL_REL} does ` +
                `not make.`
            );
        }
    }

    // --- imports -------------------------------------------------------
    const imported = new Set();
    for (const refinement of Object.values(TYPE_REFINEMENTS)) {
        for (const name of (refinement.imports || [])) { imported.add(name); }
    }
    const importNames = [...imported].sort();

    // --- body ----------------------------------------------------------
    const lines = [];
    lines.push('/**');
    lines.push(' * AppStateFields — GENERATED FILE. DO NOT EDIT.');
    lines.push(' *');
    lines.push(` * Source:     ${CANONICAL_REL} (schema version ${schema.version})`);
    lines.push(` * Generator:  ${GENERATOR_REL}`);
    lines.push(' * Regenerate: `npm run sync-schema` from vscode-extension/');
    lines.push(' *             (also runs on precompile / prepackage / prewatch)');
    lines.push(' *');
    lines.push(' * Field names, order and base types come straight from the canonical');
    lines.push(' * schema. The canonical schema is LANGUAGE-NEUTRAL and never names a');
    lines.push(' * TypeScript type, so the few container fields that deserve a richer');
    lines.push(' * shape are narrowed by the hand-written TYPE_REFINEMENTS map in the');
    lines.push(` * generator, pointing at the element interfaces in ${REFINEMENT_MODULE}.`);
    lines.push(' *');
    lines.push(' * Output is deterministic and carries no timestamp:');
    lines.push(' * tests/test_app_state_generated_types.py regenerates it in memory and');
    lines.push(' * fails on any difference, in either direction.');
    lines.push(' */');
    lines.push('');
    if (importNames.length > 0) {
        lines.push(
            `import { ${importNames.join(', ')} } from '${REFINEMENT_MODULE}';`
        );
        lines.push('');
    }
    lines.push('/**');
    lines.push(' * Canonical state fields shared across all ppxai clients, in camelCase.');
    lines.push(' *');
    lines.push(' * One entry per field in the canonical schema — no more, no less.');
    lines.push(' */');
    lines.push('export interface AppStateFields {');

    const entries = Object.entries(fields);
    entries.forEach(([pyName, spec], index) => {
        const baseType = BASE_TYPES[spec.type];
        if (!baseType) {
            throw new Error(
                `[sync-schema] field '${pyName}' declares unknown type ` +
                `'${spec.type}'. Known types: ${Object.keys(BASE_TYPES).join(', ')}. ` +
                `Add it to BASE_TYPES in ${GENERATOR_REL} (and to the Python-side ` +
                `type table in tests/test_app_state.py) before using it.`
            );
        }
        const refinement = TYPE_REFINEMENTS[spec.client];
        const tsType = refinement ? refinement.type : baseType;
        if (index > 0) { lines.push(''); }
        // A doc containing `*/` would close the JSDoc block early; the
        // canonical file has none today, but a future one must not be
        // able to emit a file that does not parse.
        const doc = String(spec.doc || 'no doc').replace(/\*\//g, '*\\/');
        lines.push(`    /** \`${pyName}\` (${spec.group}) — ${doc} */`);
        lines.push(`    ${spec.client}: ${tsType};`);
    });

    lines.push('}');
    lines.push('');
    return lines.join('\n');
}


function main() {
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
    let schema;
    try {
        canonicalJson = fs.readFileSync(CANONICAL, 'utf-8');
        schema = JSON.parse(canonicalJson);
    } catch (err) {
        console.error(
            `[sync-schema] ERROR: canonical schema at ${CANONICAL} is not valid JSON: ${err.message}`
        );
        process.exit(1);
    }

    // --- 1. the runtime DATA copy --------------------------------------
    fs.mkdirSync(path.dirname(BUNDLED), { recursive: true });
    const existing = fs.existsSync(BUNDLED)
        ? fs.readFileSync(BUNDLED, 'utf-8') : null;
    if (existing === canonicalJson) {
        console.log(`[sync-schema] already in sync: ${BUNDLED}`);
    } else {
        fs.writeFileSync(BUNDLED, canonicalJson, 'utf-8');
        console.log(`[sync-schema] copied ${CANONICAL} → ${BUNDLED}`);
    }

    // --- 2. the build-time TYPES ---------------------------------------
    let generated;
    try {
        generated = renderGeneratedTypes(schema);
    } catch (err) {
        console.error(`ERROR: ${err.message}`);
        process.exit(1);
    }
    const existingTs = fs.existsSync(GENERATED_TS)
        ? fs.readFileSync(GENERATED_TS, 'utf-8') : null;
    if (existingTs === generated) {
        console.log(`[sync-schema] already in sync: ${GENERATED_TS}`);
    } else {
        fs.writeFileSync(GENERATED_TS, generated, 'utf-8');
        console.log(`[sync-schema] generated ${GENERATED_TS}`);
    }
}

module.exports = {
    renderGeneratedTypes,
    TYPE_REFINEMENTS,
    BASE_TYPES,
    CONTAINER_TYPES,
    CANONICAL,
    GENERATED_TS,
    BUNDLED,
};

if (require.main === module) {
    main();
}
