import { readFileSync } from "fs";
import { resolve } from "path";
import { describe, expect, it } from "vitest";

const DETAIL_PAGE_SOURCE = readFileSync(
  resolve(__dirname, "../simulations/[id]/page.tsx"),
  "utf8",
);
const NEXT_CONFIG_SOURCE = readFileSync(
  resolve(__dirname, "../../../next.config.ts"),
  "utf8",
);

describe("simulation detail video status wiring", () => {
  it("polls simulation detail while run or render state can still change", () => {
    expect(DETAIL_PAGE_SOURCE).toContain("function shouldPollSimulation");
    expect(DETAIL_PAGE_SOURCE).toContain('sim.status === "queued"');
    expect(DETAIL_PAGE_SOURCE).toContain('sim.status === "running"');
    expect(DETAIL_PAGE_SOURCE).toContain('sim.status === "failed"');
    expect(DETAIL_PAGE_SOURCE).toContain(
      'sim.video_render_status === "pending"',
    );
    expect(DETAIL_PAGE_SOURCE).toContain(
      'sim.video_render_status === "rendering"',
    );
    expect(DETAIL_PAGE_SOURCE).toContain("window.setInterval");
    expect(DETAIL_PAGE_SOURCE).toMatch(/5_000|5000/);
  });

  it("rewrites website /videos paths to the backend", () => {
    expect(NEXT_CONFIG_SOURCE).toContain('source: "/videos/:path*"');
    expect(NEXT_CONFIG_SOURCE).toContain(
      'destination: `${apiUrl}/videos/:path*`',
    );
  });
});
