# Blog Approval Summary

Status: ready for user approval before MDX drafting

Post-approval update, 2026-06-06: user approved creating all 49 posts, not only
the recommended 16-post launch batch. The implementation now uses
`scripts/validate_blog_plan.py --mode all` as the content gate.

This is the compact approval view for `docs/BLOG-EDITORIAL-PLAN.md`. The full
plan contains the 49-post table, replacement map, summaries, and evidence. This
file captures the recommended launch decision so drafting can start cleanly
after approval.

Implementation checklist after approval:
`docs/BLOG-IMPLEMENTATION-CHECKLIST.md`.
Machine-readable series manifest: `docs/BLOG-SERIES-MANIFEST.tsv`.
Launch-batch evidence dossiers: `docs/BLOG-LAUNCH-DOSSIERS.md`.
Placeholder replacement audit: `docs/BLOG-PLACEHOLDER-REPLACEMENT-AUDIT.md`.
Approval-packet validator: `scripts/validate_blog_plan.py`.

## Recommended Approval

Approve these three choices:

1. Launch with the first 16 posts, dated 2026-03-30 through 2026-04-08.
2. Replace the old placeholder posts with the new research-notebook slugs.
3. Use first-person research voice, with "we" only for system behavior,
   alpha-loop work, or multi-agent behavior.

## Why This Launch Batch

The first 16 posts form a complete research arc before the Minecraft pivot:

- Project thesis and reproducible experiment substrate.
- Centralized LLM routing, cost visibility, and model assignment.
- Agent configs, three-tier memory, and context assembly.
- Conversation engine, Management safety path, TTS, and tools.
- Simulation bench, QA, evals, repetition failures, and the first evolution
  loop.
- Autonomy diagnosis and the shift from reactive agents to proactive internal
  state.

This is enough for AI researchers and hiring managers to evaluate the early
system design and research discipline without waiting for all 49 posts.

## Launch Batch To Draft After Approval

| # | Date | Slug | Title |
| --- | --- | --- | --- |
| 1 | 2026-03-30 | `research-harness-not-demo` | The Research Harness: Why a Livestreamed Agent World |
| 2 | 2026-03-31 | `reproducible-agent-infrastructure` | Reproducible Infrastructure for Agent Experiments |
| 3 | 2026-04-01 | `llm-call-ledger` | Every LLM Call Needs a Ledger |
| 4 | 2026-04-02 | `agents-as-experimental-variables` | Casting Agents as Experimental Variables |
| 5 | 2026-04-02 | `three-tier-agent-memory` | A Three-Tier Memory System for Persistent Agents |
| 6 | 2026-04-02 | `context-assembly-control-surface` | Context Assembly Is Where the Agent Actually Lives |
| 7 | 2026-04-03 | `first-conversation-engine` | Who Talks Next? Building the First Conversation Engine |
| 8 | 2026-04-03 | `management-before-microphones` | Management Before Microphones |
| 9 | 2026-04-03 | `tools-turn-characters-into-agents` | Tools Turn Characters Into Agents |
| 10 | 2026-04-04 | `simulations-as-lab-bench` | Simulations Became the Lab Bench |
| 11 | 2026-04-04 | `qa-as-research-method` | QA as a Research Method |
| 12 | 2026-04-04 | `repetition-problem` | The Repetition Problem |
| 13 | 2026-04-04 | `llm-judge-social-systems` | LLM-as-Judge Evals for Artificial Social Systems |
| 14 | 2026-04-04 | `overseer-to-management` | From Overseer to Management |
| 15 | 2026-04-05 | `first-evolution-loop` | The First Evolution Loop |
| 16 | 2026-04-08 | `reactive-to-proactive-agents` | Making Reactive Agents Proactive |

## Deferred Batches

| Batch | Dates | Posts | Focus |
| --- | --- | --- | --- |
| Batch 2 | 2026-04-08 to 2026-05-09 | 8 | Dreams, Phaser office, website, simulation isolation, token bloat, dashboard QA, simulation-first pivot, replay fidelity. |
| Batch 3 | 2026-05-17 to 2026-05-20 | 8 | Minecraft pivot, embodiment stack, Mindcraft fork, bridge, embodied memory, verification, Alpha, all-agent embodiment. |
| Batch 4 | 2026-05-21 to 2026-05-23 | 6 | Cost/kill, livestream ops, Director V2, text/live Minecraft command evals, open-source readiness. |
| Batch 5 | 2026-05-24 to 2026-06-04 | 11 | Dreams/journals preservation, embodied evals, run modes, negative collaboration result, headless replay, BuildScripts, civilization mechanics, observability debt. |

## What Changes After Approval

After approval, drafting should:

- Create the approved MDX files under `website/content/blog/`; for the
  2026-06-06 approval, this means all 49 manifest posts.
- Remove or redirect old placeholder-only posts as approved.
- Use historical dates from the plan.
- Include at least three evidence anchors per post.
- Include a candid limitation, failure, or open question in each post.
- Run the website blog checks/build after content changes.

## What Remains Unchanged Before Approval

No files in `website/content/blog/` should be changed until the approval is
given. The current work is planning-only.

## Approval Text

The shortest approval that unlocks writing is:

> Approved: draft the first 16 posts, use the new slugs, replace the placeholder
> posts, and use the recommended first-person research voice.
