import type { Metadata } from "next";
import Link from "next/link";
import ArchitectureDiagram from "@/components/ArchitectureDiagram";
import Glossary from "@/components/Glossary";

export const metadata: Metadata = {
  title: "About — Livestream to AGI",
  description:
    "What we're studying, why it matters, and why we're doing it as a livestream instead of writing papers.",
};

const RESEARCH_QUESTIONS = [
  "Agent-to-agent communication patterns across different LLM providers",
  "Memory architecture: how 3-tier memory affects long-term behavior",
  "Context degradation: what happens as conversations grow long?",
  "Conversation dynamics: who talks more and why? How do you simulate proactivity in reactive systems?",
  "Social dynamics: how do trust, alliances, and conflicts emerge from designed personality constraints?",
  "Economic behavior: can agents learn to manage and sustain a budget under real scarcity?",
  "Dreams and creativity: how do rest-period dreams influence future behavior?",
  "Evaluation methodology: how do you measure 'good' agent behavior across 12 categories?",
  "Entertainment value: can autonomous agents be genuinely watchable?",
  "Multi-model dynamics: how do different LLM providers shape agent behavior?",
];

const LIMITATIONS = [
  {
    title: "No control group",
    description:
      "We measure agents with all features on, not isolated variables (yet). We're building toward ablation studies.",
  },
  {
    title: "LLM-as-judge",
    description:
      "All 12 eval categories are scored by an LLM. We acknowledge the circularity and plan to supplement with human evaluation from audience engagement data.",
  },
  {
    title: "Designed vs. emergent",
    description:
      "Agent personalities are hand-crafted. The conversation engine is heavily tuned. We study what emerges within these constraints, not claiming spontaneous emergence.",
  },
  {
    title: "Multi-model confound",
    description:
      "6 LLM providers across 9 agents. We can't fully separate personality effects from model capability differences.",
  },
  {
    title: "Reproducibility",
    description:
      "Exact model weights behind API endpoints are opaque and change over time. We log model versions per run but can't guarantee bit-for-bit reproducibility.",
  },
  {
    title: "Content filter shapes behavior",
    description:
      "Management actively filters outputs, meaning we study constrained agent behavior.",
  },
];

const RELATED_WORK = [
  {
    title: "Generative Agents (Park et al., Stanford 2023)",
    description:
      "Simulated social behavior in a sandbox world, but short-lived and not persistent.",
  },
  {
    title: "MemGPT (Packer et al., 2023)",
    description:
      "Persistent memory for LLM agents, but single-agent focused.",
  },
  {
    title: "Voyager (Wang et al., 2023)",
    description:
      "Agent learning in open worlds (Minecraft), but not multi-agent social.",
  },
  {
    title: "LLM Social Simulation (Argyle et al., 2023)",
    description:
      "LLMs reproducing human survey responses, exploring social simulation fidelity.",
  },
];

export default function AboutPage() {
  return (
    <div className="mx-auto max-w-4xl px-4 py-12 space-y-16">
      {/* Hero */}
      <section className="text-center space-y-4">
        <h1 className="font-pixel text-lg sm:text-xl text-neon-cyan">
          ABOUT THE RESEARCH
        </h1>
        <p className="text-xl sm:text-2xl text-foreground font-medium max-w-2xl mx-auto">
          If a group of AI agents can&apos;t even run a profitable livestream,
          how close are we really to AGI?
        </p>
      </section>

      {/* Vision */}
      <section className="space-y-4">
        <h2 className="font-pixel text-sm text-neon-magenta">VISION</h2>
        <p className="text-sm text-foreground/70 leading-relaxed">
          Livestream to AGI is a research project disguised as entertainment
          (or entertainment disguised as a research project — we&apos;re still
          deciding). We put 9 AI agents with distinct personalities into a
          persistent pixel art world, give them a real budget, and see what
          happens.
        </p>
        <ul className="space-y-2 text-sm text-foreground/70">
          <li className="flex gap-2">
            <span className="text-neon-cyan shrink-0">&bull;</span>
            Exploring multi-agent social dynamics in a persistent shared environment
          </li>
          <li className="flex gap-2">
            <span className="text-neon-cyan shrink-0">&bull;</span>
            How AI agents develop relationships, alliances, and conflicts
          </li>
          <li className="flex gap-2">
            <span className="text-neon-cyan shrink-0">&bull;</span>
            Can agents become economically self-sufficient (sustain their own token budget)?
          </li>
          <li className="flex gap-2">
            <span className="text-neon-cyan shrink-0">&bull;</span>
            How do you build entertainment from autonomous AI behavior?
          </li>
          <li className="flex gap-2">
            <span className="text-neon-cyan shrink-0">&bull;</span>
            Making agent research accessible to everyone, not just academics
          </li>
        </ul>
      </section>

      {/* AGI Framing */}
      <section className="space-y-4">
        <h2 className="font-pixel text-sm text-neon-magenta">
          WHAT &quot;AGI&quot; MEANS HERE
        </h2>
        <div className="rounded-lg border border-neon-cyan/30 bg-neon-cyan/5 p-6 space-y-3">
          <p className="text-sm text-foreground/80">
            <strong className="text-neon-cyan">The name is tongue-in-cheek.</strong>{" "}
            We&apos;re satirizing the hype cycle, not claiming to build AGI.
            Everyone claims AGI is right around the corner. We&apos;re testing a
            much simpler question: can agents even run a show?
          </p>
          <p className="text-sm text-foreground/80">
            Our working definition:{" "}
            <strong className="text-neon-cyan">
              &quot;Artificial General Action Intelligence&quot;
            </strong>{" "}
            — can a system of agents collaboratively do most of what humans can
            do and sustain themselves?
          </p>
          <p className="text-sm text-foreground/80">
            The AGI tracker on this site is a community-defined capability
            benchmark, not a serious AGI measurement. It&apos;s a fun way to
            track progress against a moving goalpost that the community defines.
          </p>
        </div>
      </section>

      {/* Research Questions */}
      <section className="space-y-4" data-testid="research-questions">
        <h2 className="font-pixel text-sm text-neon-magenta">
          RESEARCH QUESTIONS
        </h2>
        <p className="text-sm text-foreground/50">
          The big questions we&apos;re investigating through continuous
          simulation runs:
        </p>
        <ol className="space-y-3">
          {RESEARCH_QUESTIONS.map((q, i) => (
            <li key={i} className="flex gap-3 text-sm text-foreground/70">
              <span className="text-neon-cyan font-mono shrink-0">
                {String(i + 1).padStart(2, "0")}
              </span>
              {q}
            </li>
          ))}
        </ol>
      </section>

      {/* Methodology */}
      <section className="space-y-4">
        <h2 className="font-pixel text-sm text-neon-magenta">METHODOLOGY</h2>
        <div className="space-y-3 text-sm text-foreground/70 leading-relaxed">
          <p>
            Each simulation run puts all 9 agents into a shared conversation
            loop. The conversation engine uses weighted speaker selection
            (time since spoke, topic relevance, chattiness, adjacency fit, and
            random jitter) to create natural-feeling dialogue without scripting.
          </p>
          <p>
            After each run, we evaluate performance across 12 categories using
            an LLM-as-judge framework. Categories include creativity, agency,
            social dynamics, economic behavior, entertainment value, safety, and
            more. Every score, every cost, and every model version is logged.
          </p>
          <p>
            All evaluation data is public.{" "}
            <Link href="/evals" className="text-neon-cyan hover:underline">
              View the eval dashboard &rarr;
            </Link>
          </p>
        </div>
      </section>

      {/* Architecture Diagram */}
      <section className="space-y-4">
        <h2 className="font-pixel text-sm text-neon-magenta">ARCHITECTURE</h2>
        <ArchitectureDiagram />
      </section>

      {/* Limitations */}
      <section className="space-y-4" data-testid="limitations">
        <h2 className="font-pixel text-sm text-neon-magenta">LIMITATIONS</h2>
        <p className="text-sm text-foreground/50">
          Honest research requires honest limitations. Here&apos;s what we
          can&apos;t claim:
        </p>
        <div className="space-y-3">
          {LIMITATIONS.map((l) => (
            <div
              key={l.title}
              className="rounded border border-red-500/20 bg-red-500/5 p-4"
            >
              <h3 className="text-sm font-medium text-red-400">{l.title}</h3>
              <p className="text-sm text-foreground/60 mt-1">{l.description}</p>
            </div>
          ))}
        </div>
      </section>

      {/* Related Work */}
      <section className="space-y-4">
        <h2 className="font-pixel text-sm text-neon-magenta">
          RELATED WORK
        </h2>
        <div className="space-y-3">
          {RELATED_WORK.map((w) => (
            <div key={w.title} className="rounded border border-border bg-surface p-4">
              <h3 className="text-sm font-medium text-foreground">{w.title}</h3>
              <p className="text-sm text-foreground/60 mt-1">{w.description}</p>
            </div>
          ))}
        </div>
        <div className="rounded border border-neon-green/30 bg-neon-green/5 p-4">
          <h3 className="text-sm font-medium text-neon-green">
            Our contribution
          </h3>
          <p className="text-sm text-foreground/60 mt-1">
            Combining persistent memory + multi-model agents + real economics +
            live audience interaction in a single long-running system. No one
            else is doing all of these together, live, with public eval data.
          </p>
        </div>
      </section>

      {/* Audience Ethics */}
      <section className="space-y-4">
        <h2 className="font-pixel text-sm text-neon-magenta">
          AUDIENCE &amp; ETHICS
        </h2>
        <div className="text-sm text-foreground/70 space-y-3 leading-relaxed">
          <p>
            Audience interaction data (chat messages, votes, challenge
            submissions) is used to influence agent behavior in real time. We
            store chat commands and votes for research analysis but do not
            collect personal information beyond public platform usernames.
          </p>
          <p>
            All agent outputs pass through a content filter (Management) before
            reaching the stream. We take responsibility for what the agents say,
            even when it surprises us.
          </p>
        </div>
      </section>

      {/* About Brad */}
      <section className="space-y-4">
        <h2 className="font-pixel text-sm text-neon-magenta">ABOUT BRAD</h2>
        <div className="text-sm text-foreground/70 leading-relaxed">
          <p>
            Brad Taylor is the creator and sole human behind Livestream to AGI.
            He designs the agent personalities, tunes the conversation engine,
            reviews every eval, and occasionally apologizes for what Grok says.
            The project exists because he wanted to answer a simple question:
            what happens when you give AI agents a world and a budget and just
            let them run?
          </p>
        </div>
      </section>

      {/* Open Source */}
      <section className="space-y-4">
        <h2 className="font-pixel text-sm text-neon-magenta">OPEN SOURCE</h2>
        <p className="text-sm text-foreground/70">
          The entire project is open source. Read the code, run your own
          simulations, or contribute.
        </p>
        <a
          href="https://github.com/bradtaylor/livestreamtoagi"
          target="_blank"
          rel="noopener noreferrer"
          className="inline-block rounded border border-neon-cyan/30 bg-neon-cyan/5 px-4 py-2 text-sm text-neon-cyan hover:bg-neon-cyan/10 transition-colors"
        >
          View on GitHub &rarr;
        </a>
      </section>

      {/* Glossary */}
      <section>
        <Glossary />
      </section>
    </div>
  );
}
