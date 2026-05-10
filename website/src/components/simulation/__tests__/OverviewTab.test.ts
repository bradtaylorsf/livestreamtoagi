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
  });

  it("VideoPlayer renders the video element when src is provided", () => {
    const tree = VideoPlayer({ src: "https://example.com/run.mp4" });
    expect(findByTestId(tree as ReactElement, "video-player")).not.toBeNull();
    expect(findByTestId(tree as ReactElement, "video-player-empty")).toBeNull();
  });

  it("links the AgentList into simulation-scoped agent routes", () => {
    const sim = makeSim();
    const tree = OverviewTab({ sim, simulationId: sim.id });
    const agentList = flatten(tree).find((el) => el.type === AgentList);
    expect(agentList).toBeTruthy();
    expect(agentList?.props.linkPrefix).toBe(`/simulations/${sim.id}/agents`);
  });

  it("passes the configured effective roster before participation data exists", () => {
    const sim = makeSim({
      agents_participated: [],
      config: { effective_agents: ["vera", "rex", "aurora", "pixel"] },
    });
    const tree = OverviewTab({ sim, simulationId: sim.id });
    const agentList = flatten(tree).find((el) => el.type === AgentList);

    expect(agentList?.props.agents).toEqual(["vera", "rex", "aurora", "pixel"]);
    expect(agentList?.props.title).toBe("Effective Agent Roster");
  });
});
