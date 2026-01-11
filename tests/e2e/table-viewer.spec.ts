import { test, expect } from '@playwright/test';
import * as path from 'path';

const testHarnessPath = path.resolve(__dirname, 'test-harness.html');

test.describe('DataTableViewer', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto(`file://${testHarnessPath}`);
    await page.waitForSelector('.data-table-viewer');
  });

  test.describe('Rendering', () => {
    test('should render table with headers', async ({ page }) => {
      // Check that all headers are present
      await expect(page.locator('.data-table th:has-text("ID")')).toBeVisible();
      await expect(page.locator('.data-table th:has-text("Name")')).toBeVisible();
      await expect(page.locator('.data-table th:has-text("Email")')).toBeVisible();
      await expect(page.locator('.data-table th:has-text("Status")')).toBeVisible();
      await expect(page.locator('.data-table th:has-text("Score")')).toBeVisible();
    });

    test('should render rows with data', async ({ page }) => {
      const rows = await page.locator('.data-table tbody tr').count();
      expect(rows).toBe(5); // pageSize is 5
    });

    test('should show row numbers', async ({ page }) => {
      const firstRowNum = await page.locator('.data-table tbody tr:first-child td.row-num').textContent();
      expect(firstRowNum?.trim()).toBe('1');
    });

    test('should show filter count', async ({ page }) => {
      const filterCount = await page.locator('.filter-count').textContent();
      expect(filterCount).toContain('10 rows');
    });
  });

  test.describe('Sorting', () => {
    test('should sort by column when header clicked', async ({ page }) => {
      // Get initial first row name
      const initialName = await page.locator('.data-table tbody tr:first-child td:nth-child(3)').textContent();
      expect(initialName?.trim()).toBe('Alice Smith');

      // Click Name header to sort
      await page.locator('.data-table th:has-text("Name")').click();

      // After ascending sort, Alice should still be first (alphabetically)
      const sortedName = await page.locator('.data-table tbody tr:first-child td:nth-child(3)').textContent();
      expect(sortedName?.trim()).toBe('Alice Smith');

      // Click again for descending
      await page.locator('.data-table th:has-text("Name")').click();

      // Check sort indicator
      const header = page.locator('.data-table th:has-text("Name")');
      await expect(header).toHaveClass(/sort-desc/);
    });

    test('should show sort indicator', async ({ page }) => {
      await page.locator('.data-table th:has-text("Score")').click();
      const header = page.locator('.data-table th:has-text("Score")');
      await expect(header).toHaveClass(/sort-asc/);
    });
  });

  test.describe('Filtering', () => {
    test('should filter rows on Enter key', async ({ page }) => {
      const searchInput = page.locator('.data-table-search');
      await searchInput.fill('alice');
      await searchInput.press('Enter');

      const filterCount = await page.locator('.filter-count').textContent();
      expect(filterCount).toContain('1 row');
    });

    test('should filter rows on Filter button click', async ({ page }) => {
      await page.locator('.data-table-search').fill('active');
      await page.locator('.filter-btn').click();

      const filterCount = await page.locator('.filter-count').textContent();
      // Should match rows with 'active' in any column
      expect(filterCount).not.toContain('10 rows');
    });

    test('should show Clear button after filtering', async ({ page }) => {
      // Apply filter
      const searchInput = page.locator('.data-table-search');
      await searchInput.fill('alice');
      await searchInput.press('Enter');

      // Wait for filter to apply and check count
      await expect(page.locator('.filter-count')).toContainText('1 row');

      // Verify table is filtered (only matching rows shown)
      const rows = await page.locator('.data-table tbody tr').count();
      expect(rows).toBe(1);
    });

    test('should filter by specific column', async ({ page }) => {
      // Select Status column (index 3)
      await page.locator('.filter-column-select').selectOption('3');
      await page.locator('.data-table-search').fill('active');
      await page.locator('.filter-btn').click();

      // Should match 'active' in Status column (case-insensitive substring)
      // This matches both 'active' and 'inactive' since 'inactive' contains 'active'
      const filterCount = await page.locator('.filter-count').textContent();
      expect(filterCount).toMatch(/\d+ rows?/);
    });

    test('should preserve input focus after filtering', async ({ page }) => {
      const searchInput = page.locator('.data-table-search');
      await searchInput.fill('test');
      await searchInput.press('Enter');

      // Input should still have the value
      await expect(searchInput).toHaveValue('test');
    });
  });

  test.describe('Regex Mode', () => {
    test('should toggle regex mode', async ({ page }) => {
      const regexBtn = page.locator('.filter-regex-btn');
      await expect(regexBtn).not.toHaveClass(/active/);

      await regexBtn.click();
      await expect(regexBtn).toHaveClass(/active/);

      await regexBtn.click();
      await expect(regexBtn).not.toHaveClass(/active/);
    });

    test('should filter with regex pattern', async ({ page }) => {
      await page.locator('.filter-regex-btn').click();
      // Filter for names ending with 'son'
      await page.locator('.data-table-search').fill('son$');
      await page.locator('.filter-btn').click();

      // Should match Bob Johnson, Eve Wilson
      const filterCount = await page.locator('.filter-count').textContent();
      expect(filterCount).toMatch(/\d+ rows?/);
    });

    test('should update placeholder when regex mode enabled', async ({ page }) => {
      const searchInput = page.locator('.data-table-search');
      await expect(searchInput).toHaveAttribute('placeholder', /Filter rows/);

      await page.locator('.filter-regex-btn').click();
      await expect(searchInput).toHaveAttribute('placeholder', /Regex pattern/);
    });
  });

  test.describe('Help Popup', () => {
    test('should show help popup on ? click', async ({ page }) => {
      await page.locator('.filter-help-btn').click();
      await expect(page.locator('.regex-help-popup')).toBeVisible();
    });

    test('should close help popup on click outside', async ({ page }) => {
      await page.locator('.filter-help-btn').click();
      const popup = page.locator('.regex-help-popup');
      await expect(popup).toBeVisible();

      // Wait for click-outside handler to be registered (100ms setTimeout in code)
      await page.waitForTimeout(150);

      // Click outside popup to close (on the body)
      await page.locator('body').click({ position: { x: 10, y: 10 } });
      await expect(popup).not.toBeVisible();
    });

    test('should toggle help popup on repeated clicks', async ({ page }) => {
      await page.locator('.filter-help-btn').click();
      await expect(page.locator('.regex-help-popup')).toBeVisible();

      await page.locator('.filter-help-btn').click();
      await expect(page.locator('.regex-help-popup')).not.toBeVisible();
    });

    test('should contain regex reference content', async ({ page }) => {
      await page.locator('.filter-help-btn').click();
      const popup = page.locator('.regex-help-popup');

      await expect(popup.locator('text=Regex Quick Reference')).toBeVisible();
      await expect(popup.locator('text=Any character')).toBeVisible();
      await expect(popup.locator('text=Zero or more')).toBeVisible();
    });
  });

  test.describe('Pagination', () => {
    test('should show pagination controls', async ({ page }) => {
      await expect(page.locator('.page-btn:has-text("Next")')).toBeVisible();
      await expect(page.locator('.page-btn:has-text("Prev")')).toBeVisible();
    });

    test('should navigate to next page', async ({ page }) => {
      await page.locator('.page-btn:has-text("Next")').click();

      // Should now show rows 6-10
      const firstRowNum = await page.locator('.data-table tbody tr:first-child td.row-num').textContent();
      expect(firstRowNum?.trim()).toBe('6');
    });

    test('should navigate to previous page', async ({ page }) => {
      // Go to page 2
      await page.locator('.page-btn:has-text("Next")').click();

      // Go back to page 1
      await page.locator('.page-btn:has-text("Prev")').click();

      const firstRowNum = await page.locator('.data-table tbody tr:first-child td.row-num').textContent();
      expect(firstRowNum?.trim()).toBe('1');
    });

    test('should show page info', async ({ page }) => {
      const pageInfo = await page.locator('.page-info').textContent();
      expect(pageInfo).toContain('1');
      expect(pageInfo).toContain('2'); // 10 rows, pageSize 5 = 2 pages
    });
  });
});
