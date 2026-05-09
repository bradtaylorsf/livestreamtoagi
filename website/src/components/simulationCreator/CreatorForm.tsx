"use client";

import { useEffect, useMemo, useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import {
  ApiRequestError,
  getPublicScenarios,
  submitPublicSimulation,
  type PublicScenarioMeta,
} from "@/lib/api";
import { useCurrentUser } from "@/lib/auth";
import { remainingBudget, validateForm } from "./validation";
import {
  buildSubmitPayload,
  DEFAULT_LIFETIME_CAP_USD,
  DEFAULT_MAX_COST_USD,
  initialState,
  reseedForScenario,
  toggleAgent,
  activeAgents as activeAgentsOf,
  type CreatorFormState,
} from "./state";
import {
  clearCreatorDraft,
  loadCreatorDraft,
  saveCreatorDraft,
} from "./draftStorage";
import ScenarioField from "./ScenarioField";
import AgentsField from "./AgentsField";
import FactionsField from "./FactionsField";
import MemorySeedField from "./MemorySeedField";
import EnergyConfigField from "./EnergyConfigField";
import SignInOverlay from "./SignInOverlay";

interface CreatorFormProps {
  initialScenario: string | null;
}

export default function CreatorForm({ initialScenario }: CreatorFormProps) {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const { user, loading: userLoading, refresh: refreshUser } = useCurrentUser();
  const [scenarios, setScenarios] = useState<PublicScenarioMeta[] | null>(null);
  const [scenarioError, setScenarioError] = useState<string | null>(null);
  const [state, setState] = useState<CreatorFormState | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [showSignIn, setShowSignIn] = useState(false);

  const budget = useMemo(
    () => remainingBudget(user, DEFAULT_LIFETIME_CAP_USD),
    [user],
  );
  const returnTo = useMemo(() => {
    const search = searchParams.toString();
    return `${pathname}${search ? `?${search}` : ""}`;
  }, [pathname, searchParams]);

  useEffect(() => {
    let cancelled = false;
    getPublicScenarios()
      .then((data) => {
        if (cancelled) return;
        setScenarios(data);
      })
      .catch((err) => {
        if (cancelled) return;
        setScenarioError(
          err instanceof Error ? err.message : "Failed to load scenarios",
        );
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (scenarios === null) return;
    setState((prev) => {
      if (prev) {
        return { ...prev, remaining_budget: budget };
      }
      return loadCreatorDraft({
        scenarios,
        remainingBudget: budget,
      }) ?? initialState({
        scenarios,
        initialScenarioId: initialScenario,
        remainingBudget: budget,
      });
    });
  }, [scenarios, initialScenario, budget]);

  useEffect(() => {
    if (!state) return;
    if (validateForm(state).ok) {
      saveCreatorDraft(state);
    }
  }, [state]);

  if (scenarioError) {
    return (
      <div className="rounded border border-red-500/40 bg-red-500/10 p-4 text-red-400">
        {scenarioError}
      </div>
    );
  }
  if (scenarios === null || state === null) {
    return (
      <p className="text-sm text-foreground/50" data-testid="creator-form-loading">
        Loading…
      </p>
    );
  }

  const activeAgents = activeAgentsOf(state);

  function changeScenario(filename: string) {
    const next = scenarios!.find((s) => s.filename === filename);
    if (!next) return;
    setState((prev) => (prev ? reseedForScenario(prev, next) : prev));
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!state) return;
    setSubmitError(null);
    const result = validateForm(state);
    if (!result.ok) {
      setSubmitError(result.error ?? "Form is invalid");
      return;
    }
    saveCreatorDraft(state);
    if (!user) {
      setShowSignIn(true);
      return;
    }
    setSubmitting(true);
    try {
      const payload = buildSubmitPayload(state);
      const res = await submitPublicSimulation(payload);
      clearCreatorDraft();
      router.push(`/simulations/${res.simulation_id}?queued=1`);
    } catch (err) {
      if (err instanceof ApiRequestError && err.status === 401) {
        setShowSignIn(true);
      } else {
        setSubmitError(
          err instanceof Error ? err.message : "Failed to submit simulation",
        );
      }
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <>
      <form
        onSubmit={handleSubmit}
        className="space-y-6"
        data-testid="creator-form"
        noValidate
      >
        <ScenarioField
          scenarios={scenarios}
          value={state.scenario_id}
          onChange={changeScenario}
        />

        <fieldset className="space-y-3">
          <legend className="font-pixel text-xs text-neon-cyan">
            NAME &amp; HYPOTHESIS
          </legend>
          <label className="block">
            <span className="block text-xs text-foreground/70 mb-1">Name</span>
            <input
              type="text"
              value={state.name}
              onChange={(e) =>
                setState((s) => (s ? { ...s, name: e.target.value } : s))
              }
              placeholder="My simulation"
              maxLength={100}
              required
              className="w-full rounded border border-border bg-background px-3 py-2 text-sm text-foreground"
              data-testid="creator-name"
            />
          </label>
          <label className="block">
            <span className="block text-xs text-foreground/70 mb-1">
              Hypothesis (optional but encouraged)
            </span>
            <textarea
              value={state.hypothesis}
              onChange={(e) =>
                setState((s) => (s ? { ...s, hypothesis: e.target.value } : s))
              }
              rows={3}
              placeholder="e.g., Rex and Aurora will form an alliance against Fork's contrarian streak"
              maxLength={2000}
              className="w-full rounded border border-border bg-background px-3 py-2 text-sm text-foreground"
              data-testid="creator-hypothesis"
            />
            <span className="text-[10px] text-foreground/40">
              {state.hypothesis.length}/2000
            </span>
          </label>
        </fieldset>

        <AgentsField
          scenarioAgents={state.scenario_agents}
          excludedAgents={state.excluded_agents}
          onToggle={(a) =>
            setState((s) => (s ? toggleAgent(s, a) : s))
          }
        />

        <FactionsField
          factions={state.factions}
          activeAgents={activeAgents}
          onChange={(factions) =>
            setState((s) => (s ? { ...s, factions } : s))
          }
        />

        <MemorySeedField
          value={state.memory_seed}
          rawJson={state.memory_seed_raw_json}
          onChange={(memory_seed, raw) =>
            setState((s) =>
              s
                ? {
                    ...s,
                    memory_seed,
                    memory_seed_raw_json: raw,
                  }
                : s,
            )
          }
        />

        <EnergyConfigField
          maxCost={state.max_cost}
          onMaxCost={(n) => setState((s) => (s ? { ...s, max_cost: n } : s))}
          cadence={state.conversation_cadence}
          onCadence={(n) =>
            setState((s) => (s ? { ...s, conversation_cadence: n } : s))
          }
          energy={state.energy}
          onEnergy={(agent, value) =>
            setState((s) =>
              s ? { ...s, energy: { ...s.energy, [agent]: value } } : s,
            )
          }
          activeAgents={activeAgents}
          perSubmissionCap={DEFAULT_MAX_COST_USD}
          remainingBudget={budget}
        />

        <fieldset className="space-y-2">
          <legend className="font-pixel text-xs text-neon-cyan">PUBLISH</legend>
          <label className="flex items-center gap-2 text-sm text-foreground/80">
            <input
              type="checkbox"
              checked={state.publish_to_youtube}
              onChange={(e) =>
                setState((s) =>
                  s ? { ...s, publish_to_youtube: e.target.checked } : s,
                )
              }
              data-testid="creator-publish-youtube"
              className="rounded border-border"
            />
            <span>Publish summary video to YouTube when complete</span>
          </label>
        </fieldset>

        {submitError && (
          <div
            className="rounded border border-red-500/40 bg-red-500/10 p-3 text-sm text-red-400"
            data-testid="creator-error"
            role="alert"
          >
            {submitError}
          </div>
        )}

        <div className="flex flex-wrap items-center justify-between gap-3 border-t border-border pt-4">
          <p className="text-xs text-foreground/60" data-testid="creator-cost-estimate">
            {user
              ? `≈ $${state.max_cost.toFixed(2)} max · $${(budget ?? 0).toFixed(2)} remaining of $${DEFAULT_LIFETIME_CAP_USD.toFixed(2)} lifetime budget`
              : userLoading
                ? "Checking session…"
                : "Sign in to attach this run to your budget."}
          </p>
          <button
            type="submit"
            disabled={submitting}
            className="rounded bg-neon-cyan text-background font-pixel text-sm px-6 py-3 shadow hover:bg-neon-cyan/90 transition-colors disabled:opacity-60 disabled:cursor-not-allowed"
            data-testid="creator-submit"
          >
            {submitting ? "Submitting…" : "Run simulation"}
          </button>
        </div>
      </form>

      {showSignIn && (
        <SignInOverlay
          returnTo={returnTo}
          onClose={() => {
            setShowSignIn(false);
            // After magic-link click + cookie set, the user can submit again;
            // refresh /me so the form recognises them without a reload.
            refreshUser();
          }}
        />
      )}
    </>
  );
}
