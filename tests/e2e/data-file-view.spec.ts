import { test, expect } from '@playwright/test';
import * as path from 'path';

const harnessPath = path.resolve(__dirname, 'data-file-view-harness.html');

test.describe('DataFileView', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto(`file://${harnessPath}`);
    await page.waitForSelector('#status:has-text("Ready")');
  });

  test.describe('Parser Helpers — _dfvFormatFromExt', () => {
    test('csv, tsv, tab extensions map to table format', async ({ page }) => {
      const results = await page.evaluate(() => ({
        csv: window.testHelpers.formatFromExt('csv'),
        tsv: window.testHelpers.formatFromExt('tsv'),
        tab: window.testHelpers.formatFromExt('tab'),
      }));
      expect(results.csv).toBe('table');
      expect(results.tsv).toBe('table');
      expect(results.tab).toBe('table');
    });

    test('json, yaml, yml, toml, hcl, tf, tfvars extensions map to tree format', async ({ page }) => {
      const results = await page.evaluate(() => ({
        json:    window.testHelpers.formatFromExt('json'),
        yaml:    window.testHelpers.formatFromExt('yaml'),
        yml:     window.testHelpers.formatFromExt('yml'),
        toml:    window.testHelpers.formatFromExt('toml'),
        hcl:     window.testHelpers.formatFromExt('hcl'),
        tf:      window.testHelpers.formatFromExt('tf'),
        tfvars:  window.testHelpers.formatFromExt('tfvars'),
      }));
      expect(results.json).toBe('tree');
      expect(results.yaml).toBe('tree');
      expect(results.yml).toBe('tree');
      expect(results.toml).toBe('tree');
      expect(results.hcl).toBe('tree');
      expect(results.tf).toBe('tree');
      expect(results.tfvars).toBe('tree');
    });
  });

  test.describe('Parser Helpers — _dfvDetectDelimiter', () => {
    test('comma-separated content detects comma delimiter', async ({ page }) => {
      const delim = await page.evaluate(() =>
        window.testHelpers.detectDelimiter('Name,Age,City\nAlice,30,NYC\nBob,25,LA\n')
      );
      expect(delim).toBe(',');
    });

    test('tab-separated content detects tab delimiter', async ({ page }) => {
      const delim = await page.evaluate(() =>
        window.testHelpers.detectDelimiter('Name\tAge\tCity\nAlice\t30\tNYC\nBob\t25\tLA\n')
      );
      expect(delim).toBe('\t');
    });
  });

  test.describe('Parser Helpers — _dfvParseCSV', () => {
    test('simple CSV yields correct headers and data rows', async ({ page }) => {
      const result = await page.evaluate(() =>
        window.testHelpers.parseCSV('Name,Age\nAlice,30\nBob,25\n', ',')
      );
      expect(result.headers).toEqual(['Name', 'Age']);
      expect(result.rows.length).toBe(2);
      expect(result.rows[0]).toEqual(['Alice', '30']);
      expect(result.rows[1]).toEqual(['Bob', '25']);
    });

    test('short rows get padded with empty strings to match header count', async ({ page }) => {
      const result = await page.evaluate(() =>
        window.testHelpers.parseCSV('A,B,C\n1,2\n', ',')
      );
      expect(result.headers.length).toBe(3);
      expect(result.rows[0].length).toBe(3);
      expect(result.rows[0][2]).toBe('');
    });

    test('quoted fields with embedded commas parse as a single cell', async ({ page }) => {
      const result = await page.evaluate(() =>
        window.testHelpers.parseCSV('First,Last\nJohn,"Smith, Jr."\n', ',')
      );
      expect(result.rows[0][1]).toBe('Smith, Jr.');
    });
  });

  test.describe('Parser Helpers — _dfvParseCSVLine', () => {
    test('basic comma-delimited line splits into correct cells', async ({ page }) => {
      const cells = await page.evaluate(() =>
        window.testHelpers.parseCSVLine('a,b,c', ',')
      );
      expect(cells).toEqual(['a', 'b', 'c']);
    });

    test('quoted field with escaped double-quote unescapes correctly', async ({ page }) => {
      const cells = await page.evaluate(() =>
        window.testHelpers.parseCSVLine('a,"say ""hi""",b', ',')
      );
      expect(cells).toEqual(['a', 'say "hi"', 'b']);
    });
  });

  test.describe('Parser Helpers — _dfvBuildTree', () => {
    test('string value produces node with node_type string and correct value', async ({ page }) => {
      const node = await page.evaluate(() =>
        window.testHelpers.buildTree('key', 'hello', 0)
      );
      expect(node.node_type).toBe('string');
      expect(node.value).toBe('hello');
      expect(node.children.length).toBe(0);
    });

    test('number value produces node with node_type number', async ({ page }) => {
      const node = await page.evaluate(() =>
        window.testHelpers.buildTree('n', 42, 0)
      );
      expect(node.node_type).toBe('number');
      expect(node.value).toBe(42);
    });

    test('null value produces node with node_type null', async ({ page }) => {
      const node = await page.evaluate(() =>
        window.testHelpers.buildTree('x', null, 0)
      );
      expect(node.node_type).toBe('null');
    });

    test('object value produces node with node_type object and children per key', async ({ page }) => {
      const node = await page.evaluate(() =>
        window.testHelpers.buildTree('obj', { a: 1, b: 'two' }, 0)
      );
      expect(node.node_type).toBe('object');
      expect(node.children.length).toBe(2);
      const keys = node.children.map((c: { key: string }) => c.key);
      expect(keys).toContain('a');
      expect(keys).toContain('b');
    });
  });

  test.describe('Parser Helpers — _dfvEsc', () => {
    test('escapes &, <, >, and " to HTML entities', async ({ page }) => {
      const result = await page.evaluate(() =>
        window.testHelpers.esc('&<>"')
      );
      expect(result).toBe('&amp;&lt;&gt;&quot;');
    });
  });

  test.describe('DataFileView — Identity', () => {
    test('getTitle() returns only the filename portion of the path', async ({ page }) => {
      const info = await page.evaluate(async () =>
        await window.testHelpers.mountView('test.json')
      );
      expect(info.title).toBe('test.json');
    });

    test('getPath() returns the full relative path passed to the constructor', async ({ page }) => {
      const info = await page.evaluate(async () =>
        await window.testHelpers.mountView('test.json')
      );
      expect(info.path).toBe('test.json');
    });

    test('getIcon() returns table icon for csv and tree icon for json', async ({ page }) => {
      const csvInfo  = await page.evaluate(async () => await window.testHelpers.mountView('test.csv'));
      const jsonInfo = await page.evaluate(async () => await window.testHelpers.mountView('test.json'));
      expect(csvInfo.icon).toBe('📊');
      expect(jsonInfo.icon).toBe('🌲');
    });
  });

  test.describe('DataFileView — Mount JSON (tree)', () => {
    test('toolbar is visible after mounting a JSON file', async ({ page }) => {
      await page.evaluate(async () => await window.testHelpers.mountView('test.json'));
      await expect(page.locator('.rpf-view-toolbar')).toBeVisible();
    });

    test('rendered mode button has active class after initial mount', async ({ page }) => {
      await page.evaluate(async () => await window.testHelpers.mountView('test.json'));
      await expect(page.locator('.dfv-btn-rendered')).toHaveClass(/active/);
    });

    test('.dfv-content area is visible after mounting', async ({ page }) => {
      await page.evaluate(async () => await window.testHelpers.mountView('test.json'));
      await expect(page.locator('.dfv-content')).toBeVisible();
    });
  });

  test.describe('DataFileView — Mount CSV (table)', () => {
    test('toolbar rendered button shows table label with active class after mounting CSV', async ({ page }) => {
      await page.evaluate(async () => await window.testHelpers.mountView('test.csv'));
      const btn = page.locator('.dfv-btn-rendered');
      await expect(btn).toHaveClass(/active/);
      await expect(btn).toContainText('Table');
    });

    test('.dfv-content contains a .data-table-viewer element for CSV files', async ({ page }) => {
      await page.evaluate(async () => await window.testHelpers.mountView('test.csv'));
      await expect(page.locator('.dfv-content .data-table-viewer')).toBeVisible();
    });
  });

  test.describe('DataFileView — Mode switching', () => {
    test('clicking Source button reveals .rpf-code-pre element', async ({ page }) => {
      await page.evaluate(async () => await window.testHelpers.mountView('test.json'));
      await page.locator('.dfv-btn-source').click();
      await expect(page.locator('.rpf-code-pre')).toBeVisible();
    });

    test('clicking rendered button after source mode shows data viewer again', async ({ page }) => {
      await page.evaluate(async () => await window.testHelpers.mountView('test.json'));
      await page.locator('.dfv-btn-source').click();
      await page.locator('.dfv-btn-rendered').click();
      await expect(page.locator('.dfv-content')).toBeVisible();
      await expect(page.locator('.rpf-code-pre')).not.toBeVisible();
    });

    test('clicking Edit button shows a writable element (textarea fallback or codemirror)', async ({ page }) => {
      await page.evaluate(async () => await window.testHelpers.mountView('test.json'));
      await page.locator('.dfv-btn-edit').click();
      const hasFallback   = await page.locator('textarea.ev-fallback').count();
      const hasCodemirror = await page.locator('.cev-codemirror').count();
      expect(hasFallback + hasCodemirror).toBeGreaterThan(0);
    });
  });

  test.describe('DataFileView — Dirty state', () => {
    test('isDirty() returns false in rendered mode', async ({ page }) => {
      await page.evaluate(async () => await window.testHelpers.mountView('test.json'));
      const dirty = await page.evaluate(() => window.testHelpers.isDirty());
      expect(dirty).toBe(false);
    });

    test('isDirty() returns false in source mode', async ({ page }) => {
      await page.evaluate(async () => await window.testHelpers.mountView('test.json'));
      await page.locator('.dfv-btn-source').click();
      const dirty = await page.evaluate(() => window.testHelpers.isDirty());
      expect(dirty).toBe(false);
    });
  });

  test.describe('DataFileView — getState()', () => {
    test('getState() in rendered mode returns { mode: "rendered", scrollTop: 0 }', async ({ page }) => {
      await page.evaluate(async () => await window.testHelpers.mountView('test.json'));
      const state = await page.evaluate(() => window.testHelpers.getState());
      expect(state.mode).toBe('rendered');
      expect(state.scrollTop).toBe(0);
    });

    test('getState() in edit mode returns mode "rendered" (not "edit")', async ({ page }) => {
      await page.evaluate(async () => await window.testHelpers.mountView('test.json'));
      await page.locator('.dfv-btn-edit').click();
      const state = await page.evaluate(() => window.testHelpers.getState());
      expect(state.mode).toBe('rendered');
    });
  });
});
