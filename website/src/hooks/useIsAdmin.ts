"use client";

import { useCallback, useEffect, useState } from "react";

/**
 * Checks whether the current user has admin credentials stored in
 * localStorage and verifies them against the admin API.
 *
 * Returns { isAdmin, loading } so components can conditionally render
 * admin-only actions without wrapping in AdminAuthGate.
 */
export function useIsAdmin(): { isAdmin: boolean; loading: boolean } {
  const [isAdmin, setIsAdmin] = useState(false);
  const [loading, setLoading] = useState(true);

  const verify = useCallback(async (token: string) => {
    try {
      const res = await fetch("/api/admin/agents", {
        headers: { Authorization: `Bearer ${token}` },
      });
      return res.ok;
    } catch {
      return false;
    }
  }, []);

  useEffect(() => {
    const saved = localStorage.getItem("admin_password") ?? "";
    if (!saved) {
      setLoading(false);
      return;
    }
    verify(saved).then((ok) => {
      setIsAdmin(ok);
      setLoading(false);
    });
  }, [verify]);

  return { isAdmin, loading };
}
