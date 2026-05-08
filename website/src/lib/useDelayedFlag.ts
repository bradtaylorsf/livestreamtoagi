"use client";

import { useEffect, useState } from "react";

/**
 * Returns true only after `active` has stayed true for `delayMs`.
 * Used to suppress flicker on loading states that resolve quickly.
 */
export function useDelayedFlag(active: boolean, delayMs = 100): boolean {
  const [shown, setShown] = useState(false);

  useEffect(() => {
    if (!active) {
      setShown(false);
      return;
    }
    const timer = setTimeout(() => setShown(true), delayMs);
    return () => clearTimeout(timer);
  }, [active, delayMs]);

  return shown;
}
