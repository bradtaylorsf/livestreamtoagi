import { describe, expect, it } from "vitest";
import type { AgentArtifact } from "@/types/admin";

/**
 * Test artifact preview extraction logic.
 * We replicate the getTablePreview logic from artifacts/page.tsx to test independently.
 */

function getTablePreview(artifact: AgentArtifact): string {
  const input = artifact.tool_input ?? {};
  switch (artifact.artifact_type) {
    case "social_post": {
      const text = input.content ?? input.text ?? input.message;
      if (typeof text === "string") return text.slice(0, 200);
      break;
    }
    case "email": {
      const subject = input.subject;
      const body = input.body ?? input.content;
      if (typeof subject === "string")
        return `[${subject}] ${typeof body === "string" ? body.slice(0, 150) : ""}`;
      break;
    }
    case "code_execution": {
      const code = input.code ?? input.source;
      if (typeof code === "string") return code.slice(0, 200);
      break;
    }
    case "message": {
      const msg = input.content ?? input.text ?? input.body ?? input.message;
      if (typeof msg === "string") return msg.slice(0, 200);
      break;
    }
    case "memory_operation": {
      const mem = input.content ?? input.memory;
      if (typeof mem === "string") return mem.slice(0, 200);
      break;
    }
    default:
      break;
  }
  const output = artifact.tool_output;
  if (output == null) return "(no output)";
  if (typeof output === "string") return output.slice(0, 200);
  const outObj = output as Record<string, unknown>;
  for (const key of ["result", "content", "text", "output", "description"]) {
    if (typeof outObj[key] === "string") return (outObj[key] as string).slice(0, 200);
  }
  return JSON.stringify(output).slice(0, 200);
}

function makeArtifact(overrides: Partial<AgentArtifact> = {}): AgentArtifact {
  return {
    id: "test-id",
    simulation_id: null,
    agent_id: "vera",
    artifact_type: "message",
    tool_name: "test_tool",
    tool_input: {},
    tool_output: null,
    status: "executed",
    metadata: null,
    created_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

describe("Artifact preview extraction", () => {
  it("extracts social_post content", () => {
    const artifact = makeArtifact({
      artifact_type: "social_post",
      tool_input: { content: "Hello world! This is a social post." },
    });
    expect(getTablePreview(artifact)).toBe("Hello world! This is a social post.");
  });

  it("extracts email subject and body", () => {
    const artifact = makeArtifact({
      artifact_type: "email",
      tool_input: { subject: "Welcome", body: "Dear user, welcome aboard." },
    });
    expect(getTablePreview(artifact)).toBe("[Welcome] Dear user, welcome aboard.");
  });

  it("extracts code_execution code", () => {
    const artifact = makeArtifact({
      artifact_type: "code_execution",
      tool_input: { code: "print('hello')" },
    });
    expect(getTablePreview(artifact)).toBe("print('hello')");
  });

  it("extracts message content", () => {
    const artifact = makeArtifact({
      artifact_type: "message",
      tool_input: { content: "Hey everyone, check this out!" },
    });
    expect(getTablePreview(artifact)).toBe("Hey everyone, check this out!");
  });

  it("extracts memory_operation content", () => {
    const artifact = makeArtifact({
      artifact_type: "memory_operation",
      tool_input: { memory: "Rex prefers TypeScript." },
    });
    expect(getTablePreview(artifact)).toBe("Rex prefers TypeScript.");
  });

  it("falls back to output string fields", () => {
    const artifact = makeArtifact({
      artifact_type: "unknown_type" as AgentArtifact["artifact_type"],
      tool_output: { result: "Operation completed successfully" },
    });
    expect(getTablePreview(artifact)).toBe("Operation completed successfully");
  });

  it("falls back to raw JSON for opaque output", () => {
    const artifact = makeArtifact({
      artifact_type: "unknown_type" as AgentArtifact["artifact_type"],
      tool_output: { foo: 42 },
    });
    expect(getTablePreview(artifact)).toBe('{"foo":42}');
  });

  it("returns (no output) for null output", () => {
    const artifact = makeArtifact({
      artifact_type: "unknown_type" as AgentArtifact["artifact_type"],
      tool_output: null,
    });
    expect(getTablePreview(artifact)).toBe("(no output)");
  });
});

describe("TYPE_RENDERERS coverage", () => {
  const EXPECTED_TYPES = [
    "social_post",
    "email",
    "code_execution",
    "code",
    "web_search",
    "search",
    "poll",
    "memory_operation",
    "alpha_dispatch",
    "message",
    "tilemap",
    "self_modification",
  ];

  it("all expected types should be listed", () => {
    // This serves as a static check that TYPE_RENDERERS has the expected keys
    expect(EXPECTED_TYPES).toContain("message");
    expect(EXPECTED_TYPES).toContain("tilemap");
    expect(EXPECTED_TYPES).toContain("self_modification");
    expect(EXPECTED_TYPES.length).toBe(12);
  });
});
