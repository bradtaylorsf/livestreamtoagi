# Blog Placeholder Replacement Audit

Status: replacement audit, pending user approval before MDX changes

Purpose: record the current published blog files, their frontmatter, and the
recommended handling when the research-notebook launch batch is approved.
`website/src/lib/blog.ts` publishes every `.mdx` file in
`website/content/blog/`, so old placeholder files must be removed or redirected
deliberately rather than left beside the new series.

## Current Published Files

| Current file | Date | Tags | Recommended action | Replacement target |
| --- | --- | --- | --- | --- |
| `first-week-lessons.mdx` | 2026-03-21 | `progress`, `lessons`, `economics` | Remove; date predates first repo commit and contains unverifiable week-one anecdotes. | `repetition-problem` |
| `conversation-engine-deep-dive.mdx` | 2026-03-28 | `architecture`, `conversation-engine`, `social-dynamics` | Remove; date predates implementation and should be rebuilt from actual conversation-engine commits. | `first-conversation-engine` |
| `why-a-reality-show-for-ai.mdx` | 2026-04-01 | `vision`, `multi-agent`, `research` | Replace angle; useful origin material, but should be tied to the first commit and research-harness thesis. | `research-harness-not-demo` |
| `why-agi-is-tongue-in-cheek.mdx` | 2026-04-01 | `research`, `agi`, `satire` | Remove as standalone; fold careful framing into origin/cost posts without making unserious AGI claims. | `research-harness-not-demo`, `llm-call-ledger` |
| `multi-model-matters.mdx` | 2026-04-02 | `architecture`, `multi-model` | Replace; topic is useful, but belongs in the controlled agent-config/model-assignment post. | `agents-as-experimental-variables` |
| `designing-memory-for-agents.mdx` | 2026-04-03 | `memory`, `architecture` | Replace; memory landed on 2026-04-02 and should be sourced from issues #16-#21. | `three-tier-agent-memory` |
| `who-talks-next.mdx` | 2026-04-04 | `conversation-dynamics`, `social-dynamics` | Replace; topic is right, but date and evidence should match 2026-04-02/03 engine commits. | `first-conversation-engine` |
| `the-management-problem.mdx` | 2026-04-05 | `safety`, `content-filtering` | Replace; should split early pre-TTS safety from the 2026-04-04 Overseer-to-Management rename. | `management-before-microphones`, `overseer-to-management` |
| `why-ai-agents-are-reactive.mdx` | 2026-04-06 | `agency`, `autonomy`, `evals` | Replace; strong thesis, but actual autonomy implementation and final merge landed by 2026-04-08. | `reactive-to-proactive-agents` |
| `eval-framework.mdx` | 2026-04-07 | `evals`, `methodology` | Replace; should be grounded in 2026-04-04 eval commits and foreground measurement limits. | `llm-judge-social-systems` |
| `agent-dreams.mdx` | 2026-04-08 | `creativity`, `dreams`, `memory` | Queue for batch 2; keep topic but include missing-dream-entry failure and later fixes. | `dreams-as-control-mechanism` |
| `economics-of-artificial-life.mdx` | 2026-04-09 | `economics`, `autonomy`, `budget` | Queue for later rewrite; cost governance starts earlier and kill-switch hardening lands in E11. | `llm-call-ledger`, then `autonomy-needs-kill-switch` |
| `62-simulations-retrospective.mdx` | 2026-04-10 | `lessons`, `progress`, `retrospective` | Remove; retrospective frame is useful, but many claims need artifact-backed treatment or should become negative results. | `simulation-first-pivot`, `negative-result-activity-not-collaboration` |
| `what-we-got-wrong.mdx` | 2026-04-10 | `lessons`, `transparency`, `failures`, `research` | Remove as standalone launch post; distribute failures into chronological evidence-backed posts. | `repetition-problem` |

## Replacement Policy

Recommended approval behavior:

- Create the 16 new launch MDX files first.
- Delete the 14 old placeholder MDX files in the same change.
- Do not preserve old slugs unless URL preservation becomes a real requirement.
- If redirects are requested later, add them after content lands and use the
  replacement targets above.

## Claims To Avoid Carrying Forward Without Evidence

The current placeholders contain memorable launch-copy claims that should not be
copied into the research notebook unless the specific artifact can be cited:

- Exact counts like "62 simulations", "168 hours", or detailed token/cost
  totals unless backed by logs or database exports.
- Specific emergent anecdotes such as unnamed alliances, votes, haiku streaks,
  or a particular simulation number unless the transcript or eval artifact is
  cited.
- Claims that memory "fixed" personality drift; the research notebook should
  say what mechanism changed and what remained unverified.
- Claims that dreams fueled creativity without also mentioning the early
  missing-dream-entry failure.
- Claims that evals became "the backbone of every design decision" unless
  paired with concrete implementation issues created from findings.
- Claims that Management is a character in the world; current architecture
  treats Management as an out-of-band safety role.

## Launch-Batch Mapping

| New launch post | Old material it can absorb |
| --- | --- |
| `research-harness-not-demo` | Careful parts of `why-a-reality-show-for-ai` and `why-agi-is-tongue-in-cheek`. |
| `reproducible-agent-infrastructure` | None; net-new research infrastructure story. |
| `llm-call-ledger` | Cost-governance parts of `economics-of-artificial-life`. |
| `agents-as-experimental-variables` | Model/config framing from `multi-model-matters`. |
| `three-tier-agent-memory` | Architecture framing from `designing-memory-for-agents`. |
| `context-assembly-control-surface` | Mostly net-new; can use memory post's context-window problem framing. |
| `first-conversation-engine` | `conversation-engine-deep-dive` and `who-talks-next`. |
| `management-before-microphones` | Safety framing from `the-management-problem`. |
| `tools-turn-characters-into-agents` | Mostly net-new tool/action story. |
| `simulations-as-lab-bench` | Measured parts of `62-simulations-retrospective`, if evidence-backed. |
| `qa-as-research-method` | Failure framing from `what-we-got-wrong`. |
| `repetition-problem` | Reactive/failure material from `what-we-got-wrong` and `first-week-lessons`, if evidence-backed. |
| `llm-judge-social-systems` | Structured eval framing from `eval-framework`. |
| `overseer-to-management` | Rename/filter tuning material from `the-management-problem`. |
| `first-evolution-loop` | Self-improvement framing from eval/autonomy placeholders, but only with issue #238-#242 evidence. |
| `reactive-to-proactive-agents` | Core thesis from `why-ai-agents-are-reactive`. |

## Approval Boundary

This audit is preparatory. It does not approve deleting, redirecting, or
rewriting files under `website/content/blog/`.
