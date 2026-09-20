import { test, expect } from '@playwright/test';
import * as path from 'path';

/**
 * The tool-turn collapse contract (v1.19.3).
 *
 * Before this, every tool-loop ITERATION produced its own collapsed strip in
 * the transcript, and a long agentic run stacked a dozen of them between the
 * prompt and the answer. `.tool-turn` is the level above: one strip per
 * assistant turn, holding every iteration group of that turn.
 *
 * These tests drive the REAL ppxai/web/styles.css against the markup app.js
 * emits, so a CSS change that breaks the nesting fails here. The JS that
 * decides when to open, nest and close a turn lives on the app class and is
 * fenced separately in tests/test_web_shared_modules.py -- a green run here
 * is not a claim that tool rendering as a whole works.
 */
const harnessPath = path.resolve(__dirname, 'tool-turn-harness.html');

test.describe('Tool turn', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto(`file://${harnessPath}`);
    await page.waitForSelector('#status:has-text("Ready")');
  });

  test.describe('collapse contract', () => {
    test('starts collapsed, hiding every group inside it', async ({ page }) => {
      await page.evaluate(() => window.testHelpers.buildTurn(3, 2));

      await expect(page.locator('.tool-turn')).toHaveClass(/collapsed/);
      await expect(page.locator('.tool-turn-body')).toBeHidden();
      // The groups exist in the DOM -- they are hidden, not unrendered, so
      // expanding reveals the real history rather than re-fetching it.
      expect(await page.locator('.tool-turn-body .tool-group').count()).toBe(3);
    });

    test('one strip holds every iteration of the turn', async ({ page }) => {
      await page.evaluate(() => window.testHelpers.buildTurn(5, 1));

      // The regression this whole feature exists to prevent: five iterations
      // must be five groups inside ONE strip, not five strips.
      expect(await page.locator('.tool-turn').count()).toBe(1);
      expect(await page.locator('.tool-group').count()).toBe(5);
    });

    test('clicking the header reveals the groups', async ({ page }) => {
      await page.evaluate(() => window.testHelpers.buildTurn(2, 2));

      await page.locator('.tool-turn-header').click();

      await expect(page.locator('.tool-turn')).not.toHaveClass(/collapsed/);
      await expect(page.locator('.tool-turn-body')).toBeVisible();
    });

    test('groups stay independently collapsed inside an expanded turn', async ({ page }) => {
      await page.evaluate(() => window.testHelpers.buildTurn(2, 2));
      await page.locator('.tool-turn-header').click();

      // Expanding the turn shows the step headers, not every tool payload --
      // otherwise the strip just relocates the wall of text it replaced.
      await expect(page.locator('.tool-group').first()).toHaveClass(/collapsed/);
      await expect(page.locator('.tool-group-body').first()).toBeHidden();

      await page.locator('.tool-group-header').first().click();
      await expect(page.locator('.tool-group-body').first()).toBeVisible();
    });
  });

  test.describe('bubble disclosure', () => {
    test('a bubble with a payload hides it until expanded', async ({ page }) => {
      await page.evaluate(() => window.testHelpers.buildBubble(true));

      await expect(page.locator('.tool-details')).toBeHidden();
      await page.locator('.tool-header').click();
      await expect(page.locator('.tool-details')).toBeVisible();
    });

    test('a bubble with no payload offers no chevron to click', async ({ page }) => {
      await page.evaluate(() => window.testHelpers.buildBubble(false));

      // The pre-v1.19.3 bug: the chevron rendered unconditionally while the
      // details were only built in verbose mode, so clicking revealed
      // nothing. No payload now means no affordance at all.
      expect(await page.locator('.tool-expand').count()).toBe(0);
      expect(await page.locator('.tool-details').count()).toBe(0);
      await expect(page.locator('.tool-header')).toHaveClass(/is-static/);
    });
  });

  test.describe('accessibility', () => {
    test('the turn header is a keyboard-reachable button', async ({ page }) => {
      await page.evaluate(() => window.testHelpers.buildTurn(1, 1));
      const header = page.locator('.tool-turn-header');

      await expect(header).toHaveAttribute('role', 'button');
      await expect(header).toHaveAttribute('tabindex', '0');
      await expect(header).toHaveAttribute('aria-expanded', 'false');
      // aria-controls must name the element it actually shows, or a screen
      // reader announces a toggle with no target.
      const controls = await header.getAttribute('aria-controls');
      expect(await page.locator(`#${controls}`).getAttribute('class')).toContain('tool-turn-body');
    });

    test('aria-expanded tracks the collapsed state', async ({ page }) => {
      await page.evaluate(() => window.testHelpers.buildTurn(1, 1));
      const header = page.locator('.tool-turn-header');

      await header.click();
      await expect(header).toHaveAttribute('aria-expanded', 'true');
      await header.click();
      await expect(header).toHaveAttribute('aria-expanded', 'false');
    });

    test('a payload bubble carries aria-expanded; a static one does not', async ({ page }) => {
      await page.evaluate(() => window.testHelpers.buildBubble(true));
      await expect(page.locator('.tool-header')).toHaveAttribute('aria-expanded', 'false');

      await page.evaluate(() => window.testHelpers.buildBubble(false));
      expect(await page.locator('.tool-header').getAttribute('aria-expanded')).toBeNull();
    });
  });
});
