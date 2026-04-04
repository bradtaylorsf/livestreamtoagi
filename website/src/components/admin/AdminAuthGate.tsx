"use client";

import { FormEvent, ReactNode, useCallback, useEffect, useState } from "react";
import { setAdminToken, clearAdminToken } from "@/lib/admin-api";

export default function AdminAuthGate({ children }: { children: ReactNode }) {
  const [authed, setAuthed] = useState(false);
  const [checking, setChecking] = useState(true);
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");

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
      setChecking(false);
      return;
    }
    verify(saved).then((ok) => {
      setAuthed(ok);
      if (!ok) clearAdminToken();
      setChecking(false);
    });
  }, [verify]);

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError("");
    const ok = await verify(password);
    if (ok) {
      setAdminToken(password);
      setAuthed(true);
    } else {
      setError("Invalid password");
    }
  };

  if (checking) {
    return <p className="p-6 text-sm text-foreground/50">Checking auth...</p>;
  }

  if (!authed) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-background">
        <form
          onSubmit={handleSubmit}
          className="w-80 space-y-4 rounded-lg border border-border bg-surface p-6"
        >
          <h2 className="text-sm font-medium text-foreground/70">
            Admin Dashboard
          </h2>
          <input
            type="password"
            placeholder="Password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className="w-full rounded border border-border bg-surface-light px-3 py-2 text-sm text-foreground placeholder:text-foreground/30"
            autoFocus
          />
          {error && (
            <p className="text-xs text-red-400">{error}</p>
          )}
          <button
            type="submit"
            className="w-full rounded bg-neon-cyan/20 py-2 text-sm text-neon-cyan hover:bg-neon-cyan/30 transition-colors"
          >
            Log In
          </button>
        </form>
      </div>
    );
  }

  return <>{children}</>;
}
