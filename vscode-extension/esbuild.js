// esbuild build script for the ppxai VSCode extension (Item 5, v1.18.2).
//
// Bundles `src/extension.ts` and all transitive imports into a single
// `dist/extension.js`. The `vscode` module is the only external —
// it's provided by the editor host at runtime, never bundled.
//
// Cross-platform: pure Node.js, no shell-isms, no platform-specific
// paths. Works on Linux, macOS, and Windows. The `npm install` step
// fetches the right native esbuild binary per host.
//
// Usage:
//   node esbuild.js              -> dev build (sourcemaps, no minify)
//   node esbuild.js --production -> release build (minified, no sourcemap)
//   node esbuild.js --watch      -> rebuild on change (dev shape)
//
// Webview-side libraries (`marked`, `highlight.js`) are loaded as
// static assets from `media/webview/` by the chat-panel HTML; they
// are NOT imported by extension code and stay out of this bundle.

const esbuild = require("esbuild");

const production = process.argv.includes("--production");
const watch = process.argv.includes("--watch");

/** @type {import('esbuild').BuildOptions} */
const buildOptions = {
    entryPoints: ["src/extension.ts"],
    bundle: true,
    format: "cjs",
    platform: "node",
    target: "node20",
    // VSCode provides this module at runtime — never bundle it.
    external: ["vscode"],
    outfile: "dist/extension.js",
    minify: production,
    sourcemap: production ? false : "linked",
    // Keep names readable in stack traces even under minify.
    keepNames: true,
    // VSCode's host loads the bundle via Node's `require`; set this
    // so esbuild emits clean CommonJS without ESM interop shims.
    mainFields: ["module", "main"],
    logLevel: "info",
};

async function main() {
    if (watch) {
        const ctx = await esbuild.context(buildOptions);
        await ctx.watch();
        console.log("[esbuild] watching for changes...");
        return;
    }
    const result = await esbuild.build(buildOptions);
    if (result.errors.length > 0) {
        process.exit(1);
    }
    console.log(
        `[esbuild] built dist/extension.js ` +
        `(${production ? "production, minified" : "development, sourcemaps"})`
    );
}

main().catch((err) => {
    console.error(err);
    process.exit(1);
});
