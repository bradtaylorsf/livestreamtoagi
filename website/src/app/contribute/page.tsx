import type { Metadata } from "next";
import Link from "next/link";

export const metadata: Metadata = {
  title: "Contribute — Livestream to AGI",
  description:
    "How to contribute to Livestream to AGI — code, prompts, agent skills, evals, world building, and content. All contributions are validated empirically through eval scores.",
};

const CONTRIBUTION_TYPES = [
  {
    title: "Code Contributions",
    description:
      "Backend features, frontend improvements, infrastructure, and tooling. Python (FastAPI, CrewAI) and TypeScript (Next.js, Phaser.js).",
  },
  {
    title: "Prompt Engineering",
    description:
      "Agent system prompts, conversation engine tuning, speaker selection weights, and personality refinement.",
  },
  {
    title: "Agent Skills",
    description:
      "New tools agents can use — code execution, world manipulation, social interactions, economic actions.",
  },
  {
    title: "Eval Improvements",
    description:
      "New eval categories, better rubrics, human evaluation integration, scoring methodology refinements.",
  },
  {
    title: "World Building",
    description:
      "New world chunks, tilesets, furniture, room layouts, and pixel art assets for the shared office environment.",
  },
  {
    title: "Content",
    description:
      "Blog posts, documentation, tutorials, research writeups, and community guides.",
  },
];

const VALIDATION_STEPS = [
  "Fork the repo and make your change",
  "Run the eval suite against a simulation with your change",
  "Submit a PR with before/after eval scores",
  "Maintainers verify the improvement by re-running the simulation independently",
  "Changes that degrade scores are rejected with data, not opinion",
];

const AB_TESTING_STEPS = [
  {
    step: "1",
    title: "Run baseline simulation",
    description: "Run a simulation without your change to establish baseline scores.",
    command: "pnpm sim",
  },
  {
    step: "2",
    title: "Run treatment simulation",
    description: "Run a simulation with your change applied.",
    command: "pnpm sim",
  },
  {
    step: "3",
    title: "Compare scores",
    description: "Use the comparison script to generate a diff of eval scores.",
    command: "scripts/run_evolution.py --compare BASELINE_ID TREATMENT_ID",
  },
  {
    step: "4",
    title: "Include comparison in PR",
    description:
      "Paste the comparison output into your PR description so reviewers can see the impact.",
  },
  {
    step: "5",
    title: "Repeat 3x for confidence",
    description:
      "LLM outputs are non-deterministic. Run at least 3 baseline/treatment pairs to establish statistical confidence.",
  },
];

const GETTING_STARTED_STEPS = [
  {
    title: "Set up the dev environment",
    items: [
      "Clone the repo and install Python 3.13+ and Node.js",
      "Run `docker compose up -d` to start PostgreSQL, Redis, and Langfuse",
      "Run `bash scripts/check-services.sh` to verify all 5 services are healthy",
      "Set up Python: `uv venv .venv --python 3.13 && uv pip install -e \".[dev]\"`",
      "Set up website: `cd website && npm install`",
    ],
  },
  {
    title: "Run a simulation locally",
    items: [
      "Copy `.env.example` to `.env` and fill in API keys",
      "Run `pnpm sim` to start a local simulation",
      "Watch agent conversations unfold in the terminal",
    ],
  },
  {
    title: "Run evals and interpret scores",
    items: [
      "After a simulation completes, evals run automatically across 12 categories",
      "Scores range from 0-10 across categories like creativity, agency, social dynamics, safety",
      "Higher scores = better agent behavior in that category",
    ],
  },
  {
    title: "Read the eval dashboard",
    items: [
      "Visit the eval dashboard to see current scores and trends",
      "Identify categories with low scores — these are the best areas to improve",
      "Look at score history to understand which changes had the biggest impact",
    ],
  },
];

const HELP_WANTED = [
  {
    label: "Good First Issues",
    url: "https://github.com/bradtaylor/livestreamtoagi/labels/good%20first%20issue",
    description: "Scoped, well-defined tasks for new contributors",
  },
  {
    label: "Help Wanted",
    url: "https://github.com/bradtaylor/livestreamtoagi/labels/help%20wanted",
    description: "Larger tasks where community help would be valuable",
  },
  {
    label: "Eval Improvements",
    url: "https://github.com/bradtaylor/livestreamtoagi/labels/eval",
    description: "Tasks related to improving evaluation methodology and scores",
  },
];

export default function ContributePage() {
  return (
    <div className="mx-auto max-w-4xl px-4 py-12 space-y-16">
      {/* Hero */}
      <section className="text-center space-y-4" data-testid="contribute-hero">
        <h1 className="font-pixel text-lg sm:text-xl text-neon-cyan">
          CONTRIBUTE
        </h1>
        <p className="text-xl sm:text-2xl text-foreground font-medium max-w-2xl mx-auto">
          Changes are validated empirically, not by opinion. Show us the eval
          scores.
        </p>
        <p className="text-sm text-foreground/60 max-w-xl mx-auto">
          Every contribution to this project must prove it improves simulation
          performance or eval scores before merging. This is core to our
          research methodology.
        </p>
      </section>

      {/* What You Can Contribute */}
      <section className="space-y-4" data-testid="contribution-types">
        <h2 className="font-pixel text-sm text-neon-magenta">
          WHAT YOU CAN CONTRIBUTE
        </h2>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          {CONTRIBUTION_TYPES.map((type) => (
            <div
              key={type.title}
              className="rounded border border-border bg-surface p-4"
            >
              <h3 className="text-sm font-medium text-foreground">
                {type.title}
              </h3>
              <p className="text-xs text-foreground/60 mt-1">
                {type.description}
              </p>
            </div>
          ))}
        </div>
      </section>

      {/* How Contributions Are Validated */}
      <section className="space-y-4" data-testid="validation-process">
        <h2 className="font-pixel text-sm text-neon-magenta">
          HOW CONTRIBUTIONS ARE VALIDATED
        </h2>
        <p className="text-sm text-foreground/70">
          We don&apos;t merge based on code review alone. Every change that
          affects agent behavior must demonstrate measurable improvement:
        </p>
        <ol className="space-y-3">
          {VALIDATION_STEPS.map((step, i) => (
            <li key={i} className="flex gap-3 text-sm text-foreground/70">
              <span className="text-neon-cyan font-mono shrink-0">
                {String(i + 1).padStart(2, "0")}
              </span>
              {step}
            </li>
          ))}
        </ol>
      </section>

      {/* A/B Testing Protocol */}
      <section className="space-y-4" data-testid="ab-testing-protocol">
        <h2 className="font-pixel text-sm text-neon-magenta">
          A/B TESTING PROTOCOL
        </h2>
        <p className="text-sm text-foreground/70">
          The step-by-step process for proving your change works:
        </p>
        <div className="space-y-4">
          {AB_TESTING_STEPS.map((step) => (
            <div
              key={step.step}
              className="rounded border border-border bg-surface p-4"
            >
              <div className="flex items-start gap-3">
                <span className="text-neon-cyan font-mono text-sm shrink-0">
                  {step.step}.
                </span>
                <div>
                  <h3 className="text-sm font-medium text-foreground">
                    {step.title}
                  </h3>
                  <p className="text-xs text-foreground/60 mt-1">
                    {step.description}
                  </p>
                  {step.command && (
                    <code className="block mt-2 text-xs text-neon-green bg-surface-light rounded px-2 py-1">
                      {step.command}
                    </code>
                  )}
                </div>
              </div>
            </div>
          ))}
        </div>
        <div className="rounded-lg border border-neon-cyan/30 bg-neon-cyan/5 p-4">
          <p className="text-sm text-foreground/70">
            <strong className="text-neon-cyan">Simulation isolation:</strong>{" "}
            Your test simulations won&apos;t pollute production data. Each
            simulation run gets its own isolated ID, so your eval runs are
            completely separate from live data.
          </p>
        </div>
      </section>

      {/* Example PR */}
      <section className="space-y-4">
        <h2 className="font-pixel text-sm text-neon-magenta">EXAMPLE PR FORMAT</h2>
        <div className="rounded border border-border bg-surface-light p-4 text-xs text-foreground/70 font-mono whitespace-pre-wrap leading-relaxed">
{`## What changed
Tuned speaker selection weights to increase topic_relevance from 0.30 to 0.40

## Eval scores (3 runs averaged)

| Category        | Baseline | Treatment | Delta  |
|-----------------|----------|-----------|--------|
| Creativity      | 6.2      | 6.4       | +0.2   |
| Social Dynamics | 7.1      | 7.8       | +0.7   |
| Agency          | 5.9      | 5.8       | -0.1   |
| Overall         | 6.4      | 6.7       | +0.3   |

## Confidence
3 runs each, scores within +/- 0.3 standard deviation`}
        </div>
      </section>

      {/* Getting Started */}
      <section className="space-y-4" data-testid="getting-started">
        <h2 className="font-pixel text-sm text-neon-magenta">
          GETTING STARTED
        </h2>
        <div className="space-y-6">
          {GETTING_STARTED_STEPS.map((section, i) => (
            <div key={section.title}>
              <h3 className="text-sm font-medium text-foreground mb-2">
                <span className="text-neon-cyan font-mono mr-2">{i + 1}.</span>
                {section.title}
              </h3>
              <ul className="space-y-1 ml-6">
                {section.items.map((item, j) => (
                  <li
                    key={j}
                    className="flex gap-2 text-xs text-foreground/60"
                  >
                    <span className="text-neon-cyan shrink-0">&bull;</span>
                    {item}
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      </section>

      {/* Areas That Need Help */}
      <section className="space-y-4" data-testid="help-wanted">
        <h2 className="font-pixel text-sm text-neon-magenta">
          AREAS THAT NEED HELP
        </h2>
        <p className="text-sm text-foreground/70">
          Browse open issues to find something to work on:
        </p>
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
          {HELP_WANTED.map((item) => (
            <a
              key={item.label}
              href={item.url}
              target="_blank"
              rel="noopener noreferrer"
              className="rounded border border-border bg-surface p-4 hover:border-neon-cyan/30 transition-colors"
            >
              <h3 className="text-sm font-medium text-neon-cyan">
                {item.label}
              </h3>
              <p className="text-xs text-foreground/60 mt-1">
                {item.description}
              </p>
            </a>
          ))}
        </div>
        <p className="text-xs text-foreground/50">
          Check the{" "}
          <Link href="/evals" className="text-neon-cyan hover:underline">
            eval dashboard
          </Link>{" "}
          to see which categories have the lowest scores — those are the highest-impact areas to improve.
        </p>
      </section>

      {/* Discuss Before Implementing */}
      <section className="space-y-4">
        <h2 className="font-pixel text-sm text-neon-magenta">
          DISCUSS BEFORE IMPLEMENTING
        </h2>
        <p className="text-sm text-foreground/70">
          For larger contributions, open a discussion before writing code.
          This prevents wasted effort on approaches that won&apos;t be merged.
        </p>
        <div className="flex flex-wrap gap-3">
          <a
            href="https://github.com/bradtaylor/livestreamtoagi/discussions"
            target="_blank"
            rel="noopener noreferrer"
            className="inline-block rounded border border-neon-cyan/30 bg-neon-cyan/5 px-4 py-2 text-sm text-neon-cyan hover:bg-neon-cyan/10 transition-colors"
          >
            GitHub Discussions &rarr;
          </a>
          <a
            href="https://github.com/bradtaylor/livestreamtoagi/issues"
            target="_blank"
            rel="noopener noreferrer"
            className="inline-block rounded border border-border px-4 py-2 text-sm text-foreground/70 hover:text-foreground transition-colors"
          >
            Open an Issue &rarr;
          </a>
        </div>
      </section>

      {/* Links */}
      <section className="space-y-4">
        <h2 className="font-pixel text-sm text-neon-magenta">RESOURCES</h2>
        <div className="flex flex-wrap gap-3">
          <a
            href="https://github.com/bradtaylor/livestreamtoagi"
            target="_blank"
            rel="noopener noreferrer"
            className="inline-block rounded border border-neon-cyan/30 bg-neon-cyan/5 px-4 py-2 text-sm text-neon-cyan hover:bg-neon-cyan/10 transition-colors"
          >
            GitHub Repo &rarr;
          </a>
          <Link
            href="/evals"
            className="inline-block rounded border border-border px-4 py-2 text-sm text-foreground/70 hover:text-foreground transition-colors"
          >
            Eval Dashboard &rarr;
          </Link>
          <Link
            href="/about"
            className="inline-block rounded border border-border px-4 py-2 text-sm text-foreground/70 hover:text-foreground transition-colors"
          >
            About the Research &rarr;
          </Link>
        </div>
      </section>
    </div>
  );
}
