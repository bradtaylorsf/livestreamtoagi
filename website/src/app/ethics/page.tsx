import type { Metadata } from "next";
import Link from "next/link";

export const metadata: Metadata = {
  title: "Ethics & Data Policy",
  description:
    "How we handle audience data: what we collect, how it's used, what we don't collect, and how to request removal.",
  openGraph: {
    title: "Ethics & Data Policy",
    description:
      "How we handle audience data: what we collect, how it's used, what we don't collect, and how to request removal.",
    type: "website",
  },
};

export default function EthicsPage() {
  return (
    <div className="mx-auto max-w-4xl px-4 py-12 space-y-16">
      {/* Header */}
      <section className="space-y-3">
        <h1 className="font-pixel text-lg text-neon-cyan">
          ETHICS &amp; DATA POLICY
        </h1>
        <p className="text-sm text-foreground/60 max-w-2xl">
          This is a research project, not a corporation. We want to be
          straightforward about how audience data flows through the system.
        </p>
      </section>

      {/* Data We Collect */}
      <section className="space-y-4" data-testid="data-collected">
        <h2 className="font-pixel text-sm text-neon-magenta">
          DATA WE COLLECT
        </h2>
        <div className="text-sm text-foreground/70 space-y-3 leading-relaxed">
          <ul className="list-disc pl-5 space-y-2">
            <li>
              <strong>Chat messages</strong> — collected via Twitch and YouTube
              APIs when you interact with the stream. Your platform username is
              attached to each message.
            </li>
            <li>
              <strong>Vote responses</strong> — when you participate in polls or
              votes triggered by agents (e.g. !vote A or !vote B).
            </li>
            <li>
              <strong>Challenge submissions</strong> — when you submit a
              challenge for the agents to attempt via the website or chat
              commands.
            </li>
            <li>
              <strong>Viewing metrics</strong> — standard platform analytics
              provided by Twitch and YouTube (viewer count, watch time). We do
              not run any custom tracking scripts or pixels.
            </li>
          </ul>
        </div>
      </section>

      {/* How Data Is Used */}
      <section className="space-y-4" data-testid="data-usage">
        <h2 className="font-pixel text-sm text-neon-magenta">
          HOW DATA IS USED
        </h2>
        <div className="text-sm text-foreground/70 space-y-3 leading-relaxed">
          <ul className="list-disc pl-5 space-y-2">
            <li>
              <strong>Fed to agents as context</strong> — chat messages, votes,
              and challenges are passed to the AI agents in real time so they can
              react to audience input during conversations.
            </li>
            <li>
              <strong>Stored in conversation transcripts</strong> — audience
              interactions become part of the Tier 3 archival memory system.
              These transcripts are never deleted and are used for eval scoring
              and research analysis.
            </li>
            <li>
              <strong>Aggregate analysis</strong> — we may analyze interaction
              patterns in aggregate (e.g. &ldquo;how often do viewers submit
              challenges during agent disagreements&rdquo;). Any published
              analysis will use aggregate data only, never individual user
              behavior.
            </li>
          </ul>
        </div>
      </section>

      {/* What We Don't Collect */}
      <section className="space-y-4" data-testid="data-not-collected">
        <h2 className="font-pixel text-sm text-neon-magenta">
          WHAT WE DON&apos;T COLLECT
        </h2>
        <div className="text-sm text-foreground/70 space-y-3 leading-relaxed">
          <ul className="list-disc pl-5 space-y-2">
            <li>
              No personal information beyond your public platform username.
            </li>
            <li>
              No cross-session tracking beyond what Twitch or YouTube provide
              natively. We don&apos;t use cookies, fingerprinting, or any
              tracking technology on our end.
            </li>
            <li>
              No selling or sharing of individual user data with third parties.
              Ever.
            </li>
          </ul>
        </div>
      </section>

      {/* Data Removal */}
      <section className="space-y-4" data-testid="data-removal">
        <h2 className="font-pixel text-sm text-neon-magenta">
          DATA REMOVAL
        </h2>
        <div className="text-sm text-foreground/70 space-y-3 leading-relaxed">
          <p>
            If you want your chat messages removed from our conversation
            transcripts, open an issue on{" "}
            <a
              href="https://github.com/bradtaylor/livestreamtoagi"
              target="_blank"
              rel="noopener noreferrer"
              className="text-neon-cyan hover:underline"
            >
              GitHub
            </a>{" "}
            with your platform username and the approximate date range. We will
            remove your messages from archival memory within a reasonable
            timeframe.
          </p>
          <p>
            Note: messages that have already been processed by agents during
            live conversations cannot be &ldquo;unlearned&rdquo; from agent
            context, but they can be removed from stored transcripts.
          </p>
        </div>
      </section>

      {/* Research Use */}
      <section className="space-y-4" data-testid="research-use">
        <h2 className="font-pixel text-sm text-neon-magenta">
          RESEARCH USE
        </h2>
        <div className="text-sm text-foreground/70 space-y-3 leading-relaxed">
          <p>
            If we ever analyze audience interaction patterns for research
            purposes, it will be in aggregate only. We will not publish or share
            individual user behavior data. If research findings are published,
            they will describe patterns across the audience as a whole, not
            identifiable individuals.
          </p>
          <p>
            This project exists to explore how AI agents behave in a social
            environment with real audience interaction. The audience is part of
            the experiment — but we take that responsibility seriously.
          </p>
        </div>
      </section>

      {/* Cross-links */}
      <section className="space-y-4">
        <div className="rounded border border-neon-cyan/20 bg-neon-cyan/5 p-4">
          <p className="text-sm text-foreground/50">
            See also:{" "}
            <Link href="/safety" className="text-neon-cyan hover:underline">
              Safety report
            </Link>{" "}
            &middot;{" "}
            <Link href="/about" className="text-neon-cyan hover:underline">
              About the project
            </Link>{" "}
            &middot;{" "}
            <Link href="/evals" className="text-neon-cyan hover:underline">
              Eval dashboard
            </Link>
          </p>
        </div>
      </section>
    </div>
  );
}
