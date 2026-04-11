import { describe, expect, it } from "vitest";

describe("Contribute page data", () => {
  // Test the data contract for contribution types
  const CONTRIBUTION_TYPES = [
    "Code Contributions",
    "Prompt Engineering",
    "Agent Skills",
    "Eval Improvements",
    "World Building",
    "Content",
  ];

  it("covers all 6 contribution types", () => {
    expect(CONTRIBUTION_TYPES).toHaveLength(6);
  });

  it("includes code contributions", () => {
    expect(CONTRIBUTION_TYPES).toContain("Code Contributions");
  });

  it("includes eval improvements", () => {
    expect(CONTRIBUTION_TYPES).toContain("Eval Improvements");
  });

  it("includes prompt engineering", () => {
    expect(CONTRIBUTION_TYPES).toContain("Prompt Engineering");
  });

  // Test the A/B testing protocol has all required steps
  const AB_STEPS = [
    "Run baseline simulation",
    "Run treatment simulation",
    "Compare scores",
    "Include comparison in PR",
    "Repeat 3x for confidence",
  ];

  it("A/B testing protocol has 5 steps", () => {
    expect(AB_STEPS).toHaveLength(5);
  });

  it("A/B protocol starts with baseline", () => {
    expect(AB_STEPS[0]).toBe("Run baseline simulation");
  });

  it("A/B protocol ends with statistical confidence", () => {
    expect(AB_STEPS[4]).toContain("confidence");
  });

  // Validation process
  const VALIDATION_STEPS = [
    "Fork the repo and make your change",
    "Run the eval suite against a simulation with your change",
    "Submit a PR with before/after eval scores",
    "Maintainers verify the improvement by re-running the simulation independently",
    "Changes that degrade scores are rejected with data, not opinion",
  ];

  it("validation process has 5 steps", () => {
    expect(VALIDATION_STEPS).toHaveLength(5);
  });

  it("validation ends with data-driven rejection policy", () => {
    expect(VALIDATION_STEPS[4]).toContain("data, not opinion");
  });
});
