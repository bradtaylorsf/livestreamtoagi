import { describe, expect, it } from "vitest";
import OverviewTab from "../OverviewTab";
import AgentList from "../AgentList";
import SummaryGrid from "../SummaryGrid";
import VideoPlayer from "../VideoPlayer";
import type { PublicSimulationDetail } from "@/lib/api";

type ReactElement = {
  type: unknown;
  props: Record<string, unknown> & { children?: unknown };
};

function isElement(node: unknown): node is ReactElement {
  return Boolean(
    node && typeof node === "object" && "props" in node && "type" in node,
  );
}

function flatten(node: unknown, out: ReactElement[] = []): ReactElement[] {
  if (Array.isArray(node)) {
    for (const child of node) flatten(child, out);
    return out;
  }
  if (!isElement(node)) return out;
  out.push(node);
  flatten(node.props.children, out);
  return out;
}

function findByTestId(root: ReactElement, testId: string): ReactElement | null {
  for (const el of flatten(root)) {
    if (el.props["data-testid"] === testId) return el;
  }
  return null;
}

function makeSim(
  over: Partial<PublicSimulationDetail> = {},
): PublicSimulationDetail {
  const base: PublicSimulationDetail = {
    id: "sim-1",
    name: "My run",
    description: null,
    status: "completed",
    started_at: null,
    completed_at: null,
    real_duration: null,
    total_conversations: 4,
    total_turns: 12,
    total_cost: "0.5",
    total_artifacts: 0,
    agents_participated: ["vera", "rex"],
    is_featured: false,
    video_url: null,
    video_render_status: null,
    video_rendered_at: null,
    video_render_failure_reason: null,
    video_render_cancellation_reason: null,
    submitter_display_name: null,
    config: {},
    simulated_duration: null,
    total_tokens: 0,
    total_management_flags: 0,
    hypothesis: null,
    outcomes: null,
    learnings: null,
    factions: null,
  };
  return { ...base, ...over };
}

describe("OverviewTab", () => {
  it("renders both SummaryGrid and AgentList components", () => {
    const sim = makeSim();
    const tree = OverviewTab({ sim, simulationId: sim.id });
    const elements = flatten(tree);
    expect(elements.some((el) => el.type === SummaryGrid)).toBe(true);
    expect(elements.some((el) => el.type === AgentList)).toBe(true);
  });

  it("shows the hypothesis preview when set", () => {
    const sim = makeSim({ hypothesis: "Aurora keeps the energy up." });
    const tree = OverviewTab({ sim, simulationId: sim.id });
    const node = findByTestId(tree as ReactElement, "overview-hypothesis");
    expect(node).not.toBeNull();
    expect(String(node?.props.children)).toBe("Aurora keeps the energy up.");
  });

  it("passes video_url to the embedded VideoPlayer", () => {
    const sim = makeSim({ video_url: "https://example.com/run.mp4" });
    const tree = OverviewTab({ sim, simulationId: sim.id });
    const player = flatten(tree).find((el) => el.type === VideoPlayer);
    expect(player).toBeTruthy();
    expect(player?.props.src).toBe("https://example.com/run.mp4");
  });

  it("passes render status detail to the embedded VideoPlayer", () => {
    const sim = makeSim({
      video_render_status: "failed",
      video_render_failure_reason: "Playwright timed out",
    });
    const tree = OverviewTab({ sim, simulationId: sim.id });
    const player = flatten(tree).find((el) => el.type === VideoPlayer);
    expect(player?.props.renderStatus).toBe("failed");
    expect(player?.props.failureReason).toBe("Playwright timed out");
  });

  it("still renders VideoPlayer when video_url is null (component handles empty state)", () => {
    const sim = makeSim({ video_url: null });
    const tree = OverviewTab({ sim, simulationId: sim.id });
    const player = flatten(tree).find((el) => el.type === VideoPlayer);
    expect(player).toBeTruthy();
    expect(player?.props.src).toBeNull();
  });

  it("VideoPlayer renders the empty placeholder when src is null", () => {
    const tree = VideoPlayer({ src: null });
    expect(findByTestId(tree as ReactElement, "video-player-empty")).not.toBeNull();
    expect(findByTestId(tree as ReactElement, "video-player")).toBeNull();
    expect(findByTestId(tree as ReactElement, "video-player-empty")?.props[
      "data-state"
    ]).toBe("none");
  });

  it("VideoPlayer renders the video element when src is provided", () => {
    const tree = VideoPlayer({
      src: "https://example.com/run.mp4",
      renderStatus: "done",
    });
    expect(findByTestId(tree as ReactElement, "video-player")).not.toBeNull();
    expect(findByTestId(tree as ReactElement, "video-player-empty")).toBeNull();
  });

  it("VideoPlayer shows the rendering state", () => {
    const tree = VideoPlayer({ src: null, renderStatus: "rendering" });
    expect(findByTestId(tree as ReactElement, "video-player-empty")?.props[
      "data-state"
    ]).toBe("rendering");
  });

  it("VideoPlayer shows failure detail when render fails", () => {
    const tree = VideoPlayer({
      src: null,
      renderStatus: "failed",
      failureReason: "ffmpeg exited",
    });
    const empty = findByTestId(tree as ReactElement, "video-player-empty");
    expect(empty?.props["data-state"]).toBe("failed");
    expect(JSON.stringify(empty?.props.children)).toContain("ffmpeg exited");
  });

  it("VideoPlayer shows skipped renders separately from failures", () => {
    const tree = VideoPlayer({
      src: null,
      renderStatus: "skipped",
      failureReason: "No transcript cues were available to render.",
    });
    expect(findByTestId(tree as ReactElement, "video-player-empty")?.props[
      "data-state"
    ]).toBe("skipped");
  });

  it("VideoPlayer shows cancelled and cost-limited runs", () => {
    const tree = VideoPlayer({
      src: null,
      simulationStatus: "cancelled",
      cancellationReason: "Cost limit reached after $1.23.",
    });
    const empty = findByTestId(tree as ReactElement, "video-player-empty");
    expect(empty?.props["data-state"]).toBe("cancelled");
    expect(JSON.stringify(empty?.props.children)).toContain("Cost limit");
  });

  it("VideoPlayer distinguishes done-without-url from no render yet", () => {
    const tree = VideoPlayer({ src: null, renderStatus: "done" });
    expect(findByTestId(tree as ReactElement, "video-player-empty")?.props[
      "data-state"
    ]).toBe("done-missing");
  });

  it("links the AgentList into simulation-scoped agent routes", () => {
    const sim = makeSim();
    const tree = OverviewTab({ sim, simulationId: sim.id });
    const agentList = flatten(tree).find((el) => el.type === AgentList);
    expect(agentList).toBeTruthy();
    expect(agentList?.props.linkPrefix).toBe(`/simulations/${sim.id}/agents`);
  });
});
