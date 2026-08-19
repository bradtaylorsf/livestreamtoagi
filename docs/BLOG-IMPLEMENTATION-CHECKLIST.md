# Blog Implementation Checklist

Status: prepared, pending user approval

Use this checklist only after the approval in `docs/BLOG-APPROVAL-SUMMARY.md`
is given. The original recommendation was the first 16 posts, but the
2026-06-06 approval selected all 49 posts with new research-notebook slugs,
replacement of old placeholder posts, and first-person research voice.

## Pre-Write Gate

- Confirm approval scope: first 16 posts, all 49 posts, or a different batch.
- Confirm slug strategy: new research-notebook slugs or preserve selected old
  slugs.
- Confirm placeholder handling: delete old placeholder posts, replace in place,
  or add redirects.
- Re-read `docs/BLOG-WRITING-PLAYBOOK.md` before drafting.
- Use `docs/BLOG-EVIDENCE-LEDGER.md` as the source checklist.
- Use `docs/BLOG-SERIES-MANIFEST.tsv` for ordered slugs, dates, batches, and
  titles.
- Use `docs/BLOG-LAUNCH-DOSSIERS.md` for the first 16 posts' thesis,
  limitations, and hiring-manager signal.
- Use `docs/BLOG-PLACEHOLDER-REPLACEMENT-AUDIT.md` before deleting or
  redirecting current blog files.
- Run `python3 scripts/validate_blog_plan.py --mode planning` before writing,
  then run `python3 scripts/validate_blog_plan.py --mode all` after the
  approved 49-post series is in place.

## Files To Create For Recommended Launch

Create these MDX files under `website/content/blog/`:

| # | File | Date |
| --- | --- | --- |
| 1 | `research-harness-not-demo.mdx` | 2026-03-30 |
| 2 | `reproducible-agent-infrastructure.mdx` | 2026-03-31 |
| 3 | `llm-call-ledger.mdx` | 2026-04-01 |
| 4 | `agents-as-experimental-variables.mdx` | 2026-04-02 |
| 5 | `three-tier-agent-memory.mdx` | 2026-04-02 |
| 6 | `context-assembly-control-surface.mdx` | 2026-04-02 |
| 7 | `first-conversation-engine.mdx` | 2026-04-03 |
| 8 | `management-before-microphones.mdx` | 2026-04-03 |
| 9 | `tools-turn-characters-into-agents.mdx` | 2026-04-03 |
| 10 | `simulations-as-lab-bench.mdx` | 2026-04-04 |
| 11 | `qa-as-research-method.mdx` | 2026-04-04 |
| 12 | `repetition-problem.mdx` | 2026-04-04 |
| 13 | `llm-judge-social-systems.mdx` | 2026-04-04 |
| 14 | `overseer-to-management.mdx` | 2026-04-04 |
| 15 | `first-evolution-loop.mdx` | 2026-04-05 |
| 16 | `reactive-to-proactive-agents.mdx` | 2026-04-08 |

## Placeholder Files To Remove Or Redirect

The current blog loader publishes every `.mdx` file in `website/content/blog/`.
If the recommended launch is approved, these placeholder files should not remain
published alongside the new research-notebook posts:

- `62-simulations-retrospective.mdx`
- `agent-dreams.mdx`
- `conversation-engine-deep-dive.mdx`
- `designing-memory-for-agents.mdx`
- `economics-of-artificial-life.mdx`
- `eval-framework.mdx`
- `first-week-lessons.mdx`
- `multi-model-matters.mdx`
- `the-management-problem.mdx`
- `what-we-got-wrong.mdx`
- `who-talks-next.mdx`
- `why-a-reality-show-for-ai.mdx`
- `why-agi-is-tongue-in-cheek.mdx`
- `why-ai-agents-are-reactive.mdx`

Recommended launch behavior: remove the placeholder MDX files after the new
posts exist. Add redirects later only if preserving old URLs becomes important.

## Per-Post Drafting Gate

Each post must have:

- Frontmatter supported by `website/src/lib/blog.ts`: `title`, `date`,
  `excerpt`, `tags`, `author`, and optional `coverImage`.
- Historical `date` matching the editorial plan.
- `author: "Brad Taylor"`.
- 2-4 stable research tags.
- At least three concrete evidence anchors from commits, issues, docs, evals,
  alpha-loop learnings, logs, or snapshots.
- One explicit limitation, failure, surprise, or open question.
- A clear hiring-manager signal: systems design, research discipline,
  debugging maturity, safety judgment, or product taste.

## Website Checks After Writing

Run from `website/` after MDX changes:

```sh
python3 ../scripts/validate_blog_plan.py --mode launch
pnpm lint
pnpm test
pnpm build
```

If the build fails because replay assets or local generated artifacts are
missing, record the exact failure and decide whether it is unrelated to blog
content before shipping.

## Content Verification Commands

Use these checks after writing the approved 49-post batch:

```sh
python3 scripts/validate_blog_plan.py --mode all
find website/content/blog -maxdepth 1 -type f -name '*.mdx' | wc -l
rg -n '^date: "2026-03-[0-9]{2}"|^date: "2026-04-[0-9]{2}"' website/content/blog
rg -n '^author: "Brad Taylor"$' website/content/blog
rg -n 'first-week-lessons|conversation-engine-deep-dive|why-a-reality-show-for-ai' website/content/blog
```

Expected state for the all-49 approval:

- 49 published `.mdx` files if all placeholder posts are removed.
- No post dated before 2026-03-30.
- All 16 posts have `author: "Brad Taylor"`.
- No old placeholder slug appears as a published filename.

## Optional Redirect Follow-Up

If old blog URLs need preservation, add a redirect strategy after content lands.
The current route `website/src/app/blog/[slug]/page.tsx` returns `notFound()`
for missing slugs, and `website/next.config.ts` can host static redirects if
that becomes necessary.

Use the redirect targets in `docs/BLOG-EDITORIAL-PLAN.md` rather than inventing
new targets during implementation.

## Done Criteria For The Blog Launch Batch

The launch batch is done when:

1. The approved `.mdx` files exist in `website/content/blog/`.
2. The old placeholder posts are removed or deliberately redirected.
3. Blog index renders the new posts in date order.
4. Individual post pages render MDX content without route errors.
5. RSS generation can parse all post dates.
6. Website lint, tests, and build pass or documented unrelated failures exist.
7. The final summary names any deferred batches and remaining launch risks.
