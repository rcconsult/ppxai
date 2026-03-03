import { test, expect } from '@playwright/test';
import * as path from 'path';

const harnessPath = path.resolve(__dirname, 'right-panel-frame-harness.html');

test.describe('RightPanelFrame', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto(`file://${harnessPath}`);
    await page.waitForSelector('#status:has-text("Ready")');
    await page.evaluate(() => window.testHelpers.setup());
  });

  // ── Construction ────────────────────────────────────────────────────────────

  test.describe('Construction', () => {
    test('stackSize is 0 initially', async ({ page }) => {
      const size = await page.evaluate(() => window.testHelpers.stackSize());
      expect(size).toBe(0);
    });

    test('activeView is null initially', async ({ page }) => {
      const active = await page.evaluate(() => window.testHelpers.activeView());
      expect(active).toBeNull();
    });

    test('frame is hidden initially', async ({ page }) => {
      const visible = await page.evaluate(() => window.testHelpers.isVisible());
      expect(visible).toBe(false);
    });
  });

  // ── push() ──────────────────────────────────────────────────────────────────

  test.describe('push()', () => {
    test('mounts the view (mountCount becomes 1)', async ({ page }) => {
      await page.evaluate(() => {
        window.testHelpers.makeView('a.txt', 'A');
        window.testHelpers.push('a.txt');
      });
      const count = await page.evaluate(() => window.testHelpers.viewStat('a.txt', 'mountCount'));
      expect(count).toBe(1);
    });

    test('sets activeView to the pushed view path', async ({ page }) => {
      await page.evaluate(() => {
        window.testHelpers.makeView('b.txt', 'B');
        window.testHelpers.push('b.txt');
      });
      const active = await page.evaluate(() => window.testHelpers.activeView());
      expect(active).toBe('b.txt');
    });

    test('shows the frame (isVisible becomes true)', async ({ page }) => {
      await page.evaluate(() => {
        window.testHelpers.makeView('c.txt', 'C');
        window.testHelpers.push('c.txt');
      });
      const visible = await page.evaluate(() => window.testHelpers.isVisible());
      expect(visible).toBe(true);
    });

    test('increments stackSize', async ({ page }) => {
      const sizes = await page.evaluate(() => {
        window.testHelpers.makeView('d.txt', 'D');
        window.testHelpers.makeView('e.txt', 'E');
        const before = window.testHelpers.stackSize();
        window.testHelpers.push('d.txt');
        const after1 = window.testHelpers.stackSize();
        window.testHelpers.push('e.txt');
        const after2 = window.testHelpers.stackSize();
        return { before, after1, after2 };
      });
      expect(sizes.before).toBe(0);
      expect(sizes.after1).toBe(1);
      expect(sizes.after2).toBe(2);
    });

    test('calls onActivate on the pushed view', async ({ page }) => {
      await page.evaluate(() => {
        window.testHelpers.makeView('f.txt', 'F');
        window.testHelpers.push('f.txt');
      });
      const count = await page.evaluate(() => window.testHelpers.viewStat('f.txt', 'activateCount'));
      // showFrame() also calls onActivate on the active view — count >= 1
      expect(count).toBeGreaterThanOrEqual(1);
    });
  });

  // ── Deduplication ───────────────────────────────────────────────────────────

  test.describe('Deduplication', () => {
    test('pushing same path twice keeps stackSize at 1 (promotes existing)', async ({ page }) => {
      const size = await page.evaluate(() => {
        window.testHelpers.makeView('dup.txt', 'Dup');
        window.testHelpers.push('dup.txt');
        window.testHelpers.push('dup.txt');
        return window.testHelpers.stackSize();
      });
      expect(size).toBe(1);
    });

    test('dedup=false config allows the same path to be pushed twice', async ({ page }) => {
      const size = await page.evaluate(() => {
        window.testHelpers.setup({ dedup: false });
        window.testHelpers.makeView('dup2.txt', 'Dup2');
        window.testHelpers.push('dup2.txt');
        window.testHelpers.push('dup2.txt');
        return window.testHelpers.stackSize();
      });
      expect(size).toBe(2);
    });
  });

  // ── LRU Eviction ────────────────────────────────────────────────────────────

  test.describe('LRU Eviction', () => {
    test('at capacity, pushing a third view evicts the bottom (oldest) view', async ({ page }) => {
      await page.evaluate(() => {
        window.testHelpers.setup({ stackSize: 2 });
        window.testHelpers.makeView('lru1.txt', 'LRU1');
        window.testHelpers.makeView('lru2.txt', 'LRU2');
        window.testHelpers.makeView('lru3.txt', 'LRU3');
        window.testHelpers.push('lru1.txt');
        window.testHelpers.push('lru2.txt');
        window.testHelpers.push('lru3.txt');  // lru1 should be evicted
      });
      const unmounted = await page.evaluate(() => window.testHelpers.viewStat('lru1.txt', 'unmountCount'));
      expect(unmounted).toBe(1);
    });

    test('evicted view is the bottom one (first pushed), not the active one', async ({ page }) => {
      const activeAfterEviction = await page.evaluate(() => {
        window.testHelpers.setup({ stackSize: 2 });
        window.testHelpers.makeView('ev1.txt', 'EV1');
        window.testHelpers.makeView('ev2.txt', 'EV2');
        window.testHelpers.makeView('ev3.txt', 'EV3');
        window.testHelpers.push('ev1.txt');
        window.testHelpers.push('ev2.txt');
        window.testHelpers.push('ev3.txt');
        return window.testHelpers.activeView();
      });
      expect(activeAfterEviction).toBe('ev3.txt');
    });

    test('pinned views are not evicted; push is rejected when all non-top views are pinned', async ({ page }) => {
      const sizeAfterRejectedPush = await page.evaluate(() => {
        window.testHelpers.setup({ stackSize: 2 });
        window.testHelpers.makeView('pin1.txt', 'Pin1');
        window.testHelpers.makeView('pin2.txt', 'Pin2');
        window.testHelpers.makeView('pin3.txt', 'Pin3');
        window.testHelpers.push('pin1.txt');
        window.testHelpers.push('pin2.txt');
        // pin the bottom view so it cannot be evicted
        window.testHelpers.pinView('pin1.txt');
        // push a third view — eviction impossible, should be silently rejected
        window.testHelpers.push('pin3.txt');
        return window.testHelpers.stackSize();
      });
      // Stack must remain at 2: pin1 (pinned) + pin2 (active), pin3 rejected
      expect(sizeAfterRejectedPush).toBe(2);
    });
  });

  // ── pop() ───────────────────────────────────────────────────────────────────

  test.describe('pop()', () => {
    test('decrements stackSize', async ({ page }) => {
      const result = await page.evaluate(async () => {
        window.testHelpers.makeView('pop1.txt', 'Pop1');
        window.testHelpers.push('pop1.txt');
        const before = window.testHelpers.stackSize();
        await window.testHelpers.pop();
        return { before, after: window.testHelpers.stackSize() };
      });
      expect(result.before).toBe(1);
      expect(result.after).toBe(0);
    });

    test('unmounts the popped view (unmountCount = 1)', async ({ page }) => {
      await page.evaluate(async () => {
        window.testHelpers.makeView('pop2.txt', 'Pop2');
        window.testHelpers.push('pop2.txt');
        await window.testHelpers.pop();
      });
      const count = await page.evaluate(() => window.testHelpers.viewStat('pop2.txt', 'unmountCount'));
      expect(count).toBe(1);
    });

    test('hides the frame when the stack becomes empty', async ({ page }) => {
      const visible = await page.evaluate(async () => {
        window.testHelpers.makeView('pop3.txt', 'Pop3');
        window.testHelpers.push('pop3.txt');
        await window.testHelpers.pop();
        return window.testHelpers.isVisible();
      });
      expect(visible).toBe(false);
    });
  });

  // ── back() / forward() ──────────────────────────────────────────────────────

  test.describe('back() / forward()', () => {
    test('back() changes activeView to the previous view', async ({ page }) => {
      const active = await page.evaluate(() => {
        window.testHelpers.makeView('nav1.txt', 'Nav1');
        window.testHelpers.makeView('nav2.txt', 'Nav2');
        window.testHelpers.push('nav1.txt');
        window.testHelpers.push('nav2.txt');
        return window.testHelpers.back();  // returns new activeView path
      });
      expect(active).toBe('nav1.txt');
    });

    test('back() on a single-view stack is a no-op (activeView unchanged)', async ({ page }) => {
      const active = await page.evaluate(() => {
        window.testHelpers.makeView('solo.txt', 'Solo');
        window.testHelpers.push('solo.txt');
        window.testHelpers.back();
        return window.testHelpers.activeView();
      });
      expect(active).toBe('solo.txt');
    });

    test('forward() restores a previously backed-out view', async ({ page }) => {
      const active = await page.evaluate(() => {
        window.testHelpers.makeView('fwd1.txt', 'Fwd1');
        window.testHelpers.makeView('fwd2.txt', 'Fwd2');
        window.testHelpers.push('fwd1.txt');
        window.testHelpers.push('fwd2.txt');
        window.testHelpers.back();    // fwd1 is now active
        return window.testHelpers.forward();  // fwd2 should be restored
      });
      expect(active).toBe('fwd2.txt');
    });

    test('forward() on a single-view stack is a no-op (activeView unchanged)', async ({ page }) => {
      const active = await page.evaluate(() => {
        window.testHelpers.makeView('solo2.txt', 'Solo2');
        window.testHelpers.push('solo2.txt');
        window.testHelpers.forward();
        return window.testHelpers.activeView();
      });
      expect(active).toBe('solo2.txt');
    });
  });

  // ── Visibility ──────────────────────────────────────────────────────────────

  test.describe('Visibility', () => {
    test('showFrame() makes the container visible (removes .hidden class)', async ({ page }) => {
      const result = await page.evaluate(() => {
        const visible = window.testHelpers.showFrame();
        return { visible, containerHidden: window.testHelpers.isContainerHidden() };
      });
      expect(result.visible).toBe(true);
      expect(result.containerHidden).toBe(false);
    });

    test('hideFrame() hides the container (adds .hidden class)', async ({ page }) => {
      const result = await page.evaluate(() => {
        window.testHelpers.showFrame();
        const visible = window.testHelpers.hideFrame();
        return { visible, containerHidden: window.testHelpers.isContainerHidden() };
      });
      expect(result.visible).toBe(false);
      expect(result.containerHidden).toBe(true);
    });

    test('toggleFrame() flips visibility from false to true and back', async ({ page }) => {
      const states = await page.evaluate(() => {
        const v1 = window.testHelpers.toggleFrame();  // hidden → visible
        const v2 = window.testHelpers.toggleFrame();  // visible → hidden
        return [v1, v2];
      });
      expect(states[0]).toBe(true);
      expect(states[1]).toBe(false);
    });
  });

  // ── getStackInfo() ──────────────────────────────────────────────────────────

  test.describe('getStackInfo()', () => {
    test('returns entries in most-recent-first order with isActive=true for the first entry', async ({ page }) => {
      const info = await page.evaluate(() => {
        window.testHelpers.makeView('si1.txt', 'SI1');
        window.testHelpers.makeView('si2.txt', 'SI2');
        window.testHelpers.makeView('si3.txt', 'SI3');
        window.testHelpers.push('si1.txt');
        window.testHelpers.push('si2.txt');
        window.testHelpers.push('si3.txt');
        return window.testHelpers.getStackInfo();
      });
      expect(info).toHaveLength(3);
      expect(info[0].isActive).toBe(true);
      expect(info[0].title).toBe('SI3');   // most recently pushed
      expect(info[2].title).toBe('SI1');   // oldest
    });

    test('stackIndex in info matches position in the internal stack (0 = bottom)', async ({ page }) => {
      const indices = await page.evaluate(() => {
        window.testHelpers.makeView('idx1.txt', 'Idx1');
        window.testHelpers.makeView('idx2.txt', 'Idx2');
        window.testHelpers.push('idx1.txt');
        window.testHelpers.push('idx2.txt');
        return window.testHelpers.getStackInfo().map((i: any) => i.stackIndex);
      });
      // getStackInfo reverses the array: entry[0] has the highest stackIndex
      expect(indices[0]).toBe(1);
      expect(indices[1]).toBe(0);
    });

    test('isDirty and isPinned are reflected correctly in stack info', async ({ page }) => {
      const info = await page.evaluate(() => {
        window.testHelpers.makeView('dirty.txt', 'Dirty', { dirty: true });
        window.testHelpers.makeView('pinned.txt', 'Pinned', { pinned: true });
        window.testHelpers.push('dirty.txt');
        window.testHelpers.push('pinned.txt');
        return window.testHelpers.getStackInfo();
      });
      const dirtyEntry  = info.find((i: any) => i.title === 'Dirty');
      const pinnedEntry = info.find((i: any) => i.title === 'Pinned');
      expect(dirtyEntry.isDirty).toBe(true);
      expect(pinnedEntry.isPinned).toBe(true);
    });
  });

  // ── activateByIndex() ───────────────────────────────────────────────────────

  test.describe('activateByIndex()', () => {
    test('promotes the view at the given stack index to the top', async ({ page }) => {
      const active = await page.evaluate(() => {
        window.testHelpers.makeView('abi1.txt', 'ABI1');
        window.testHelpers.makeView('abi2.txt', 'ABI2');
        window.testHelpers.makeView('abi3.txt', 'ABI3');
        window.testHelpers.push('abi1.txt');  // stackIndex 0
        window.testHelpers.push('abi2.txt');  // stackIndex 1
        window.testHelpers.push('abi3.txt');  // stackIndex 2 (active)
        // Activate abi1 (bottom of stack, stackIndex 0)
        return window.testHelpers.activateByIndex(0);
      });
      expect(active).toBe('abi1.txt');
    });

    test('activating the already-active view (last index) is a no-op', async ({ page }) => {
      const result = await page.evaluate(() => {
        window.testHelpers.makeView('nop1.txt', 'Nop1');
        window.testHelpers.makeView('nop2.txt', 'Nop2');
        window.testHelpers.push('nop1.txt');
        window.testHelpers.push('nop2.txt');
        const sizeBefore = window.testHelpers.stackSize();
        // nop2 is at stackIndex 1 (top); promoting it should be a no-op
        window.testHelpers.activateByIndex(1);
        const sizeAfter  = window.testHelpers.stackSize();
        const active     = window.testHelpers.activeView();
        return { sizeBefore, sizeAfter, active };
      });
      expect(result.sizeBefore).toBe(2);
      expect(result.sizeAfter).toBe(2);
      expect(result.active).toBe('nop2.txt');
    });
  });

  // ── handleKeyDown() ─────────────────────────────────────────────────────────

  test.describe('handleKeyDown()', () => {
    test('ArrowLeft with the correct modifier navigates back and returns consumed=true', async ({ page }) => {
      const result = await page.evaluate(() => {
        window.testHelpers.makeView('kl1.txt', 'KL1');
        window.testHelpers.makeView('kl2.txt', 'KL2');
        window.testHelpers.push('kl1.txt');
        window.testHelpers.push('kl2.txt');
        const mac = window.testHelpers.isMac();
        const consumed = window.testHelpers.handleKey('ArrowLeft', mac, false, !mac);
        const active   = window.testHelpers.activeView();
        return { consumed, active };
      });
      expect(result.consumed).toBe(true);
      expect(result.active).toBe('kl1.txt');
    });

    test('ArrowRight with the correct modifier navigates forward and returns consumed=true', async ({ page }) => {
      const result = await page.evaluate(() => {
        window.testHelpers.makeView('kr1.txt', 'KR1');
        window.testHelpers.makeView('kr2.txt', 'KR2');
        window.testHelpers.push('kr1.txt');
        window.testHelpers.push('kr2.txt');
        window.testHelpers.back();   // now kr1 is active, kr2 is at bottom
        const mac = window.testHelpers.isMac();
        const consumed = window.testHelpers.handleKey('ArrowRight', mac, false, !mac);
        const active   = window.testHelpers.activeView();
        return { consumed, active };
      });
      expect(result.consumed).toBe(true);
      expect(result.active).toBe('kr2.txt');
    });

    test('Escape hides the frame and returns consumed=true', async ({ page }) => {
      const result = await page.evaluate(() => {
        window.testHelpers.makeView('esc.txt', 'Esc');
        window.testHelpers.push('esc.txt');  // makes frame visible
        const consumed = window.testHelpers.handleKey('Escape');
        return { consumed, visible: window.testHelpers.isVisible() };
      });
      expect(result.consumed).toBe(true);
      expect(result.visible).toBe(false);
    });

    test('unrecognised key returns consumed=false', async ({ page }) => {
      const consumed = await page.evaluate(() => {
        window.testHelpers.makeView('uk.txt', 'UK');
        window.testHelpers.push('uk.txt');
        return window.testHelpers.handleKey('F12');
      });
      expect(consumed).toBe(false);
    });
  });

  // ── State save / restore ────────────────────────────────────────────────────

  test.describe('State save / restore', () => {
    test('after back(), the re-mounted view receives its saved state as pendingState', async ({ page }) => {
      const pending = await page.evaluate(() => {
        window.testHelpers.makeView('sr1.txt', 'SR1');
        window.testHelpers.makeView('sr2.txt', 'SR2');
        window.testHelpers.push('sr1.txt');
        // Give sr1 some state to save
        window._views['sr1.txt']._savedState = { scrollTop: 42 };
        window.testHelpers.push('sr2.txt');
        // back() saves sr2's state and re-mounts sr1 with its saved state
        window.testHelpers.back();
        // sr1 was re-mounted; _pendingStateWhenMounted should reflect { scrollTop: 42 }
        return window.testHelpers.pendingStateWhenMounted('sr1.txt');
      });
      expect(pending).not.toBeNull();
      expect((pending as any).scrollTop).toBe(42);
    });

    test('_savedStates is cleared for a view when it is popped', async ({ page }) => {
      const mapSize = await page.evaluate(async () => {
        window.testHelpers.makeView('sc1.txt', 'SC1');
        window.testHelpers.makeView('sc2.txt', 'SC2');
        window.testHelpers.push('sc1.txt');
        window._views['sc1.txt']._savedState = { mode: 'edit' };
        window.testHelpers.push('sc2.txt');
        // After pushing sc2, sc1's state is saved in _savedStates
        const sizeAfterPush = window.testHelpers.savedStatesSize();
        // Pop sc2 and then pop sc1 — both should be removed from _savedStates
        await window.testHelpers.pop();  // sc1 becomes active
        await window.testHelpers.pop();  // stack empty
        return { sizeAfterPush, sizeAfterPop: window.testHelpers.savedStatesSize() };
      });
      // After the second push the frame saved sc1's state (size >= 1)
      expect(mapSize.sizeAfterPush).toBeGreaterThanOrEqual(1);
      // After popping everything the map must be empty
      expect(mapSize.sizeAfterPop).toBe(0);
    });
  });
});
