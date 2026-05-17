"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import {
  getCurrentSimulationId,
  setCurrentSimulationId,
  useCurrentSimulationId,
} from "@/lib/simulation-store";

export type SimulationContextSource = "route" | "url" | "session" | "none";

export interface SimulationContextValue {
  simulationId: string | null;
  setSimulationId: (id: string | null) => void;
  /** Where the active simulation id was resolved from. */
  source: SimulationContextSource;
  /** True when the URL path itself fixes the simulation (e.g. /simulations/[id]/...). */
  isRouteScoped: boolean;
}

const SimulationContext = createContext<SimulationContextValue | null>(null);

// Sub-paths under /simulations that are list/index pages, not simulation ids.
const SIMULATION_LIST_SENTINELS = new Set(["live", "new", "scenarios"]);

/**
 * Extract a simulation id from a pathname. Returns the segment after
 * `/simulations/` when it looks like an id (non-empty, not a known list-page
 * sentinel like `live`, `new`, `scenarios`); null otherwise.
 *
 * Synchronous: a route-aware caller can use this on the very first render to
 * seed the active simulation id from the URL without waiting for hydration.
 */
export function parseSimIdFromPath(pathname: string | null): string | null {
  if (!pathname) return null;
  const match = pathname.match(/^\/simulations\/([^/]+)/);
  if (!match) return null;
  const id = match[1];
  if (!id || SIMULATION_LIST_SENTINELS.has(id)) return null;
  return id;
}

interface ProviderProps {
  /**
   * The route-scoped simulation id, e.g. from `/simulations/[id]/...`. When
   * present, this takes precedence over the `?sim=` query param and the
   * session-store value. `null` means the route is not scoped to a sim and
   * the provider should fall back to URL → session.
   */
  routeSimulationId?: string | null;
  children: React.ReactNode;
}

/**
 * SimulationProvider resolves the active simulation id with precedence:
 *   1. routeSimulationId prop (from the URL path segment, scoped layout)
 *   2. pathname-derived sim id (root provider on /simulations/[id]/... pages)
 *   3. ?sim= URL search param
 *   4. session-store value (cross-page memory)
 *
 * setSimulationId() updates the session store unconditionally and writes
 * back to the `?sim=` query param when no route-level sim is in play.
 */
export function SimulationProvider({
  routeSimulationId = null,
  children,
}: ProviderProps) {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const simParam = searchParams.get("sim");
  const [sessionSim] = useCurrentSimulationId();

  // Hydration-safe initial value: client renders match server (null) on first
  // pass, then sync once the session store has settled.
  const [hydrated, setHydrated] = useState(false);
  useEffect(() => {
    setHydrated(true);
  }, []);

  const pathSimId = parseSimIdFromPath(pathname);
  const routeOwned = Boolean(routeSimulationId) || Boolean(pathSimId);

  // Keep the cross-page session store in sync with the URL so non-scoped
  // pages reflect the most recently visited simulation.
  useEffect(() => {
    if (pathSimId) {
      setCurrentSimulationId(pathSimId);
    }
  }, [pathSimId]);

  const { simulationId, source } = useMemo<{
    simulationId: string | null;
    source: SimulationContextSource;
  }>(() => {
    if (routeSimulationId) {
      return { simulationId: routeSimulationId, source: "route" };
    }
    if (pathSimId) {
      return { simulationId: pathSimId, source: "route" };
    }
    if (simParam) {
      return { simulationId: simParam, source: "url" };
    }
    if (hydrated && sessionSim) {
      return { simulationId: sessionSim, source: "session" };
    }
    return { simulationId: null, source: "none" };
  }, [routeSimulationId, pathSimId, simParam, sessionSim, hydrated]);

  const setSimulationId = useCallback(
    (id: string | null) => {
      // Always update the session store so other pages see the change.
      setCurrentSimulationId(id);

      // If we're on a route that has its own sim segment, the route owns the
      // value and we leave the URL alone.
      if (routeOwned) return;

      const sp = new URLSearchParams(searchParams.toString());
      if (id) sp.set("sim", id);
      else sp.delete("sim");
      const qs = sp.toString();
      router.replace(qs ? `?${qs}` : "?", { scroll: false });
    },
    [router, searchParams, routeOwned],
  );

  const value: SimulationContextValue = useMemo(
    () => ({
      simulationId,
      setSimulationId,
      source,
      isRouteScoped: routeOwned,
    }),
    [simulationId, setSimulationId, source, routeOwned],
  );

  return (
    <SimulationContext.Provider value={value}>
      {children}
    </SimulationContext.Provider>
  );
}

/**
 * Read the active simulation id from context. Falls back to a stand-alone
 * implementation that reads URL/session directly when no provider is present
 * — this lets components be safely dropped into pages that haven't yet wired
 * up the provider.
 */
export function useSimulation(): SimulationContextValue {
  const ctx = useContext(SimulationContext);
  // Always call the standalone hooks (rules-of-hooks); only use them when
  // the provider isn't present.
  const standalone = useStandaloneSimulation();
  return ctx ?? standalone;
}

function useStandaloneSimulation(): SimulationContextValue {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const simParam = searchParams.get("sim");
  const [sessionSim] = useCurrentSimulationId();

  const [hydrated, setHydrated] = useState(false);
  useEffect(() => {
    setHydrated(true);
  }, []);

  const pathSimId = parseSimIdFromPath(pathname);
  const routeOwned = Boolean(pathSimId);

  useEffect(() => {
    if (pathSimId) {
      setCurrentSimulationId(pathSimId);
    }
  }, [pathSimId]);

  const { simulationId, source } = useMemo<{
    simulationId: string | null;
    source: SimulationContextSource;
  }>(() => {
    if (pathSimId) return { simulationId: pathSimId, source: "route" };
    if (simParam) return { simulationId: simParam, source: "url" };
    if (hydrated && sessionSim) {
      return { simulationId: sessionSim, source: "session" };
    }
    return { simulationId: null, source: "none" };
  }, [pathSimId, simParam, sessionSim, hydrated]);

  const setSimulationId = useCallback(
    (id: string | null) => {
      setCurrentSimulationId(id);
      if (routeOwned) return;
      const sp = new URLSearchParams(searchParams.toString());
      if (id) sp.set("sim", id);
      else sp.delete("sim");
      const qs = sp.toString();
      router.replace(qs ? `?${qs}` : "?", { scroll: false });
    },
    [router, searchParams, routeOwned],
  );

  return { simulationId, setSimulationId, source, isRouteScoped: routeOwned };
}

/**
 * Used by tests and non-React callers to read the current value synchronously.
 * Mirrors the precedence rules without touching React.
 */
export function resolveSimulationId(opts: {
  routeSimulationId?: string | null;
  urlSim?: string | null;
}): { simulationId: string | null; source: SimulationContextSource } {
  if (opts.routeSimulationId) {
    return { simulationId: opts.routeSimulationId, source: "route" };
  }
  if (opts.urlSim) {
    return { simulationId: opts.urlSim, source: "url" };
  }
  const session = getCurrentSimulationId();
  if (session) return { simulationId: session, source: "session" };
  return { simulationId: null, source: "none" };
}
