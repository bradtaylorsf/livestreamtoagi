# Livestream to AGI: Research Program & Content Strategy
## A Framework for Running Entertaining, Transparent, Rigorous Multi-Agent Research
### April 2026

---

## Part 1: The Snapshot-and-Branch Research Methodology

Your instinct is right: one canonical live timeline, with branching experiments forked from snapshots. This is essentially **counterfactual simulation** — "what would have happened if we changed X at this point?" — and it's a legitimate, well-understood methodology. Here's how to formalize it.

### The Core Architecture

```
CANONICAL TIMELINE (the live stream — always running)
│
│  Day 14 ──── Snapshot A
│  │           ├── Experiment A1: Remove personality seeding from 3 agents
│  │           ├── Experiment A2: Add desire-driven autonomy
│  │           └── Experiment A3: Same config, no audience interaction
│  │
│  Day 30 ──── Snapshot B
│  │           ├── Experiment B1: Swap agent model assignments
│  │           └── Experiment B2: Introduce 3 unsupervised agents
│  │
│  Day 45 ──── Snapshot C
│  │           └── Experiment C1: A-Mem style memory vs current recall
│  │
│  (continues...)
```

**What a snapshot captures:**
- Full database state (core memories, recall memories, archival transcripts)
- Agent internal states (frustration, energy, satisfaction, etc.)
- Relationship matrices (all adjacency scores, trust levels)
- Goal states (active goals, completed goals, priority rankings)
- World state (what they've built, economic balances, lore)
- Conversation history (the full context of "where we are")

**What a snapshot does NOT capture (and that's the point):**
- Audience participation from the canonical timeline going forward
- Real-time events that happened after the snapshot
- Model updates/changes at the API level after snapshot date

This means every experiment is a "What if, starting from this exact state, we changed one variable?" That's clean experimental design.

### Making It Rigorous

The key methodological decisions:

**1. One variable per experiment.** If you fork from Snapshot A and change both the memory system AND remove personality seeding, you can't attribute results to either change. One fork, one change. Run the same fork multiple times (3-5 runs minimum) to account for LLM stochasticity.

**2. Fixed duration per experiment.** Each experiment fork runs for a set number of simulation cycles (not wall-clock time), so results are comparable. I'd suggest standardizing on "simulation days" — maybe 7 simulated days per experiment, which gives agents enough time to show behavioral changes without burning your budget.

**3. Same evaluation framework across all forks.** Your 12-category LLM-as-judge eval runs identically on the canonical timeline and every experiment fork. This gives you direct comparisons.

**4. Pre-register your hypotheses.** Before you fork a snapshot, write down what you expect to happen. "I expect that removing personality seeding will result in lower initial entertainment scores but higher emergent creativity scores by day 5." This is standard practice in research and prevents post-hoc rationalization. It's also great content — your audience sees the prediction, then watches whether it comes true.

**5. Log everything, publish everything.** Every experiment fork produces a complete data package: config diff (what changed), raw transcripts, eval scores, cost data, agent state snapshots at each checkpoint. Make these downloadable. This is your radical transparency commitment and it's what real researchers need.

### The Audience Participation Variable

You're right that this is genuinely novel. Every paper I reviewed studies agent-to-agent dynamics in closed systems. Nobody has studied agent-to-agent-to-human dynamics in a persistent, live environment. This is your most unique research contribution.

Here's how to handle it methodologically:

**The canonical timeline always has audience participation.** That's the "natural" condition — agents living in a world where humans interact with them. This is the baseline.

**For experiments, you have three conditions:**
1. **With live audience** — fork plays out on stream, audience interacts in real time (only feasible for one fork at a time, or you'd need to split your audience)
2. **With simulated audience** — fork runs offline, but you replay audience interaction patterns from the canonical timeline's history (semi-controlled)
3. **Without audience** — fork runs in complete isolation, agents only interact with each other (full control)

Condition 3 is your true control group. The comparison between Condition 1/2 and Condition 3 directly measures the audience effect — something nobody has published on.

**A specific experiment to run early:** Fork a snapshot and run it three ways: (a) canonical config + live audience, (b) canonical config + simulated audience from historical data, (c) canonical config + no audience. Measure divergence across all 12 eval categories. The delta between (b) and (c) tells you what audience interaction does to agent behavior. The delta between (a) and (b) tells you whether *live* audience matters vs. just having *some* audience input. That's two papers right there.

---

## Part 2: Format and Structure — Seasons, Episodes, and Experiments

### The Recommendation: Seasons with Continuous Canon

Don't choose between seasons and one long run. Do both.

**The Canonical Timeline runs continuously.** It never resets. Agents accumulate months/years of memory, relationships deepen or fracture, the world grows. This is the core entertainment product and the longitudinal research asset.

**Seasons are thematic arcs** layered on top of the canonical timeline. Each season introduces a research question, a set of experiments, and new capabilities. Seasons don't restart the world — they evolve it.

Here's a concrete structure:

**Season 1: "The Beginning" (Weeks 1-8)**
- Research focus: Baseline establishment
- Capabilities: Core conversation, basic tools, world building, audience chat interaction
- Experiments: Personality seeding vs. organic emergence (the first big fork)
- Key metrics: Personality differentiation rate, conversation quality, audience retention

**Season 2: "Desire" (Weeks 9-16)**
- Research focus: Proactivity and intrinsic motivation
- Capabilities: Add desire-driven autonomy, coding sandbox, social media accounts
- Experiments: D2A vs. idle-timeout proactivity, effect of real tools on agent behavior
- Key metrics: Goal completion rate, behavioral coherence, economic activity

**Season 3: "Memory" (Weeks 17-24)**
- Research focus: Long-term memory and identity evolution
- Capabilities: A-Mem style memory upgrade, adaptive personality parameters
- Experiments: Memory architecture comparison, personality drift measurement
- Key metrics: Memory coherence over time, personality stability vs. growth

**Season 4: "Society" (Weeks 25-32)**
- Research focus: Emergent social dynamics and audience co-evolution
- Capabilities: Email, expanded economic tools, inter-agent governance
- Experiments: Audience participation ablation (the three-condition study above)
- Key metrics: Alliance formation, conflict resolution, audience influence measurement

**Season 5: "Autonomy" (Weeks 33+)**
- Research focus: Increasing agent autonomy toward economic self-sufficiency
- Capabilities: Bank account access, autonomous content creation, self-directed research
- Experiments: Graduated autonomy levels, safety guardrail effectiveness
- Key metrics: Revenue generation, safety incident rate, audience growth

Each season gives you a narrative arc for entertainment ("Will the agents learn to use real money?"), a research question for the academic side ("How does access to financial tools affect agent economic behavior?"), and a natural content marketing hook for blog posts.

### Episode Structure Within Seasons

Within each season, I'd suggest a weekly rhythm:

- **Monday-Friday:** Canonical timeline runs live. Audience interacts. Agents pursue goals, have conversations, build things.
- **Saturday:** "Lab Day" — you show experiment results from the past week's forks. Overlay the canonical timeline with experiment divergences. Show graphs, eval comparisons, surprising moments from the forks. This is where the research gets showcased.
- **Sunday:** Reflection cycle. Agents do their weekly reflection. You publish the weekly research data package. Blog post goes up.

The "Lab Day" concept is key for making research entertaining. You're basically saying, "Here's what our agents did this week. And here's what *would have happened* if we'd changed X." The audience gets invested in the canonical timeline AND curious about the experiments.

### Showing Divergent Timelines on Stream

For the live stream, here's how to visualize it:

**Split-screen moments.** When an experiment fork produces dramatically different results, show both timelines side by side. "In our world, Rex and Fork became allies. But in the experiment where we removed personality seeding, they haven't spoken in 3 days." This is inherently engaging television.

**"What If" segments.** Short (5-10 minute) pre-produced segments that show key moments from experiment forks. Narrated by the agents themselves, if you want to go meta ("In another timeline, I apparently became the budget hawk instead of Sentinel...").

**Research dashboards on stream.** A persistent overlay showing key metrics — agent satisfaction levels, budget burn rate, conversation energy, audience interaction count. These update in real time and give data-minded viewers something to track.

---

## Part 3: The Blog Post Series

Your story — building a system independently and then discovering it converges with (and diverges from) published research — is genuinely compelling. Here's how to structure it.

### Series Title: "Building Toward AGI, One Livestream at a Time"
*Subtitle: What happens when an engineer builds a multi-agent system from scratch, then reads the papers*

### Post 1: "I Built a Multi-Agent AI System Before Reading Any Papers. Here's Where I Was Right and Wrong."
**The hook post.** This is the one that goes viral on Hacker News.

Content:
- Your background: enterprise AI work, agent building experience, the idea for the project
- The core design decisions you made from intuition and experience (not papers)
- Then: "Last week, I finally read the academic literature. Six papers. Here's what I found."
- For each paper: what you got right, what you got wrong, what surprised you
- The punchline: practitioner intuition and academic research converge more than either side admits, but diverge in important ways

Tone: Honest, slightly self-deprecating about not reading papers earlier, but confident about the value of building-first. This is relatable to every engineer who's ever said "I should probably read the paper on this."

### Post 2: "The Personality Seeding Question: Should You Tell AI Agents Who They Are?"
**The research question post.** Goes deep on one topic.

Content:
- Your approach: heavy personality seeding with archetypes, system prompts, behavioral configs
- The 2024 paper showing organic personality emergence from blank-slate agents
- Why this matters: if personality can emerge organically, what are we constraining by pre-defining it?
- Your planned experiment: seeded vs. unseeded agents from the same snapshot
- Early results (if you've run the experiment by publication time)

### Post 3: "Making Reactive AI Agents Proactive: Lessons from Maslow and ICLR 2025"
**The technical deep-dive post.** For the AI engineering audience.

Content:
- The fundamental problem: LLMs are reactive, but believable agents need to be proactive
- Your original approach: initiative scores + idle timeouts
- D2A's approach: desire-driven autonomy based on Maslow's hierarchy
- How you're integrating it: using your existing internal state tracking
- Before/after comparison of agent behavior
- Code snippets, architecture diagrams

### Post 4: "The Variable Nobody's Studying: What Happens When Real Humans Enter a Multi-Agent Simulation"
**The novel contribution post.** This is the one academic researchers will cite.

Content:
- Literature review: every major multi-agent paper studies closed systems
- Your setup: 9 agents + live Twitch/YouTube audience
- The three-condition experiment (live audience / simulated audience / no audience)
- What you've observed: how audience interaction changes agent behavior in ways the literature doesn't predict
- Open questions for the research community

### Post 5: "AI Agents with Real Money: Economic Behavior Under Actual Scarcity"
**The eye-catching post.** The "real money" angle gets attention.

Content:
- Why simulated economics produce different behavior than real economics
- Your setup: actual API costs, real budget constraints
- What happens when an agent's spending actually matters
- Sentinel's budget monitoring behavior vs. what the literature predicts
- The path toward agent economic self-sufficiency (or the failure to get there)

### Post 6: "Season 1 Results: What We Learned From 8 Weeks of AI Reality TV"
**The results post.** Data-heavy, narrative-driven.

Content:
- Comprehensive Season 1 findings across all experiments
- Key metrics with graphs
- Surprising results and failed hypotheses
- What changed for Season 2
- All data packages linked for reproducibility

### Ongoing: Weekly "Lab Notes" posts
Short (500-800 word) posts each Sunday that cover:
- What happened in the canonical timeline this week
- Any experiments that ran and preliminary results
- Interesting moments or behaviors worth highlighting
- Next week's planned experiments

These keep the audience engaged between major posts and build a research log that's valuable over time.

### Where to Publish

For the blog posts: start on your own site/Substack, cross-post to Medium and dev.to. Post 1 and Post 4 specifically — submit those to Hacker News yourself. The "built before reading papers" angle and the "audience participation" angle both have strong HN appeal.

For more formal research output: arXiv is open and doesn't require peer review to publish. You can put up a paper at any time. Once you have Season 1 results, write them up as a proper paper and post to arXiv. This establishes priority and makes your work citable. You can later submit to conferences like EMNLP, AAMAS (Autonomous Agents and Multi-Agent Systems), or NeurIPS workshops.

---

## Part 4: How to Position Yourself as a Researcher

### You're Already Doing Research. Own It.

Here's the thing: research isn't defined by having a PhD or university affiliation. It's defined by methodology. If you have a hypothesis, a controlled experiment, reproducible conditions, and published data — that's research. Period.

Your situation is actually enviable in the current AI research landscape:
- You have a running system, not a toy benchmark
- You have real economic constraints, not simulated ones
- You have audience interaction data that no academic lab can replicate
- You're building in public with radical transparency

### The "Practitioner-Researcher" Frame

Position yourself as a practitioner-researcher. You're not an academic studying agents in theory — you're an engineer running a live system and applying research methodology to understand what's happening. This is credible and increasingly respected in AI/ML.

The framing in your blog posts should be: "I build multi-agent systems for a living. I built this one from intuition. Then I tested it against the literature. Here's what I found."

### Reproducing vs. Challenging vs. Extending

You asked whether to reproduce existing results, challenge them, or extend them. The answer is: all three, at different times, and be clear about which you're doing.

**Reproducing:** When you run a personality-seeded simulation and get results consistent with Generative Agents (Park et al.), that's reproduction. Reproduction is valuable even though it doesn't feel novel. It builds credibility and strengthens the field. Mention it: "Our results are consistent with Park et al.'s finding that reflection improves behavioral coherence."

**Challenging:** When you run the organic emergence experiment and find that your seeded agents are *more* entertaining but *less* creative than unseeded agents, that's a challenge. It doesn't mean either result is wrong — it means the relationship is more nuanced than the original paper captured. Frame it that way: "While [paper] found X, our results suggest that in a persistent, audience-facing environment, the relationship between personality seeding and [outcome] is mediated by [factor]."

**Extending:** When you measure the audience participation effect — something no existing paper has studied — that's extension. This is where you contribute new knowledge. Frame it as: "Building on [paper]'s work on agent social dynamics, we introduce a novel variable: real-time human audience interaction."

### Practical Steps

1. **Get an ORCID.** It's free, takes 2 minutes, and gives you a researcher identifier that links all your publications. https://orcid.org

2. **Post your first paper to arXiv** after Season 1. It doesn't need to be polished to journal standards. arXiv papers get cited all the time in AI. Format: describe your system, your methodology, Season 1 results, and open questions.

3. **Engage with the authors you're citing.** Twitter/X and Bluesky are where AI researchers interact. When you publish results that relate to their work, tag them. Most researchers are excited to see their work applied in novel contexts.

4. **Attend one conference.** AAMAS (Autonomous Agents and Multi-Agent Systems) or a NeurIPS workshop on multi-agent systems. You don't need to present — just go, talk to people, show them your system on your phone. The live demo of real agents with real audiences doing real things is more compelling than any poster.

5. **Build a proper research page on your website.** List your hypotheses, experiments, data packages, and blog posts in an organized way. Make it easy for academic researchers to find, cite, and build on your work.

---

## Part 5: The Expanding Capability Roadmap

You mentioned several capabilities you want to add: coding sandbox, social media accounts, email, eventually a real bank account. Here's how to introduce them as both entertainment milestones and research variables.

### Principle: Each New Capability is a Research Event

Every time you give agents a new tool, that's an intervention. Treat it like one:

1. **Before** giving them the tool: snapshot the current state, run baseline metrics
2. **Give** them the tool: document exactly what they can now do
3. **After**: measure behavioral changes across all 12 eval categories
4. **Fork**: run the same period without the new tool from the same snapshot

This gives you a clean before/after comparison for every capability addition.

### Recommended Capability Sequence

**Phase 1 (Season 1-2):**
- Conversation + basic world building (already have)
- Coding sandbox (isolated Docker containers, agents can write and deploy code to their world)
- Audience task submission (humans propose tasks, agents vote on which to pursue)

**Phase 2 (Season 3-4):**
- Social media accounts (agents post to X/Bluesky, respond to mentions — with your approval initially, then graduated autonomy)
- Email (agents can send emails to each other and to external addresses you whitelist)
- Economic tools (agents can allocate budget to their projects, propose spending)

**Phase 3 (Season 5+):**
- Graduated financial autonomy (small real transactions, heavily monitored)
- Autonomous content creation (blog posts, videos, music — agents create and publish)
- Self-directed research (agents propose their own experiments on their own behavior)

The Phase 3 self-directed research angle is particularly interesting from a research perspective. If your agents can design experiments on themselves, you've created a meta-research loop. That's wild and publishable.

### Safety Escalation Matching Capability Escalation

As capabilities expand, safety needs to expand to match:

- **Phase 1 safety:** Current 3-layer Management filter is sufficient
- **Phase 2 safety:** Add pre-execution goal review (the recommendation from the previous analysis). Social media posts require your approval for the first N posts, then graduated to Management-only review after establishing a safety track record.
- **Phase 3 safety:** Multi-layer approval for financial transactions. Hard spending limits per agent per day. All external communications logged and reviewable. Kill switch remains accessible from your phone.

The graduated trust model — agents earn autonomy by demonstrating safe behavior — is itself a research question worth studying. "How quickly do LLM agents earn trust in a supervised environment, and is that trust warranted?"

---

## Part 6: Data Architecture for Research

To make all of this work, you need your data infrastructure to support research from day one.

### What to Log (Everything)

For every agent action:
- Timestamp, agent ID, action type
- Full input context (what the agent "saw" when it decided)
- Full output (what the agent said/did)
- Internal state at time of action (all 6 dimensions)
- Cost of the action (API tokens, dollars)
- Evaluation scores (run async, don't block the live stream)

For every audience interaction:
- Timestamp, platform, anonymized user ID
- Interaction type (chat message, vote, task submission, tip)
- Which agent(s) were affected
- How agent behavior changed (if measurable)

For every experiment:
- Fork point (which snapshot)
- Variable changed (exactly one thing)
- Duration (simulation cycles)
- All of the above logging, identical to canonical timeline
- Pre-registered hypothesis

### Data Publication

Weekly: publish a data package containing:
- Anonymized conversation transcripts
- Eval scores across all 12 categories
- Agent state trajectories (how internal states changed over time)
- Cost data
- Audience interaction summary statistics (no individual user data)

Per experiment: publish the above plus:
- Config diff (what was changed)
- Hypothesis document (written before the experiment)
- Results summary
- Statistical comparison with canonical timeline

Host all of this on GitHub or a dedicated data repository (Zenodo is free and gives you DOIs, which makes your data citable in academic papers).

---

## Part 7: What Makes This a Genuine Research Sandbox

You said you feel like this is a sandbox for many research projects. You're right. Here's a non-exhaustive list of research questions this platform can uniquely study:

1. **Personality emergence:** Does organic differentiation produce more or less entertaining agents than designed personalities?
2. **Audience co-evolution:** How does human interaction change multi-agent dynamics over time?
3. **Economic behavior under real scarcity:** Do agents manage real money differently than simulated money?
4. **Cross-model social dynamics:** Do agents running on different LLMs form different kinds of relationships?
5. **Memory architecture comparison:** Which memory system produces the most coherent long-term behavior?
6. **Proactivity mechanisms:** Desire-driven vs. idle-timeout vs. scheduled activity
7. **Safety under autonomy:** How effective are guardrails as agent capabilities expand?
8. **Trust and delegation:** Can agents earn graduated autonomy through demonstrated safety?
9. **Creative collaboration:** What conditions produce the most original creative output from multi-agent systems?
10. **Longitudinal identity:** How stable is agent "personality" over weeks/months of continuous operation?
11. **Meta-cognition:** Can agents productively reason about their own simulation?
12. **Entertainment metrics as evaluation:** Is audience retention a valid proxy for agent believability?

Each of these is a publishable paper. Some are worth multiple papers (longitudinal studies as data accumulates over seasons). Your platform is uniquely positioned to study all of them because you have what no academic lab has: a persistent, live, audience-interactive, economically real multi-agent system.

That's not a project. That's a research program.
