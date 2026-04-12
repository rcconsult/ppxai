import { test, expect } from '@playwright/test';
import * as path from 'path';
import * as fs from 'fs';

const harnessPath = path.resolve(__dirname, 'app-state-harness.html');

// v1.17.4 post-release hotfix: AppState is schema-driven and throws
// in its constructor if `window.APP_STATE_SCHEMA` is missing. The
// real web app injects the schema via the FastAPI static route; the
// E2E harness runs over file:// which blocks synchronous XHR in
// modern Chromium/Playwright. Read the canonical schema from disk
// via Node fs and inject it with page.addInitScript — runs BEFORE
// any page script, guaranteed by Playwright contract.
const schemaPath = path.resolve(
  __dirname, '..', '..', 'ppxai', 'engine', 'app_state_schema.json'
);
const schemaJson = fs.readFileSync(schemaPath, 'utf-8');

test.describe('AppState', () => {
  test.beforeEach(async ({ page }) => {
    await page.addInitScript(
      (schemaJsonArg: string) => {
        (window as any).APP_STATE_SCHEMA = JSON.parse(schemaJsonArg);
      },
      schemaJson,
    );
    await page.goto(`file://${harnessPath}`);
    await page.waitForSelector('#status:has-text("Ready")');
  });

  test.describe('Construction', () => {
    test('reads back initial values via Proxy', async ({ page }) => {
      const vals = await page.evaluate(() => {
        const state = window.testHelpers.createState({ x: 42, label: 'hello' });
        return { x: state.x, label: state.label };
      });
      expect(vals.x).toBe(42);
      expect(vals.label).toBe('hello');
    });

    test('unset key returns undefined', async ({ page }) => {
      const val = await page.evaluate(() => {
        const state = window.testHelpers.createState({});
        return state.missing;
      });
      expect(val).toBeUndefined();
    });

    test('default construction (no args) does not throw', async ({ page }) => {
      const ok = await page.evaluate(() => {
        try { new AppState(); return true; } catch { return false; }
      });
      expect(ok).toBe(true);
    });
  });

  test.describe('Read / Write', () => {
    test('writes a new key and reads it back', async ({ page }) => {
      const val = await page.evaluate(() => {
        const state = window.testHelpers.createState({});
        state.foo = 'bar';
        return state.foo;
      });
      expect(val).toBe('bar');
    });

    test('overwrites an existing key', async ({ page }) => {
      const val = await page.evaluate(() => {
        const state = window.testHelpers.createState({ count: 1 });
        state.count = 99;
        return state.count;
      });
      expect(val).toBe(99);
    });

    test('supports boolean false as a value (not no-op)', async ({ page }) => {
      const val = await page.evaluate(() => {
        const state = window.testHelpers.createState({ flag: true });
        state.flag = false;
        return state.flag;
      });
      expect(val).toBe(false);
    });

    test('supports null as a value', async ({ page }) => {
      const val = await page.evaluate(() => {
        const state = window.testHelpers.createState({ item: 'something' });
        state.item = null;
        return state.item;
      });
      expect(val).toBeNull();
    });

    test('supports 0 as a value (not no-op)', async ({ page }) => {
      const val = await page.evaluate(() => {
        const state = window.testHelpers.createState({ n: 1 });
        state.n = 0;
        return state.n;
      });
      expect(val).toBe(0);
    });
  });

  test.describe('Observer (on)', () => {
    test('observer fires when value changes', async ({ page }) => {
      const result = await page.evaluate(() =>
        window.testHelpers.testObserver({ provider: '' }, 'provider', 'openai')
      );
      expect(result.callCount).toBe(1);
      expect(result.lastValue).toBe('openai');
      expect(result.readBack).toBe('openai');
    });

    test('observer does NOT fire when value is unchanged (no-op)', async ({ page }) => {
      const callCount = await page.evaluate(() =>
        window.testHelpers.testNoop({ theme: 'dark' }, 'theme', 'dark')
      );
      expect(callCount).toBe(0);
    });

    test('multiple observers on the same key all fire', async ({ page }) => {
      const calls = await page.evaluate(() =>
        window.testHelpers.testMultiObserver({ x: 0 }, 'x', 7)
      );
      expect(calls).toEqual(['a:7', 'b:7']);
    });

    test('observer on one key does not fire for a different key', async ({ page }) => {
      const callCount = await page.evaluate(() => {
        const state = window.testHelpers.createState({ a: 1, b: 2 });
        let count = 0;
        state.on('a', () => count++);
        state.b = 99;   // different key
        return count;
      });
      expect(callCount).toBe(0);
    });

    test('on() returns the proxy (supports chaining)', async ({ page }) => {
      const ok = await page.evaluate(() =>
        window.testHelpers.testChaining({}, 'key')
      );
      expect(ok).toBe(true);
    });

    test('observer fires on first write even when initial value was undefined', async ({ page }) => {
      const result = await page.evaluate(() => {
        const state = window.testHelpers.createState({});
        let fired = false;
        state.on('newKey', () => { fired = true; });
        state.newKey = 'hello';
        return fired;
      });
      expect(result).toBe(true);
    });
  });

  test.describe('snapshot()', () => {
    test('returns a plain object with all current values', async ({ page }) => {
      // AppState is schema-driven (v1.17.4) — `new AppState(initial)`
      // seeds EVERY schema-declared field with its default in addition
      // to the caller-provided initial keys. snapshot() returns all
      // live fields, so we assert the user-provided keys/values are
      // present (toMatchObject) rather than strict equality which
      // would fail on every schema default.
      const snap = await page.evaluate(() =>
        window.testHelpers.testSnapshot({ a: 1, b: 'two', c: true })
      );
      expect(snap).toMatchObject({ a: 1, b: 'two', c: true });
    });

    test('snapshot is a copy — mutating it does not affect state', async ({ page }) => {
      const result = await page.evaluate(() => {
        const state = window.testHelpers.createState({ x: 10 });
        const snap = state.snapshot();
        snap.x = 999;
        return state.x;
      });
      expect(result).toBe(10);
    });

    test('snapshot reflects latest writes', async ({ page }) => {
      const snap = await page.evaluate(() => {
        const state = window.testHelpers.createState({ x: 1 });
        state.x = 42;
        state.y = 'added';
        return state.snapshot();
      });
      expect(snap.x).toBe(42);
      expect(snap.y).toBe('added');
    });
  });

  test.describe('Internal fields', () => {
    test('_data and _listeners are accessible directly without going through state data', async ({ page }) => {
      const ok = await page.evaluate(() => {
        const state = window.testHelpers.createState({ z: 1 });
        // _data should be a plain object
        return typeof state._data === 'object' && state._data !== null;
      });
      expect(ok).toBe(true);
    });

    test('AppState class is available as window.AppState', async ({ page }) => {
      const ok = await page.evaluate(() => typeof window.AppState === 'function');
      expect(ok).toBe(true);
    });
  });
});
