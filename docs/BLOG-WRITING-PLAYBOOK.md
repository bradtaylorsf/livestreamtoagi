# Blog Writing Playbook

Status: draft support doc for the approved blog rewrite

Use this playbook when turning `docs/BLOG-EDITORIAL-PLAN.md` into MDX posts
under `website/content/blog/`.

## MDX Contract

Each post is a standalone `.mdx` file in `website/content/blog/` with this
frontmatter shape:

```mdx
---
title: "Post Title"
date: "2026-04-02"
excerpt: "One clear sentence describing the research question or finding."
tags: ["tag-one", "tag-two", "tag-three"]
author: "Brad Taylor"
---
```

Rules:

- Filename is the approved slug plus `.mdx`.
- `date` is the historical commit/issue date from the editorial plan.
- `excerpt` should describe the finding, not tease vague drama.
- Use 2-4 tags. Prefer stable research tags over novelty tags.
- Do not add invented frontmatter fields unless `website/src/lib/blog.ts`
  supports them.

## Voice

Default voice: first-person research notebook.

Use "I" for:

- Design decisions.
- Research hypotheses.
- Mistakes and lessons learned.
- Interpretation of evidence.

Use "we" only for:

- Behavior of the implemented system.
- Alpha-loop or agent-runner activity.
- Team-like behavior among agents.

Avoid:

- Demo hype.
- Claims that the system "proved" general results.
- Fictionalized anecdotes unless the underlying artifact is cited in the
  evidence notes.
- Over-polished launch-copy voice. The appeal is the rigor and candor.

## Standard Structure

Most posts should use this shape:

1. **Research Question** - what problem was I trying to understand?
2. **System Move** - what did I implement or change?
3. **Evidence** - which commits, issues, evals, logs, or docs anchor the post?
4. **What Broke** - what failed, surprised me, or remained unverified?
5. **What Changed Next** - how this post connects to the next system move.

Do not force this structure when a post is primarily an ADR, negative result,
or operational post. The point is not uniformity; it is evidence-backed
readability.

## Evidence Rules

Every post must include at least three concrete evidence anchors from the plan:

- A commit hash or issue range.
- A local doc/spec path.
- An alpha-loop summary, eval JSON, simulation log, or snapshot artifact.

Evidence should be woven into prose, not dumped as an appendix. Good examples:

- "The memory layer landed across issues #16-#21 on 2026-04-02."
- "The eval that forced this change was `eval-e24db48d`, which called out
  repeated transcripts and identity bleed."
- "The alpha-loop summary for E22 is blunt: unit-green features were silently
  no-ops when the service was not threaded through the real constructor path."

Bad examples:

- "The agents became creative." Unless the evals and logs show that.
- "The system learned." Say which mechanism changed and what evidence supports
  the change.
- "Minecraft solved embodiment." It did not; it made action failures visible.

## Hiring-Manager Signal

Each post should make one professional signal explicit:

- Systems design: a boundary, invariant, or dependency choice.
- Research discipline: a hypothesis, measurement, or negative result.
- Debugging maturity: a failure traced to a concrete cause.
- Safety judgment: an approval gate, kill path, or content-filter constraint.
- Product taste: making results inspectable and useful to outsiders.

This signal can be a paragraph, not a banner. Do not turn posts into a resume.

## Handling Negative Results

Negative results are central to the series.

When writing a negative result:

- State what the system was expected to do.
- State what actually happened.
- Quote or summarize the evaluation evidence.
- Describe the fix or next experiment.
- Leave unresolved gaps unresolved.

Preferred framing:

> This was not a failed demo. It was a useful measurement: the system had enough
> instrumentation to tell me exactly where its agency claim collapsed.

## Tags

Preferred tags:

- `research`
- `multi-agent`
- `architecture`
- `memory`
- `context`
- `conversation-engine`
- `evals`
- `negative-results`
- `safety`
- `cost-governance`
- `autonomy`
- `simulation`
- `instrumentation`
- `minecraft`
- `embodiment`
- `director-v2`
- `run-modes`
- `civilization`

Avoid one-off joke tags. Tags should help readers navigate the research corpus.

## Launch Batch Quality Gate

Before considering the first 16 posts ready:

1. All 16 approved slugs exist in `website/content/blog/`.
2. No old placeholder-only posts remain published unless deliberately retained.
3. No post predates the first repo commit unless it is explicitly framed as
   pre-repo context.
4. Each post has a date, excerpt, tags, and author.
5. Each post has at least three concrete evidence anchors.
6. Each post includes at least one candid limitation, failure, or open question.
7. `website` blog tests pass, or any failure is documented as unrelated.

## Suggested Launch Batch Order

1. `research-harness-not-demo`
2. `reproducible-agent-infrastructure`
3. `llm-call-ledger`
4. `agents-as-experimental-variables`
5. `three-tier-agent-memory`
6. `context-assembly-control-surface`
7. `first-conversation-engine`
8. `management-before-microphones`
9. `tools-turn-characters-into-agents`
10. `simulations-as-lab-bench`
11. `qa-as-research-method`
12. `repetition-problem`
13. `llm-judge-social-systems`
14. `overseer-to-management`
15. `first-evolution-loop`
16. `reactive-to-proactive-agents`

## Not Yet Approved

Do not write or replace the MDX posts until the editorial plan is approved.
The user's requested workflow is list first, approval second, writing third.
