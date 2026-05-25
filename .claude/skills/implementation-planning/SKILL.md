---
name: implementation-planning
description: Two-layer feature planning (business + technical). Use when planning any feature before implementation starts.
auto_load: true
priority: high
---

# Implementation Planning Skill

## Trigger
When planning a feature before implementation starts.

## Rules

### Two-Layer Approach

Every feature plan has two layers:

**Layer A: Non-Technical Summary**
- What are we building?
- Who benefits?
- What's the impact?

**Layer B: Technical Detail**
- What components/modules?
- What database changes?
- What API endpoints?
- What will be tested?

### Acceptance Criteria

Make them specific and testable:

Good:
```
- [ ] User can select a coach from a list
- [ ] System prevents booking overlapping sessions
- [ ] All tests pass
```

Bad:
```
- [ ] Booking system works
- [ ] It's fast
```

### Feature Breakdown

Break large features into smaller issues:
- One feature per issue (small, scoped)
- XS (< 4h), S (4-8h), M (8-16h), L (16-32h)
- Identify dependencies between issues

### Red Flags

**Blocker:**
- Acceptance criteria vague or untestable
- Technical approach missing
- Feature too large for one sprint

**Warning:**
- Dependencies not identified
- No test plan
- High-risk approach without discussion

## Wiring Plan (required for any change touching schemas, services, or runtime)

The most expensive recent bug class is "code shipped, but the new primitive is never invoked". Avoid by including this section in every technical plan:

### Schema-field wiring

For every new Pydantic field, DB column, or event payload field:
- Name the **producer** (which subsystem / route handler / writer fills it).
- Name the **consumer** (which subsystem / endpoint / UI reads it).
- If either is intentionally deferred, mark the field `# wiring: deferred — issue #NNN` so downstream issues know it is not yet live.
- For Pydantic-on-the-wire fields, name the matching TypeScript interface and confirm it lands in the same PR.

### Constructor injection vs post-hoc attribute

- Pass required infrastructure (loggers, clocks, repos, sim folders, decision loggers) as constructor parameters, not as private attrs set after construction.
- Banned pattern: `setattr(obj, "_sim_folder", folder)` paired with `getattr(self, "_sim_folder", None)` in the consumer. The fallback hides the real dependency and breaks silently when the constructor signature changes.
- If you discover this pattern in adjacent code, file a follow-up issue — but don't bundle the refactor into an unrelated PR.

### Pydantic ↔ TypeScript contract

- Any field a frontend polls on or conditionally renders must exist on both the Pydantic response model and the matching TS interface, in the same commit.
- Reject plans that use `as` casts to coerce response shapes — past sessions saw 10-minute polling timeouts from a single missing `status` field hidden behind an `as` cast.
