import { test, expect } from '@playwright/test';
import * as path from 'path';

const harnessPath = path.resolve(__dirname, 'markdown-file-view-harness.html');

test.describe('MarkdownFileView', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto(`file://${harnessPath}`);
    await page.waitForSelector('#status:has-text("Ready")');
  });

  test.describe('Identity', () => {
    test('getTitle() returns README.md for path README.md', async ({ page }) => {
      const info = await page.evaluate(async () =>
        await window.testHelpers.mountView('README.md')
      );
      expect(info.title).toBe('README.md');
    });

    test('getPath() returns docs/README.md for that path', async ({ page }) => {
      const info = await page.evaluate(async () =>
        await window.testHelpers.mountView('docs/README.md')
      );
      expect(info.path).toBe('docs/README.md');
    });

    test('getIcon() returns the markdown emoji', async ({ page }) => {
      const info = await page.evaluate(async () =>
        await window.testHelpers.mountView('README.md')
      );
      expect(info.icon).toBe('📝');
    });
  });

  test.describe('Mount — Rendered mode', () => {
    test('toolbar is visible after mounting', async ({ page }) => {
      await page.evaluate(async () => await window.testHelpers.mountView('README.md'));
      await expect(page.locator('.rpf-view-toolbar')).toBeVisible();
    });

    test('rendered, source, and edit buttons are present in toolbar', async ({ page }) => {
      await page.evaluate(async () => await window.testHelpers.mountView('README.md'));
      await expect(page.locator('.mfv-btn-rendered')).toBeVisible();
      await expect(page.locator('.mfv-btn-source')).toBeVisible();
      await expect(page.locator('.mfv-btn-edit')).toBeVisible();
    });

    test('rendered button has active class after initial mount', async ({ page }) => {
      await page.evaluate(async () => await window.testHelpers.mountView('README.md'));
      await expect(page.locator('.mfv-btn-rendered')).toHaveClass(/active/);
    });

    test('.mfv-content div is visible after mounting', async ({ page }) => {
      await page.evaluate(async () => await window.testHelpers.mountView('README.md'));
      await expect(page.locator('.mfv-content')).toBeVisible();
    });
  });

  test.describe('Rendered — Markdown', () => {
    test('rendered mode shows mfv-markdown-body div or pre fallback', async ({ page }) => {
      await page.evaluate(async () => await window.testHelpers.mountView('README.md'));
      const hasMarkdownBody = await page.locator('.mfv-markdown-body').count();
      const hasPre          = await page.locator('.mfv-content pre').count();
      expect(hasMarkdownBody + hasPre).toBeGreaterThan(0);
    });

    test('content with bold markdown renders strong tag or pre fallback with text', async ({ page }) => {
      await page.evaluate(async () => {
        window.testHelpers.setContent('This is **bold** text.');
        await window.testHelpers.mountView('README.md');
      });
      // marked not loaded — pre fallback contains the raw markdown text
      const hasStrong  = await page.locator('.mfv-content strong').count();
      const hasFallback = await page.locator('.mfv-content pre').count();
      expect(hasStrong + hasFallback).toBeGreaterThan(0);
    });
  });

  test.describe('Source mode', () => {
    test('clicking Source button reveals .rpf-code-pre element', async ({ page }) => {
      await page.evaluate(async () => await window.testHelpers.mountView('README.md'));
      await page.locator('.mfv-btn-source').click();
      await expect(page.locator('.rpf-code-pre')).toBeVisible();
    });

    test('source button gets active class after clicking it', async ({ page }) => {
      await page.evaluate(async () => await window.testHelpers.mountView('README.md'));
      await page.locator('.mfv-btn-source').click();
      await expect(page.locator('.mfv-btn-source')).toHaveClass(/active/);
    });
  });

  test.describe('Edit mode', () => {
    test('clicking Edit button shows the Save button', async ({ page }) => {
      await page.evaluate(async () => await window.testHelpers.mountView('README.md'));
      await page.locator('.mfv-btn-edit').click();
      await expect(page.locator('.mfv-btn-save')).toBeVisible();
    });

    test('clicking Edit button shows a text editor (textarea fallback or codemirror)', async ({ page }) => {
      await page.evaluate(async () => await window.testHelpers.mountView('README.md'));
      await page.locator('.mfv-btn-edit').click();
      const hasFallback   = await page.locator('textarea.ev-fallback').count();
      const hasCodemirror = await page.locator('.cev-codemirror').count();
      expect(hasFallback + hasCodemirror).toBeGreaterThan(0);
    });

    test('edit button gets active class after clicking it', async ({ page }) => {
      await page.evaluate(async () => await window.testHelpers.mountView('README.md'));
      await page.locator('.mfv-btn-edit').click();
      await expect(page.locator('.mfv-btn-edit')).toHaveClass(/active/);
    });
  });

  test.describe('Dirty state', () => {
    test('isDirty() returns false in rendered mode', async ({ page }) => {
      await page.evaluate(async () => await window.testHelpers.mountView('README.md'));
      const dirty = await page.evaluate(() => window.testHelpers.isDirty());
      expect(dirty).toBe(false);
    });

    test('isDirty() returns false immediately after switching to edit mode with no changes', async ({ page }) => {
      await page.evaluate(async () => await window.testHelpers.mountView('README.md'));
      await page.locator('.mfv-btn-edit').click();
      const dirty = await page.evaluate(() => window.testHelpers.isDirty());
      expect(dirty).toBe(false);
    });

    test('isDirty() returns true after content changes in edit mode', async ({ page }) => {
      await page.evaluate(async () => await window.testHelpers.mountView('README.md'));
      await page.locator('.mfv-btn-edit').click();
      await page.locator('textarea.ev-fallback').fill('changed content');
      const dirty = await page.evaluate(() => window.testHelpers.isDirty());
      expect(dirty).toBe(true);
    });
  });

  test.describe('Save', () => {
    test('save() calls apiClient.writeFile and lastSaved is populated', async ({ page }) => {
      await page.evaluate(async () => await window.testHelpers.mountView('README.md'));
      await page.locator('.mfv-btn-edit').click();
      await page.locator('.mfv-btn-save').click();
      const saved = await page.evaluate(() => window.testHelpers.lastSaved());
      expect(saved).not.toBeNull();
      expect(saved.path).toBe('README.md');
    });

    test('isDirty() is false after successful save', async ({ page }) => {
      await page.evaluate(async () => await window.testHelpers.mountView('README.md'));
      await page.locator('.mfv-btn-edit').click();
      await page.locator('textarea.ev-fallback').fill('some new content');
      await page.locator('.mfv-btn-save').click();
      const dirty = await page.evaluate(() => window.testHelpers.isDirty());
      expect(dirty).toBe(false);
    });
  });

  test.describe('State save/restore', () => {
    test('getState() returns { mode: "rendered", scrollTop: 0 } in rendered mode', async ({ page }) => {
      await page.evaluate(async () => await window.testHelpers.mountView('README.md'));
      const state = await page.evaluate(() => window.testHelpers.getState());
      expect(state.mode).toBe('rendered');
      expect(state.scrollTop).toBe(0);
    });

    test('getState() returns mode "rendered" (not "edit") when in edit mode', async ({ page }) => {
      await page.evaluate(async () => await window.testHelpers.mountView('README.md'));
      await page.locator('.mfv-btn-edit').click();
      const state = await page.evaluate(() => window.testHelpers.getState());
      expect(state.mode).toBe('rendered');
    });

    test('setState({ mode: "source" }) switches to source mode', async ({ page }) => {
      await page.evaluate(async () => await window.testHelpers.mountView('README.md'));
      await page.evaluate(() => window.testHelpers.setState({ mode: 'source' }));
      await expect(page.locator('.rpf-code-pre')).toBeVisible();
      await expect(page.locator('.mfv-btn-source')).toHaveClass(/active/);
    });
  });
});
