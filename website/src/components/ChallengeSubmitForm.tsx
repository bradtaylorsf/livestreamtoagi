"use client";

import { useState } from "react";
import type { Challenge } from "@/types";
import { submitChallenge } from "@/lib/api";

const CATEGORY_OPTIONS = [
  { value: "", label: "Select a category" },
  { value: "building", label: "Building" },
  { value: "creative", label: "Creative" },
  { value: "social", label: "Social" },
  { value: "technical", label: "Technical" },
  { value: "other", label: "Other" },
];

interface ChallengeSubmitFormProps {
  onSubmitted: (challenge: Challenge) => void;
}

export default function ChallengeSubmitForm({
  onSubmitted,
}: ChallengeSubmitFormProps) {
  const [description, setDescription] = useState("");
  const [category, setCategory] = useState("");
  const [submitterName, setSubmitterName] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!description.trim()) return;

    setSubmitting(true);
    setError(null);
    setSuccess(false);

    try {
      const challenge = await submitChallenge({
        description: description.trim(),
        category: category || undefined,
        submitter_name: submitterName.trim() || undefined,
      });
      onSubmitted(challenge);
      setDescription("");
      setCategory("");
      setSubmitterName("");
      setSuccess(true);
      setTimeout(() => setSuccess(false), 3000);
    } catch (err) {
      if (err instanceof Error && err.message.includes("429")) {
        setError("Rate limit reached. Try again in a bit (max 5/hr).");
      } else {
        setError("Failed to submit challenge. Please try again.");
      }
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form
      onSubmit={handleSubmit}
      className="rounded border border-border bg-surface p-4 space-y-4"
    >
      <h3 className="font-pixel text-xs text-neon-magenta">SUBMIT A CHALLENGE</h3>

      <div>
        <label
          htmlFor="challenge-description"
          className="block text-xs text-foreground/60 mb-1"
        >
          What should the agents work on?
        </label>
        <textarea
          id="challenge-description"
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          placeholder="Describe your challenge..."
          rows={3}
          maxLength={500}
          required
          className="w-full rounded border border-border bg-background px-3 py-2 text-sm text-foreground placeholder:text-foreground/30 focus:border-neon-cyan focus:outline-none"
        />
      </div>

      <div className="flex gap-3">
        <div className="flex-1">
          <label
            htmlFor="challenge-category"
            className="block text-xs text-foreground/60 mb-1"
          >
            Category
          </label>
          <select
            id="challenge-category"
            value={category}
            onChange={(e) => setCategory(e.target.value)}
            className="w-full rounded border border-border bg-background px-3 py-2 text-sm text-foreground"
          >
            {CATEGORY_OPTIONS.map((opt) => (
              <option key={opt.value} value={opt.value}>
                {opt.label}
              </option>
            ))}
          </select>
        </div>
        <div className="flex-1">
          <label
            htmlFor="challenge-submitter"
            className="block text-xs text-foreground/60 mb-1"
          >
            Your name (optional)
          </label>
          <input
            id="challenge-submitter"
            type="text"
            value={submitterName}
            onChange={(e) => setSubmitterName(e.target.value)}
            placeholder="Anonymous"
            maxLength={100}
            className="w-full rounded border border-border bg-background px-3 py-2 text-sm text-foreground placeholder:text-foreground/30 focus:border-neon-cyan focus:outline-none"
          />
        </div>
      </div>

      {error && (
        <p className="text-xs text-red-400">{error}</p>
      )}
      {success && (
        <p className="text-xs text-green-400">Challenge submitted!</p>
      )}

      <button
        type="submit"
        disabled={submitting || !description.trim()}
        className="rounded bg-neon-cyan/20 border border-neon-cyan px-4 py-2 text-sm text-neon-cyan hover:bg-neon-cyan/30 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
      >
        {submitting ? "Submitting..." : "Submit Challenge"}
      </button>
    </form>
  );
}
