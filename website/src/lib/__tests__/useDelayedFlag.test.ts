import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

/**
 * useDelayedFlag is a thin React hook around setTimeout. We don't have
 * jsdom or @testing-library/react in this repo, so we exercise the hook
 * by mocking React's useState/useEffect and replaying the effect lifecycle
 * the way React would.
 */

const reactStub = vi.hoisted(() => {
  type StateRef<T> = { value: T };
  type EffectSlot = {
    deps: unknown[] | null;
    cleanup?: () => void;
  };
  const states: StateRef<unknown>[] = [];
  const effectSlots: EffectSlot[] = [];
  let stateIndex = 0;
  let effectIndex = 0;
  // Pending effects to run on the next flush (their slot indices + bodies).
  const pending: Array<{ slot: number; fn: () => void | (() => void) }> = [];

  function depsChanged(prev: unknown[] | null, next: unknown[]): boolean {
    if (prev === null) return true;
    if (prev.length !== next.length) return true;
    return prev.some((v, i) => !Object.is(v, next[i]));
  }

  return {
    states,
    useState<T>(initial: T): [T, (next: T) => void] {
      const idx = stateIndex++;
      if (states[idx] === undefined) {
        states[idx] = { value: initial };
      }
      const ref = states[idx] as StateRef<T>;
      return [ref.value, (next: T) => { ref.value = next; }];
    },
    useEffect(fn: () => void | (() => void), deps: unknown[]) {
      const idx = effectIndex++;
      if (effectSlots[idx] === undefined) {
        effectSlots[idx] = { deps: null };
      }
      const slot = effectSlots[idx];
      if (depsChanged(slot.deps, deps)) {
        slot.deps = [...deps];
        pending.push({ slot: idx, fn });
      }
    },
    flushEffects() {
      while (pending.length > 0) {
        const { slot, fn } = pending.shift()!;
        const target = effectSlots[slot];
        if (target.cleanup) {
          target.cleanup();
          target.cleanup = undefined;
        }
        const cleanup = fn();
        if (typeof cleanup === "function") target.cleanup = cleanup;
      }
    },
    reset() {
      stateIndex = 0;
      effectIndex = 0;
    },
    fullReset() {
      // Run any outstanding cleanups so timers from prior tests don't leak.
      for (const slot of effectSlots) {
        if (slot?.cleanup) slot.cleanup();
      }
      states.length = 0;
      effectSlots.length = 0;
      pending.length = 0;
      stateIndex = 0;
      effectIndex = 0;
    },
  };
});

vi.mock("react", () => ({
  useState: reactStub.useState,
  useEffect: reactStub.useEffect,
}));

import { useDelayedFlag } from "@/lib/useDelayedFlag";

describe("useDelayedFlag", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    reactStub.fullReset();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("returns false initially when active=true", () => {
    const result = useDelayedFlag(true);
    expect(result).toBe(false);
  });

  it("flips to true after the delay elapses while active stays true", () => {
    expect(useDelayedFlag(true, 100)).toBe(false);
    reactStub.flushEffects();
    vi.advanceTimersByTime(99);
    reactStub.reset();
    expect(useDelayedFlag(true, 100)).toBe(false);
    vi.advanceTimersByTime(1);
    reactStub.reset();
    expect(useDelayedFlag(true, 100)).toBe(true);
  });

  it("does NOT flip to true if active turns off before the delay elapses", () => {
    useDelayedFlag(true, 100);
    reactStub.flushEffects();
    vi.advanceTimersByTime(50);
    // Caller flips active to false — the timer must be cleared
    reactStub.reset();
    useDelayedFlag(false, 100);
    reactStub.flushEffects();
    vi.advanceTimersByTime(200);
    reactStub.reset();
    expect(useDelayedFlag(false, 100)).toBe(false);
  });

  it("uses the default 100ms delay when none is provided", () => {
    useDelayedFlag(true);
    reactStub.flushEffects();
    vi.advanceTimersByTime(99);
    reactStub.reset();
    expect(useDelayedFlag(true)).toBe(false);
    vi.advanceTimersByTime(1);
    reactStub.reset();
    expect(useDelayedFlag(true)).toBe(true);
  });
});
