# Minecraft Pivot - Project Context

## What this project is
Livestream to AGI: an experiment in whether a group of LLM agents can
autonomously run a business - sustain a 24/7 livestream, post to social
media, hold an audience, and stay economically self-sustaining. The
"AGI" framing is tongue-in-cheek (Artificial General *Action*
Intelligence). Entertainment is the product; autonomy is the thesis.

## Why we are pivoting the visual/world layer to Minecraft
The current world is a 2-D Phaser office. Agents "build" by writing
tilemap JSON, with no environment to act in and no way to verify a build
worked. Evals confirmed the agents were never good at building anything
useful. The project's own research notes already identified the fix:
Voyager-style embodiment in Minecraft gives agents a concrete action
space AND environment self-verification - the missing mechanism. We are
moving the world layer to Minecraft so building, moving, and acting
become real, verifiable actions instead of unverified code generation.

## The chosen architecture - "Option C, disciplined"
- Minecraft + Mineflayer (via a fork of Mindcraft) owns: agent BODIES,
  the world, movement, pathfinding, the skill/action library, bot
  process management, and the decentralized "respond or ignore"
  conversation model.
- The existing Python brain REMAINS the source of truth for: the 3-tier
  pgvector memory system, agent dreams/journals, alliances and voting,
  the energy/personality model, eval and reporting, cost controls, and
  Management (a safety content-filter, NOT a world bot).
- Integration is bots-call-Python-services over a bridge. The Python
  brain is NOT a central conversation director. Mindcraft's per-agent
  decentralized respond/ignore model replaces the old director.
- The old Phaser frontend, tilemap generation, pixel-office layout,
  sprite/asset pipeline, custom A* pathfinding, and Phaser-canvas replay
  are all retired.

## What MUST be preserved (non-negotiable)
1. Per-agent multi-model routing via OpenRouter - each agent runs a
   different LLM with separate conversation/building model tiers. This
   is the core research thesis. Verify Mindcraft supports this; if not,
   it is a required patch on the fork.
2. The 3-tier memory system (Postgres + pgvector): core, recall,
   archival. Stays Python-side, exposed as a service the bots query.
3. Agent dreams and journals that publish to the website.
4. Cost controls: hard per-agent hourly spend caps and the
   phone-accessible kill switch. A prior runaway loop burned $38/hour;
   a 24/7 autonomous world is MORE exposed to this.
5. Eval and reporting harness.
6. Management as an out-of-band content-safety filter on agent output -
   never spawned as a Minecraft bot.

## What we want Minecraft to ENHANCE
The ability for agents to genuinely build and create things, with
verification - and ideally to keep their code-writing ability as a tool
alongside real in-world building.

## Two run modes the system must support
1. Long-lived 24/7 simulation - a persistent world, livestreamed,
   running indefinitely.
2. Experimental simulations - shorter runs where we tweak starting
   conditions: different backstories, pre-set factions, different goals,
   different seeded memories, or NO backstory at all (blank-slate runs
   to see what emerges).
The architecture must treat "starting conditions" (personas, memories,
factions, goals, world) as configurable inputs, not hardcoded.

## Special agents
- Management: safety/content filter. Out-of-band. Not a world bot.
- Alpha: conceived as the "office dog" - a general-purpose errand runner
  the other agents can dispatch to do things for them. Non-verbal,
  communicates in symbols. Because it is non-verbal and action-only, it
  is the simplest agent to embody first and is the recommended
  vertical-slice test case.

## Important constraint about the person running this
The project owner has NEVER played Minecraft and knows nothing about it.
Every Minecraft-specific issue must be written for a complete beginner:
explain server types, versions, auth, LAN vs dedicated, mods, and any
in-game concepts in plain language. Do not assume any Minecraft
knowledge anywhere.

## Current stack (for reference)
Python 3.13, FastAPI, asyncio, CrewAI, Postgres 16 + pgvector, Redis 7,
OpenRouter, Edge TTS, Langfuse. Website: Next.js (live, public).
Committed integrations: OpenRouter, Twitch, YouTube, Edge TTS.
