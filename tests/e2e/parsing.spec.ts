import { test, expect } from '@playwright/test';
import * as path from 'path';

const testHarnessPath = path.resolve(__dirname, 'parsing-harness.html');

test.describe('Parsing Libraries', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto(`file://${testHarnessPath}`);
    // Wait for library checks to complete
    await page.waitForSelector('.lib-check.available, .lib-check.missing');
  });

  test.describe('Library Availability', () => {
    test('js-yaml library should be available', async ({ page }) => {
      const yamlStatus = page.locator('#yaml-status');
      await expect(yamlStatus).toHaveClass(/available/);
      await expect(yamlStatus).toContainText('js-yaml: available');
    });

    test('toml library should be available', async ({ page }) => {
      const tomlStatus = page.locator('#toml-status');
      await expect(tomlStatus).toHaveClass(/available/);
      await expect(tomlStatus).toContainText('toml: available');
    });

    test('hcl2 library should be available', async ({ page }) => {
      const hclStatus = page.locator('#hcl-status');
      await expect(hclStatus).toHaveClass(/available/);
      await expect(hclStatus).toContainText('hcl2: available');
    });
  });

  test.describe('YAML Parsing', () => {
    test('should parse YAML successfully', async ({ page }) => {
      const status = page.locator('#yaml-parse-status');
      await expect(status).toHaveClass(/success/);
      await expect(status).toContainText('YAML parsed successfully');
    });

    test('should render YAML tree viewer', async ({ page }) => {
      const treeContainer = page.locator('#yaml-tree');
      await expect(treeContainer.locator('.data-tree-viewer')).toBeVisible();
    });

    test('should show YAML keys in tree', async ({ page }) => {
      // Expand all nodes
      await page.locator('#yaml-tree .expand-all').click();

      // Check for expected keys (use first() due to multiple matches)
      await expect(page.locator('#yaml-tree .tree-key:has-text("name")').first()).toBeVisible();
      await expect(page.locator('#yaml-tree .tree-key:has-text("version")').first()).toBeVisible();
      await expect(page.locator('#yaml-tree .tree-key:has-text("server")').first()).toBeVisible();
    });

    test('should parse YAML nested objects', async ({ page }) => {
      await page.locator('#yaml-tree .expand-all').click();

      // Check for nested server.host
      await expect(page.locator('#yaml-tree .tree-key:has-text("host")')).toBeVisible();
      await expect(page.locator('#yaml-tree .tree-key:has-text("port")')).toBeVisible();
    });

    test('should parse YAML arrays', async ({ page }) => {
      await page.locator('#yaml-tree .expand-all').click();

      // Check for users array
      await expect(page.locator('#yaml-tree .tree-key:has-text("users")')).toBeVisible();
      // Array indices
      await expect(page.locator('#yaml-tree .tree-key:has-text("0")').first()).toBeVisible();
    });
  });

  test.describe('TOML Parsing', () => {
    test('should parse TOML successfully', async ({ page }) => {
      const status = page.locator('#toml-parse-status');
      await expect(status).toHaveClass(/success/);
      await expect(status).toContainText('TOML parsed successfully');
    });

    test('should render TOML tree viewer', async ({ page }) => {
      const treeContainer = page.locator('#toml-tree');
      await expect(treeContainer.locator('.data-tree-viewer')).toBeVisible();
    });

    test('should show TOML keys in tree', async ({ page }) => {
      await page.locator('#toml-tree .expand-all').click();

      // Check for expected keys
      await expect(page.locator('#toml-tree .tree-key:has-text("title")')).toBeVisible();
      await expect(page.locator('#toml-tree .tree-key:has-text("version")')).toBeVisible();
      await expect(page.locator('#toml-tree .tree-key:has-text("server")')).toBeVisible();
    });

    test('should parse TOML sections', async ({ page }) => {
      await page.locator('#toml-tree .expand-all').click();

      // Check for [server] section keys
      await expect(page.locator('#toml-tree .tree-key:has-text("host")')).toBeVisible();
      await expect(page.locator('#toml-tree .tree-key:has-text("port")')).toBeVisible();
      await expect(page.locator('#toml-tree .tree-key:has-text("enabled")')).toBeVisible();
    });

    test('should parse TOML arrays of tables', async ({ page }) => {
      await page.locator('#toml-tree .expand-all').click();

      // Check for [[users]] array
      await expect(page.locator('#toml-tree .tree-key:has-text("users")')).toBeVisible();
    });

    test('should parse TOML boolean values', async ({ page }) => {
      await page.locator('#toml-tree .expand-all').click();

      // Should have boolean type values
      await expect(page.locator('#toml-tree .tree-value.type-boolean').first()).toBeVisible();
    });

    test('should parse TOML number values', async ({ page }) => {
      await page.locator('#toml-tree .expand-all').click();

      // Should have number type values (port: 8080)
      await expect(page.locator('#toml-tree .tree-value.type-number').first()).toBeVisible();
    });
  });

  test.describe('HCL/Terraform Parsing', () => {
    test('should parse HCL successfully', async ({ page }) => {
      const status = page.locator('#hcl-parse-status');
      await expect(status).toHaveClass(/success/);
      await expect(status).toContainText('HCL parsed successfully');
    });

    test('should render HCL tree viewer', async ({ page }) => {
      const treeContainer = page.locator('#hcl-tree');
      await expect(treeContainer.locator('.data-tree-viewer')).toBeVisible();
    });

    test('should show HCL resource blocks', async ({ page }) => {
      await page.locator('#hcl-tree .expand-all').click();

      // Check for resource block
      await expect(page.locator('#hcl-tree .tree-key:has-text("resource")')).toBeVisible();
    });

    test('should show HCL variable blocks', async ({ page }) => {
      await page.locator('#hcl-tree .expand-all').click();

      // Check for variable block
      await expect(page.locator('#hcl-tree .tree-key:has-text("variable")')).toBeVisible();
    });

    test('should parse HCL nested attributes', async ({ page }) => {
      await page.locator('#hcl-tree .expand-all').click();

      // Check for nested aws_instance attributes
      await expect(page.locator('#hcl-tree .tree-key:has-text("ami")')).toBeVisible();
      await expect(page.locator('#hcl-tree .tree-key:has-text("instance_type")')).toBeVisible();
    });

    test('should parse HCL tags block', async ({ page }) => {
      await page.locator('#hcl-tree .expand-all').click();

      // Check for tags
      await expect(page.locator('#hcl-tree .tree-key:has-text("tags")')).toBeVisible();
      await expect(page.locator('#hcl-tree .tree-key:has-text("Name")')).toBeVisible();
    });
  });

  test.describe('Tree Viewer Integration', () => {
    test('YAML tree should support search', async ({ page }) => {
      const searchInput = page.locator('#yaml-tree .tree-search');
      await searchInput.fill('Alice');
      await searchInput.press('Enter');

      const matchCount = await page.locator('#yaml-tree .search-count').textContent();
      expect(matchCount).toContain('match');
    });

    test('TOML tree should support search', async ({ page }) => {
      const searchInput = page.locator('#toml-tree .tree-search');
      await searchInput.fill('localhost');
      await searchInput.press('Enter');

      const matchCount = await page.locator('#toml-tree .search-count').textContent();
      expect(matchCount).toContain('match');
    });

    test('HCL tree should support search', async ({ page }) => {
      const searchInput = page.locator('#hcl-tree .tree-search');
      await searchInput.fill('aws');
      await searchInput.press('Enter');

      const matchCount = await page.locator('#hcl-tree .search-count').textContent();
      expect(matchCount).toContain('match');
    });

    test('YAML tree should support jq expressions', async ({ page }) => {
      // Enable jq mode
      await page.locator('#yaml-tree .search-jq-btn').click();

      const searchInput = page.locator('#yaml-tree .tree-search');
      await searchInput.fill('.server.port');
      await searchInput.press('Enter');

      const matchCount = await page.locator('#yaml-tree .search-count').textContent();
      expect(matchCount).toContain('1 match');
    });

    test('TOML tree should support expand/collapse', async ({ page }) => {
      // Expand all
      await page.locator('#toml-tree .expand-all').click();
      const expandedNodes = await page.locator('#toml-tree .tree-node').count();

      // Collapse all
      await page.locator('#toml-tree .collapse-all').click();

      // Expand all again - should have same count
      await page.locator('#toml-tree .expand-all').click();
      const reExpandedNodes = await page.locator('#toml-tree .tree-node').count();

      expect(reExpandedNodes).toBe(expandedNodes);
    });
  });
});
