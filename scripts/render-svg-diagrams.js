#!/usr/bin/env node
/*
 * Render docs SVG diagrams to PNG with the Playwright Chromium that
 * tests/e2e already installs, so every PNG in docs/diagrams/ can be
 * regenerated from its SVG source.
 *
 *   node scripts/render-svg-diagrams.js docs/diagrams/ssh-remote        # every *.svg in the dir
 *   node scripts/render-svg-diagrams.js path/to/one.svg [--scale 2]
 *
 * Needs `npm install` in tests/e2e (and `npx playwright install chromium`
 * once). The PNG is written next to the SVG, at the SVG's width/height
 * times --scale (default 2), on the SVG's own background.
 */
'use strict';

const fs = require('fs');
const path = require('path');

const repo = path.resolve(__dirname, '..');
let chromium;
try {
    ({ chromium } = require(path.join(repo, 'tests', 'e2e', 'node_modules', 'playwright')));
} catch (e) {
    console.error('Playwright not found: run `npm install` in tests/e2e first.');
    process.exit(2);
}

function parseArgs(argv) {
    const out = { scale: 2, targets: [] };
    for (let i = 0; i < argv.length; i++) {
        if (argv[i] === '--scale') out.scale = Number(argv[++i]);
        else out.targets.push(argv[i]);
    }
    if (!out.targets.length || !(out.scale > 0)) {
        console.error('usage: render-svg-diagrams.js <dir|file.svg>... [--scale N]');
        process.exit(2);
    }
    return out;
}

function svgFiles(target) {
    const abs = path.resolve(target);
    if (fs.statSync(abs).isDirectory()) {
        return fs.readdirSync(abs).filter(f => f.endsWith('.svg')).sort().map(f => path.join(abs, f));
    }
    return [abs];
}

function svgSize(svg) {
    const tag = svg.match(/<svg\b[^>]*>/);
    const w = tag && tag[0].match(/\bwidth="(\d+(?:\.\d+)?)"/);
    const h = tag && tag[0].match(/\bheight="(\d+(?:\.\d+)?)"/);
    if (!w || !h) throw new Error('the root <svg> needs numeric width and height attributes');
    return { width: Math.ceil(Number(w[1])), height: Math.ceil(Number(h[1])) };
}

(async () => {
    const { scale, targets } = parseArgs(process.argv.slice(2));
    const files = targets.flatMap(svgFiles);
    const browser = await chromium.launch();
    try {
        for (const file of files) {
            const svg = fs.readFileSync(file, 'utf8');
            const { width, height } = svgSize(svg);
            const page = await browser.newPage({ viewport: { width, height }, deviceScaleFactor: scale });
            await page.setContent(
                `<!doctype html><html><head><meta charset="utf-8"><style>html,body{margin:0;padding:0}svg{display:block}</style></head><body>${svg}</body></html>`,
                { waitUntil: 'load' });
            const png = file.replace(/\.svg$/, '.png');
            await page.locator('svg').first().screenshot({ path: png });
            await page.close();
            console.log(`${path.relative(repo, png)}  ${width * scale}x${height * scale}`);
        }
    } finally {
        await browser.close();
    }
})().catch(err => { console.error(err.message || err); process.exit(1); });
