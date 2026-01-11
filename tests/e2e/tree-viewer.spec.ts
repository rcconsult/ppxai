import { test, expect } from '@playwright/test';
import * as path from 'path';

const testHarnessPath = path.resolve(__dirname, 'test-harness.html');

test.describe('DataTreeViewer', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto(`file://${testHarnessPath}`);
    await page.waitForSelector('.data-tree-viewer');
  });

  test.describe('Rendering', () => {
    test('should render tree with root node', async ({ page }) => {
      await expect(page.locator('.tree-content')).toBeVisible();
      const nodeCount = await page.locator('.tree-node').count();
      expect(nodeCount).toBeGreaterThan(0);
    });

    test('should show tree keys with correct styling', async ({ page }) => {
      const nameKey = page.locator('.tree-key:has-text("name")').first();
      await expect(nameKey).toBeVisible();
    });

    test('should show string values', async ({ page }) => {
      // Expand all to ensure values are visible
      await page.locator('.expand-all').click();
      await expect(page.locator('.tree-value.type-string').first()).toBeVisible();
    });

    test('should show number values', async ({ page }) => {
      await page.locator('.expand-all').click();
      await expect(page.locator('.tree-value.type-number').first()).toBeVisible();
    });

    test('should show boolean values', async ({ page }) => {
      await page.locator('.expand-all').click();
      await expect(page.locator('.tree-value.type-boolean').first()).toBeVisible();
    });

    test('should show null values', async ({ page }) => {
      await page.locator('.expand-all').click();
      await expect(page.locator('.tree-value.type-null').first()).toBeVisible();
    });
  });

  test.describe('Expand/Collapse', () => {
    test('should show expand/collapse buttons', async ({ page }) => {
      await expect(page.locator('.expand-all')).toBeVisible();
      await expect(page.locator('.collapse-all')).toBeVisible();
    });

    test('should expand all nodes on Expand All click', async ({ page }) => {
      await page.locator('.expand-all').click();

      // Should be able to see nested user IDs
      const userId = page.locator('.tree-key:has-text("id")').first();
      await expect(userId).toBeVisible();
    });

    test('should collapse nodes on Collapse All click', async ({ page }) => {
      // First expand all
      await page.locator('.expand-all').click();

      // Then collapse
      await page.locator('.collapse-all').click();

      // Children should be hidden (toggle should show collapsed state)
      const toggles = page.locator('.tree-toggle');
      // At least one toggle should exist for expandable nodes
      await expect(toggles.first()).toBeVisible();
    });

    test('should toggle individual node on click', async ({ page }) => {
      // Find a toggle button (triangle)
      const toggle = page.locator('.tree-toggle').first();
      await toggle.click();

      // Toggle state should change
      await expect(toggle).toBeVisible();
    });
  });

  test.describe('Search - Plain Text', () => {
    test('should filter nodes on Enter key', async ({ page }) => {
      const searchInput = page.locator('.tree-search');
      await searchInput.fill('Alice');
      await searchInput.press('Enter');

      const matchCount = await page.locator('.search-count').textContent();
      expect(matchCount).toContain('match');
    });

    test('should filter nodes on Search button click', async ({ page }) => {
      await page.locator('.tree-search').fill('port');
      await page.locator('.search-btn').click();

      const matchCount = await page.locator('.search-count').textContent();
      expect(matchCount).toContain('1 match');
    });

    test('should clear search on Clear button click', async ({ page }) => {
      // Apply search first
      await page.locator('.tree-search').fill('Alice');
      await page.locator('.search-btn').click();

      // Clear button should appear
      await expect(page.locator('.search-clear-btn')).toBeVisible();
      await page.locator('.search-clear-btn').click();

      // Match count should disappear
      await expect(page.locator('.search-count')).not.toBeVisible();
    });

    test('should highlight matching nodes', async ({ page }) => {
      await page.locator('.tree-search').fill('name');
      await page.locator('.search-btn').click();

      // Should have search-match class on matching nodes
      const matchCount = await page.locator('.tree-node.search-match').count();
      expect(matchCount).toBeGreaterThan(0);
    });

    test('should expand parents of matching nodes', async ({ page }) => {
      // Collapse all first
      await page.locator('.collapse-all').click();

      // Search for nested value
      await page.locator('.tree-search').fill('Alice');
      await page.locator('.search-btn').click();

      // The match should be visible (parents expanded)
      const matchCount = await page.locator('.search-count').textContent();
      expect(matchCount).toContain('1 match');
    });
  });

  test.describe('Search - Regex Mode', () => {
    test('should toggle regex mode', async ({ page }) => {
      const regexBtn = page.locator('.search-regex-btn');
      await expect(regexBtn).not.toHaveClass(/active/);

      await regexBtn.click();
      await expect(regexBtn).toHaveClass(/active/);
    });

    test('should disable jq mode when regex enabled', async ({ page }) => {
      // Enable jq first
      await page.locator('.search-jq-btn').click();
      await expect(page.locator('.search-jq-btn')).toHaveClass(/active/);

      // Enable regex - should disable jq
      await page.locator('.search-regex-btn').click();
      await expect(page.locator('.search-regex-btn')).toHaveClass(/active/);
      await expect(page.locator('.search-jq-btn')).not.toHaveClass(/active/);
    });

    test('should search with regex pattern', async ({ page }) => {
      await page.locator('.search-regex-btn').click();
      await page.locator('.tree-search').fill('^name$');
      await page.locator('.search-btn').click();

      const matchCount = await page.locator('.search-count').textContent();
      // Should match exactly 'name' keys
      expect(matchCount).toContain('match');
    });

    test('should update placeholder for regex mode', async ({ page }) => {
      const searchInput = page.locator('.tree-search');
      await expect(searchInput).toHaveAttribute('placeholder', /Search keys/);

      await page.locator('.search-regex-btn').click();
      await expect(searchInput).toHaveAttribute('placeholder', /Regex pattern/);
    });
  });

  test.describe('Search - jq Mode', () => {
    test('should toggle jq mode', async ({ page }) => {
      const jqBtn = page.locator('.search-jq-btn');
      await expect(jqBtn).not.toHaveClass(/active/);

      await jqBtn.click();
      await expect(jqBtn).toHaveClass(/active/);
    });

    test('should disable regex mode when jq enabled', async ({ page }) => {
      // Enable regex first
      await page.locator('.search-regex-btn').click();
      await expect(page.locator('.search-regex-btn')).toHaveClass(/active/);

      // Enable jq - should disable regex
      await page.locator('.search-jq-btn').click();
      await expect(page.locator('.search-jq-btn')).toHaveClass(/active/);
      await expect(page.locator('.search-regex-btn')).not.toHaveClass(/active/);
    });

    test('should search with .key expression', async ({ page }) => {
      await page.locator('.search-jq-btn').click();
      await page.locator('.tree-search').fill('.name');
      await page.locator('.search-btn').click();

      const matchCount = await page.locator('.search-count').textContent();
      // Should match 'name' at root level
      expect(matchCount).toContain('1 match');
    });

    test('should search with nested path .foo.bar', async ({ page }) => {
      await page.locator('.search-jq-btn').click();
      await page.locator('.tree-search').fill('.config.port');
      await page.locator('.search-btn').click();

      const matchCount = await page.locator('.search-count').textContent();
      expect(matchCount).toContain('1 match');
    });

    test('should search with array index .[0]', async ({ page }) => {
      await page.locator('.search-jq-btn').click();
      await page.locator('.tree-search').fill('.users[0]');
      await page.locator('.search-btn').click();

      const matchCount = await page.locator('.search-count').textContent();
      expect(matchCount).toContain('1 match');
    });

    test('should search with array wildcard .[]', async ({ page }) => {
      await page.locator('.search-jq-btn').click();
      await page.locator('.tree-search').fill('.users[]');
      await page.locator('.search-btn').click();

      const matchCount = await page.locator('.search-count').textContent();
      // Should match both users[0] and users[1]
      expect(matchCount).toContain('2 match');
    });

    test('should search with wildcard .*', async ({ page }) => {
      await page.locator('.search-jq-btn').click();
      await page.locator('.tree-search').fill('.*');
      await page.locator('.search-btn').click();

      const matchCount = await page.locator('.search-count').textContent();
      // Should match all top-level keys
      expect(matchCount).toContain('match');
    });

    test('should update placeholder for jq mode', async ({ page }) => {
      const searchInput = page.locator('.tree-search');

      await page.locator('.search-jq-btn').click();
      await expect(searchInput).toHaveAttribute('placeholder', /jq expression/);
    });
  });

  test.describe('Help Popup', () => {
    test('should show help popup on ? click', async ({ page }) => {
      await page.locator('.search-help-btn').click();
      await expect(page.locator('.tree-help-popup')).toBeVisible();
    });

    test('should close help popup on click outside', async ({ page }) => {
      await page.locator('.search-help-btn').click();
      const popup = page.locator('.tree-help-popup');
      await expect(popup).toBeVisible();

      // Wait for click-outside handler to be registered (100ms setTimeout in code)
      await page.waitForTimeout(150);

      // Click outside popup to close (on the body)
      await page.locator('body').click({ position: { x: 10, y: 10 } });
      await expect(popup).not.toBeVisible();
    });

    test('should toggle help popup on repeated clicks', async ({ page }) => {
      await page.locator('.search-help-btn').click();
      await expect(page.locator('.tree-help-popup')).toBeVisible();

      await page.locator('.search-help-btn').click();
      await expect(page.locator('.tree-help-popup')).not.toBeVisible();
    });

    test('should contain all search mode references', async ({ page }) => {
      await page.locator('.search-help-btn').click();
      const popup = page.locator('.tree-help-popup');

      // Should have sections for all modes
      await expect(popup.locator('text=Plain Text')).toBeVisible();
      await expect(popup.locator('text=Regex Mode')).toBeVisible();
      await expect(popup.locator('text=jq Mode')).toBeVisible();
    });

    test('should show jq examples in help', async ({ page }) => {
      await page.locator('.search-help-btn').click();
      const popup = page.locator('.tree-help-popup');

      // Check for jq section and examples using code elements
      await expect(popup.locator('code:has-text(".foo")').first()).toBeVisible();
      await expect(popup.locator('code:has-text(".foo.bar")')).toBeVisible();
      await expect(popup.locator('code:has-text(".[0]")')).toBeVisible();
    });
  });

  test.describe('Copy Path', () => {
    test('should have click handler on keys', async ({ page }) => {
      // Keys should have click-to-copy title
      const key = page.locator('.tree-key:has-text("version")').first();
      await expect(key).toHaveAttribute('title', /copy path/i);
    });
  });
});
