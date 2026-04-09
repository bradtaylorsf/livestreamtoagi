import { describe, it, expect } from "vitest";
import { EventType } from "./events";

/**
 * These values must match the backend EventType enum in core/event_bus.py.
 * If the backend adds/removes/renames an event type, this test should be
 * updated to match.
 */
const BACKEND_EVENT_TYPES = [
  "agent_speak",
  "agent_move",
  "agent_action",
  "alpha_dispatch",
  "alpha_return",
  "management_warning",
  "management_intervention",
  "management_shadow",
  "world_expansion",
  "poll_created",
  "poll_result",
  "budget_update",
  "viewer_count",
  "tts_play",
  "tool_executed",
  "config_reloaded",
  "agi_progress",
  "artifact_created",
] as const;

describe("EventType enum", () => {
  it("has all backend event types", () => {
    const frontendValues = Object.values(EventType);
    for (const backendType of BACKEND_EVENT_TYPES) {
      expect(frontendValues).toContain(backendType);
    }
  });

  it("has no extra event types beyond backend", () => {
    const frontendValues = Object.values(EventType);
    expect(frontendValues).toHaveLength(BACKEND_EVENT_TYPES.length);
  });

  it("has exactly 18 event types", () => {
    expect(Object.values(EventType)).toHaveLength(18);
  });
});
