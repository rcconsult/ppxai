/**
 * Build a custom highlight.min.js bundle with languages needed by ppxai.
 *
 * Usage: node build-hljs.cjs
 * Output: media/highlight.min.js (also copied to ../ppxai/web/lib/)
 *
 * Uses esbuild to bundle highlight.js core + selected languages into
 * a single self-contained IIFE that exposes window.hljs.
 */

const { writeFileSync } = require('fs');
const { execSync } = require('child_process');
const { join } = require('path');

// All languages to include (common + extras for ppxai users)
const LANGUAGES = [
  // --- Common (same as CDN "common" bundle) ---
  'bash', 'c', 'cpp', 'csharp', 'css', 'diff', 'go', 'graphql', 'ini',
  'java', 'javascript', 'json', 'kotlin', 'less', 'lua', 'makefile',
  'markdown', 'objectivec', 'perl', 'php', 'php-template', 'plaintext',
  'python', 'python-repl', 'r', 'ruby', 'rust', 'scss', 'shell', 'sql',
  'swift', 'typescript', 'vbnet', 'wasm', 'xml', 'yaml',
  // --- Extras for ppxai ---
  'powershell',    // Windows users, 15 occurrences in docs
  'dockerfile',    // DevOps / container users
  'dos',           // Windows batch files (```batch → dos alias)
  'applescript',   // macOS users
];

// Generate the entry point source
const imports = LANGUAGES.map((l, i) => {
  const safe = l.replace(/-/g, '_');
  return `import ${safe} from 'highlight.js/lib/languages/${l}';`;
}).join('\n');

const registers = LANGUAGES.map(l => {
  const safe = l.replace(/-/g, '_');
  return `hljs.registerLanguage('${l}', ${safe});`;
}).join('\n');

const entrySource = `
import hljs from 'highlight.js/lib/core';
${imports}
${registers}

export default hljs;
`;

// Write temp entry file
const entryPath = join(__dirname, '_hljs-entry.js');
writeFileSync(entryPath, entrySource, 'utf-8');

console.log(`Building highlight.js bundle with ${LANGUAGES.length} languages...`);

// Bundle with esbuild
const outPath = join(__dirname, 'media', 'highlight.min.js');
try {
  execSync(
    `npx esbuild "${entryPath}" --bundle --minify --format=iife --global-name=hljs --outfile="${outPath}" --platform=browser --target=es2020`,
    { cwd: __dirname, stdio: 'inherit' }
  );
} finally {
  // Clean up temp file
  require('fs').unlinkSync(entryPath);
}

// Post-process:
// 1. Strip leading "use strict"; so var hljs leaks to global in browsers
// 2. esbuild wraps default export as {default: hljs} — unwrap .default
// 3. Append UMD footer for Node.js compatibility (same as original CDN bundle)
let bundle = require('fs').readFileSync(outPath, 'utf-8');
bundle = bundle.replace(/^"use strict";/, '');
// esbuild IIFE: var hljs=(()=>{ ... return Pt(ui); })();
// Pt(ui) returns {default: <actual hljs>}. Unwrap by appending .default
bundle = bundle.replace(/return (\w+\(\w+\));\}\)\(\);/, 'return $1.default;})();');
bundle += '\n;"object"==typeof exports&&"undefined"!=typeof module&&(module.exports=hljs);';
require('fs').writeFileSync(outPath, bundle, 'utf-8');

// Verify by loading in Node — the UMD footer sets module.exports=hljs
const hljs = require(outPath);
const registered = hljs.listLanguages().sort();
console.log(`\nVerification: ${registered.length} languages registered`);
console.log(`Languages: ${registered.join(', ')}`);

const missing = LANGUAGES.filter(l => !registered.includes(l));
if (missing.length > 0) {
  console.error(`\nWARNING: Missing languages: ${missing.join(', ')}`);
  process.exit(1);
} else {
  console.log('\nAll languages registered successfully!');
}

const { statSync } = require('fs');
const size = statSync(outPath).size;
console.log(`Bundle size: ${(size / 1024).toFixed(1)} KB`);
