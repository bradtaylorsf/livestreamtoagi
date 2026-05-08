"use client";

import { useState } from "react";
import { requestMagicLink } from "@/lib/api";

interface SignInOverlayProps {
  onClose: () => void;
}

export default function SignInOverlay({ onClose }: SignInOverlayProps) {
  const [email, setEmail] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [sent, setSent] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!email.trim()) return;
    setSubmitting(true);
    setError(null);
    try {
      await requestMagicLink(email.trim());
      setSent(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to send magic link");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 px-4"
      data-testid="sign-in-overlay"
      role="dialog"
      aria-modal="true"
      aria-labelledby="sign-in-overlay-title"
    >
      <div className="w-full max-w-md rounded-lg border border-border bg-surface p-6 space-y-4">
        <div>
          <h2
            id="sign-in-overlay-title"
            className="font-pixel text-sm text-neon-cyan"
          >
            SIGN IN TO RUN
          </h2>
          <p className="mt-2 text-xs text-foreground/60">
            We&apos;ll email you a one-click sign-in link. No password — just
            so we can attach this run to your budget.
          </p>
        </div>
        {sent ? (
          <div
            className="rounded border border-neon-green/40 bg-neon-green/10 p-3 text-xs text-neon-green"
            data-testid="sign-in-overlay-sent"
          >
            Check your email for a sign-in link. Once you click it, come back
            here and submit again — your form is preserved.
          </div>
        ) : (
          <form onSubmit={handleSubmit} className="space-y-3">
            <label className="block">
              <span className="block text-xs font-medium text-foreground/70 mb-1">
                Email
              </span>
              <input
                type="email"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="you@example.com"
                className="w-full rounded border border-border bg-background px-3 py-2 text-sm text-foreground"
                data-testid="sign-in-overlay-email"
              />
            </label>
            {error && (
              <div className="rounded border border-red-500/40 bg-red-500/10 px-3 py-2 text-xs text-red-400">
                {error}
              </div>
            )}
            <div className="flex justify-end gap-2 pt-1">
              <button
                type="button"
                onClick={onClose}
                disabled={submitting}
                className="rounded border border-border px-3 py-1.5 text-xs text-foreground/60 hover:bg-surface-light transition-colors disabled:opacity-50"
              >
                Cancel
              </button>
              <button
                type="submit"
                disabled={submitting || !email.trim()}
                className="rounded border border-neon-cyan/40 bg-neon-cyan/10 px-3 py-1.5 text-xs font-medium text-neon-cyan hover:bg-neon-cyan/20 transition-colors disabled:opacity-50"
                data-testid="sign-in-overlay-send"
              >
                {submitting ? "Sending…" : "Send link"}
              </button>
            </div>
          </form>
        )}
      </div>
    </div>
  );
}
