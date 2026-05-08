"use client";

import { useEffect, useState } from "react";

const STORAGE_KEY = "currentSimulationId";

type Listener = (id: string | null) => void;

let memoryValue: string | null = null;
let hydrated = false;
const listeners = new Set<Listener>();

function readFromStorage(): string | null {
  if (typeof window === "undefined") return null;
  try {
    return window.sessionStorage.getItem(STORAGE_KEY);
  } catch {
    return null;
  }
}

function writeToStorage(id: string | null): void {
  if (typeof window === "undefined") return;
  try {
    if (id) {
      window.sessionStorage.setItem(STORAGE_KEY, id);
    } else {
      window.sessionStorage.removeItem(STORAGE_KEY);
    }
  } catch {
    // sessionStorage unavailable (private mode, etc.) — keep in-memory only
  }
}

function ensureHydrated(): void {
  if (hydrated) return;
  hydrated = true;
  memoryValue = readFromStorage();
}

export function getCurrentSimulationId(): string | null {
  ensureHydrated();
  return memoryValue;
}

export function setCurrentSimulationId(id: string | null): void {
  ensureHydrated();
  if (memoryValue === id) return;
  memoryValue = id;
  writeToStorage(id);
  for (const listener of listeners) {
    listener(id);
  }
}

export function useCurrentSimulationId(): [
  string | null,
  (id: string | null) => void,
] {
  const [value, setValue] = useState<string | null>(() =>
    typeof window === "undefined" ? null : getCurrentSimulationId(),
  );

  useEffect(() => {
    setValue(getCurrentSimulationId());
    const listener: Listener = (id) => setValue(id);
    listeners.add(listener);
    return () => {
      listeners.delete(listener);
    };
  }, []);

  return [value, setCurrentSimulationId];
}
