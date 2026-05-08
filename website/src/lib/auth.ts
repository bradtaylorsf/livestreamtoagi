"use client";

import { useCallback, useEffect, useState } from "react";
import { getCurrentUser, type CurrentUser } from "@/lib/api";

export interface UseCurrentUserResult {
  user: CurrentUser | null;
  loading: boolean;
  error: string | null;
  refresh: () => Promise<void>;
}

export function useCurrentUser(): UseCurrentUserResult {
  const [user, setUser] = useState<CurrentUser | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const me = await getCurrentUser();
      setUser(me);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load session");
      setUser(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const me = await getCurrentUser();
        if (cancelled) return;
        setUser(me);
        setError(null);
      } catch (err) {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : "Failed to load session");
        setUser(null);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  return { user, loading, error, refresh };
}
