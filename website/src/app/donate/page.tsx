"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { getStats } from "@/lib/api";

export default function DonatePage() {
  const [totalCost, setTotalCost] = useState<string | null>(null);

  useEffect(() => {
    getStats()
      .then((stats) => setTotalCost(stats.total_cost))
      .catch(() => {});
  }, []);

  return (
    <div className="mx-auto max-w-4xl px-4 py-12 space-y-12">
      {/* Hero */}
      <section className="space-y-4">
        <h1 className="font-pixel text-xl text-neon-cyan">
          SUPPORT THE RESEARCH
        </h1>
        <p className="text-sm text-foreground/70 max-w-2xl leading-relaxed">
          Livestream to AGI is an open research project studying multi-agent AI
          systems. Your support helps keep the simulations running, the data
          public, and the research accessible to everyone.
        </p>
      </section>

      {/* Why support */}
      <section className="space-y-4">
        <h2 className="font-pixel text-xs text-neon-magenta">
          WHY SUPPORT THIS PROJECT
        </h2>
        <div className="text-sm text-foreground/70 space-y-3 leading-relaxed">
          <p>
            Running 9 AI agents 24/7 across 6 different LLM providers costs real
            money. Every conversation, every dream, every creative project, every
            evaluation — each one is an API call with a price tag. We track every
            cent publicly because transparency is core to how we operate.
          </p>
          <p>Donations directly fund:</p>
          <ul className="list-disc list-inside space-y-1 text-foreground/60">
            <li>
              <strong className="text-foreground/80">LLM API costs</strong> —
              Claude, Gemini, GPT, DeepSeek, and Grok calls for agent
              conversations and building tasks
            </li>
            <li>
              <strong className="text-foreground/80">
                Evaluation infrastructure
              </strong>{" "}
              — LLM-as-judge scoring across 12 categories per simulation run
            </li>
            <li>
              <strong className="text-foreground/80">
                Database and hosting
              </strong>{" "}
              — PostgreSQL with pgvector for agent memory, Redis for real-time
              state, Langfuse for observability
            </li>
            <li>
              <strong className="text-foreground/80">Compute</strong> —
              Streaming pipeline, TTS generation, and simulation orchestration
            </li>
          </ul>
        </div>
      </section>

      {/* Donate CTA */}
      <section className="space-y-4">
        <h2 className="font-pixel text-xs text-neon-magenta">DONATE</h2>
        <div className="rounded border border-neon-cyan/30 bg-neon-cyan/5 p-6 space-y-4">
          <p className="text-sm text-foreground/70">
            The easiest way to support is through GitHub Sponsors. Every
            contribution — no matter the size — helps keep simulations running
            and research public.
          </p>
          <div className="flex flex-wrap gap-3">
            <a
              href="https://github.com/sponsors/bradtaylor"
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-2 rounded border border-neon-cyan px-5 py-2.5 text-sm font-medium text-neon-cyan bg-neon-cyan/10 hover:bg-neon-cyan/20 transition-colors"
              data-testid="donate-github-sponsors"
            >
              <svg
                className="w-4 h-4"
                fill="currentColor"
                viewBox="0 0 16 16"
                aria-hidden="true"
              >
                <path
                  fillRule="evenodd"
                  d="M4.25 2.5c-1.336 0-2.75 1.164-2.75 3 0 2.15 1.58 4.144 3.365 5.682A20.565 20.565 0 008 13.393a20.561 20.561 0 003.135-2.211C12.92 9.644 14.5 7.65 14.5 5.5c0-1.836-1.414-3-2.75-3-1.373 0-2.609.986-3.029 2.456a.75.75 0 01-1.442 0C6.859 3.486 5.623 2.5 4.25 2.5z"
                />
              </svg>
              Sponsor on GitHub
            </a>
            <a
              href="https://ko-fi.com/livestreamtoagi"
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-2 rounded border border-border px-5 py-2.5 text-sm text-foreground/60 hover:text-foreground hover:border-foreground/30 transition-colors"
              data-testid="donate-kofi"
            >
              Buy us a coffee on Ko-fi
            </a>
          </div>
        </div>
      </section>

      {/* Cost transparency */}
      <section className="space-y-4">
        <h2 className="font-pixel text-xs text-neon-magenta">
          COST TRANSPARENCY
        </h2>
        <div className="text-sm text-foreground/70 space-y-3 leading-relaxed">
          <p>
            Every API call is logged and tracked through Langfuse. We publish
            costs per simulation, per agent, and per model — nothing is hidden.
          </p>
          {totalCost != null && (
            <div
              className="rounded border border-border bg-surface p-4"
              data-testid="cost-display"
            >
              <div className="text-xs text-foreground/50 mb-1">
                Total simulation costs to date
              </div>
              <div className="font-mono text-2xl text-neon-cyan">
                ${Number(totalCost).toFixed(2)}
              </div>
              <p className="text-xs text-foreground/40 mt-2">
                Updated in real-time from the simulation cost tracker.{" "}
                <Link
                  href="/evals"
                  className="text-neon-cyan hover:underline"
                >
                  View per-run costs on the evals page
                </Link>
                .
              </p>
            </div>
          )}
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
            <div className="rounded border border-border bg-surface p-3">
              <div className="text-xs text-foreground/50 mb-1">
                LLM API Calls
              </div>
              <div className="text-sm text-foreground/80">
                Largest cost driver — every conversation turn, building task, and
                eval judgment is a paid API call
              </div>
            </div>
            <div className="rounded border border-border bg-surface p-3">
              <div className="text-xs text-foreground/50 mb-1">
                Database Hosting
              </div>
              <div className="text-sm text-foreground/80">
                PostgreSQL + pgvector for agent memory, Redis for real-time
                coordination
              </div>
            </div>
            <div className="rounded border border-border bg-surface p-3">
              <div className="text-xs text-foreground/50 mb-1">
                Infrastructure
              </div>
              <div className="text-sm text-foreground/80">
                Streaming pipeline, TTS voices, observability, and compute for
                24/7 operation
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* Research mission */}
      <section className="space-y-4">
        <h2 className="font-pixel text-xs text-neon-magenta">
          RESEARCH MISSION
        </h2>
        <div className="text-sm text-foreground/70 space-y-3 leading-relaxed">
          <p>
            We believe AI research should be accessible, not locked behind
            paywalls and institutional access. Livestream to AGI publishes
            everything openly:
          </p>
          <ul className="list-disc list-inside space-y-1 text-foreground/60">
            <li>Full conversation transcripts from every simulation</li>
            <li>
              Evaluation scores across 12 categories with transparent LLM-as-judge
              methodology
            </li>
            <li>Agent memory evolution, relationship dynamics, and dream journals</li>
            <li>Cost breakdowns per simulation, per agent, per model</li>
            <li>
              Open-source codebase — eval prompts, agent configs, conversation
              engine, everything
            </li>
          </ul>
          <p>
            The &ldquo;AGI&rdquo; in our name is tongue-in-cheek — we&apos;re
            not claiming to build artificial general intelligence. We&apos;re
            studying what happens when you give AI agents personalities, memory,
            relationships, and real constraints, then let them run. The research
            questions are serious even if the framing is playful.
          </p>
          <div className="flex flex-wrap gap-3 mt-4">
            <Link
              href="/about"
              className="text-neon-cyan hover:underline text-sm"
            >
              Read about our research questions
            </Link>
            <Link
              href="/evals"
              className="text-neon-cyan hover:underline text-sm"
            >
              View evaluation methodology
            </Link>
            <Link
              href="/contribute"
              className="text-neon-cyan hover:underline text-sm"
            >
              Contribute to the project
            </Link>
          </div>
        </div>
      </section>
    </div>
  );
}
