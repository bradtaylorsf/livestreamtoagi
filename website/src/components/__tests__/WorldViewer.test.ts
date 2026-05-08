import { readFileSync } from "fs";
import { resolve } from "path";
import { describe, expect, it } from "vitest";
import type { WorldChunk } from "@/types";

// Read the source for content assertions (node env, no jsdom).
const SOURCE = readFileSync(
  resolve(__dirname, "../WorldViewer.tsx"),
  "utf8",
);

// Mirror of the inferChunkType heuristic in WorldViewer.tsx so we can
// test the grouping rules without rendering React.
function inferChunkType(chunk: WorldChunk): string {
  const name = (chunk.name ?? "").toLowerCase();
  if (name.includes("room") || name.includes("office") || name.includes("hall"))
    return "room";
  if (name.includes("decoration") || name.includes("plant"))
    return "decoration";
  const objectTypes = (chunk.objects ?? []).map((o) => o.type);
  if (objectTypes.some((t) => t.includes("desk") || t.includes("wall"))) {
    return "room";
  }
  if (objectTypes.length > 0) return "decoration";
  return "other";
}

function makeChunk(overrides: Partial<WorldChunk> = {}): WorldChunk {
  return {
    id: "chunk-1",
    name: null,
    x: 0,
    y: 0,
    width: 10,
    height: 10,
    tiles: [],
    objects: [],
    ...overrides,
  };
}

describe("WorldViewer chunk type inference", () => {
  it("classifies named rooms as 'room'", () => {
    expect(inferChunkType(makeChunk({ name: "The Office" }))).toBe("room");
    expect(inferChunkType(makeChunk({ name: "Server Room" }))).toBe("room");
    expect(inferChunkType(makeChunk({ name: "Main Hall" }))).toBe("room");
  });

  it("classifies decoration chunks by name", () => {
    expect(inferChunkType(makeChunk({ name: "Plant cluster" }))).toBe(
      "decoration",
    );
    expect(inferChunkType(makeChunk({ name: "Decoration set" }))).toBe(
      "decoration",
    );
  });

  it("falls back to objects when name is null", () => {
    expect(
      inferChunkType(
        makeChunk({
          objects: [{ id: "1", type: "desk", x: 0, y: 0, properties: {} }],
        }),
      ),
    ).toBe("room");
    expect(
      inferChunkType(
        makeChunk({
          objects: [{ id: "1", type: "plant", x: 0, y: 0, properties: {} }],
        }),
      ),
    ).toBe("decoration");
  });

  it("returns 'other' for empty unnamed chunks", () => {
    expect(inferChunkType(makeChunk())).toBe("other");
  });
});

describe("WorldViewer rendered structure", () => {
  it("does not include the old 'coming soon' copy", () => {
    expect(SOURCE).not.toMatch(/Live Phaser\.js world viewer coming soon/i);
    expect(SOURCE).not.toMatch(/world viewer coming soon/i);
  });

  it("renders chunks via getWorldChunks API", () => {
    expect(SOURCE).toMatch(/getWorldChunks/);
  });

  it("renders recent world events via getLore API", () => {
    expect(SOURCE).toMatch(/getLore/);
  });

  it("explains the empty-state path forward", () => {
    expect(SOURCE).toMatch(/agents have not built anything yet/i);
  });

  it("uses the WorldChunk.name field", () => {
    expect(SOURCE).toMatch(/chunk\.name/);
  });
});
