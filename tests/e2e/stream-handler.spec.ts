import { test, expect } from '@playwright/test';
import * as path from 'path';

const harnessPath = path.resolve(__dirname, 'stream-handler-harness.html');

test.describe('StreamHandler', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto(`file://${harnessPath}`);
    await page.waitForSelector('#status:has-text("Ready")');
  });

  test.describe('Construction', () => {
    test('stores serverUrl', async ({ page }) => {
      const result = await page.evaluate(() => window.testHelpers.testConstructor());
      expect(result.serverUrl).toBe('http://s');
    });

    test('stores getHeaders as a function', async ({ page }) => {
      const result = await page.evaluate(() => window.testHelpers.testConstructor());
      expect(result.headersAreFn).toBe(true);
    });

    test('StreamHandler is available as window.StreamHandler', async ({ page }) => {
      const ok = await page.evaluate(() => window.testHelpers.testGlobal());
      expect(ok).toBe(true);
    });
  });

  test.describe('setServerUrl()', () => {
    test('updates the stored server URL', async ({ page }) => {
      const url = await page.evaluate(() => window.testHelpers.testSetServerUrl());
      expect(url).toBe('http://new');
    });
  });

  test.describe('stream() — happy path', () => {
    test('yields a parsed event for each valid data: line', async ({ page }) => {
      const events = await page.evaluate(() =>
        window.testHelpers.collectEvents([
          'data: {"type":"chunk","content":"hello"}',
          'data: {"type":"done"}'
        ])
      );
      expect(events).toHaveLength(2);
      expect(events[0]).toEqual({ type: 'chunk', content: 'hello' });
      expect(events[1]).toEqual({ type: 'done' });
    });

    test('yields events in order', async ({ page }) => {
      const types = await page.evaluate(async () => {
        const evts = await window.testHelpers.collectEvents([
          'data: {"type":"a"}',
          'data: {"type":"b"}',
          'data: {"type":"c"}'
        ]);
        return evts.map((e: any) => e.type);
      });
      expect(types).toEqual(['a', 'b', 'c']);
    });

    test('handles empty stream (no data lines)', async ({ page }) => {
      const events = await page.evaluate(() =>
        window.testHelpers.collectEvents([])
      );
      expect(events).toHaveLength(0);
    });

    test('handles a single event stream', async ({ page }) => {
      const events = await page.evaluate(() =>
        window.testHelpers.collectEvents(['data: {"type":"only"}'])
      );
      expect(events).toHaveLength(1);
      expect(events[0].type).toBe('only');
    });
  });

  test.describe('stream() — line filtering', () => {
    test('ignores non-data: lines (comments, blank lines, event: lines)', async ({ page }) => {
      const events = await page.evaluate(() =>
        window.testHelpers.testNonDataLines()
      );
      expect(events).toHaveLength(1);
      expect(events[0].type).toBe('only_this');
    });

    test('silently skips malformed JSON, passes through valid lines', async ({ page }) => {
      const events = await page.evaluate(() =>
        window.testHelpers.testMalformedJson()
      );
      expect(events).toHaveLength(2);
      expect(events[0].type).toBe('good');
      expect(events[1].type).toBe('also_good');
    });
  });

  test.describe('stream() — chunked buffering', () => {
    test('reassembles a JSON payload split across two stream chunks', async ({ page }) => {
      const events = await page.evaluate(() => window.testHelpers.testSplitChunk());
      expect(events).toHaveLength(1);
      expect(events[0].type).toBe('split');
    });
  });

  test.describe('stream() — error handling', () => {
    test('throws when response.ok is false', async ({ page }) => {
      const result = await page.evaluate(() => window.testHelpers.testErrorResponse());
      expect(result.threw).toBe(true);
      expect(result.message).toContain('Internal Server Error');
    });

    test('propagates AbortError when signal is already aborted', async ({ page }) => {
      const result = await page.evaluate(() => window.testHelpers.testAbort());
      expect(result.threw).toBe(true);
      expect(result.name).toBe('AbortError');
    });
  });
});
