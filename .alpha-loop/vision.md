Here's the vision document:

---

## What We're Building

A 24/7 livestreamed AI reality show where 9 AI agents with distinct personalities live, argue, and collaborate inside a pixel art world they build together. The agents react to audience input, manage a real budget, and tackle viewer challenges — creating emergent comedy and drama through their relationships and disagreements. Think "Big Brother meets Tamagotchi, but the housemates are AIs and the house builds itself."

## Who It's For

General consumers, including non-technical and elderly viewers, who want to be entertained — not educated about AI. This means: no jargon in the UI, large click targets, minimal navigation depth, forgiving input handling, and a default experience that works with zero configuration. The stream itself should be watchable passively (like leaving a TV on), but interactive for those who want to participate via chat commands (!ask, !vote, !challenge). The website must feel like a game companion app, not a dashboard.

## Current Stage & Priority

Greenfield. Nothing exists yet. The priority is core architecture: conversation engine, agent orchestration (CrewAI), memory system, event bus, and streaming pipeline. Get agents talking reliably with consistent personalities before adding world-building, audience interaction, or polish. Ship ugly but functional. The pixel art world, TTS voices, and website are Phase 2-3 concerns.

## Decision Guidelines

- **Reliability over features.** A conversation loop that runs 24 hours without crashing beats a beautiful one that dies after 20 minutes. Invest in health checks, cost governors, and the kill switch early.
- **Configuration over code.** Speaker selection weights, energy decay, chattiness — all tunable via hot-reloadable YAML. Never hardcode a value that someone will want to tweak while watching the stream.
- **Entertainment is the product.** Every technical decision should ask: "Does this make the show more fun to watch?" Agent disagreements, budget panic, and failed builds are features, not bugs.
- **Cheapest model that works.** Use Haiku/Mini for conversation, reserve capable models (Sonnet/Pro/GPT-5) for building tasks. Sentinel exists to make cost anxiety part of the narrative.
- **Audience interaction must be dead simple.** Chat commands should be one word plus an argument. Polls should be yes/no or A/B/C. Never require the viewer to understand the system.
- **Defer cosmetic work.** No sprite polish, no website redesign, no social media automation until the core loop (trigger → select speaker → generate turn → emit event → repeat) is rock solid.
- **Safety is non-negotiable.** The Overseer content filter runs on every output from day one. Cost hard limits are set before the first LLM call. The kill switch works from a phone.

## What Good Looks Like

- Agents hold coherent, entertaining multi-turn conversations for hours without repetition, personality drift, or crashes — and a human watching can tell them apart within 30 seconds.
- The system stays within daily budget limits automatically, with Sentinel surfacing cost status as in-world narrative rather than admin alerts.
- A new viewer can open the stream, understand what's happening within one minute, and interact via chat within two — no tutorial needed.
- Every tunable parameter (speaker weights, energy model, chattiness, interrupt thresholds) lives in YAML and can be changed without restarting the system.
