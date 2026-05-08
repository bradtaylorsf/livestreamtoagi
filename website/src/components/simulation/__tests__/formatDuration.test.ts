import { describe, it, expect } from "vitest";
import { formatDuration } from "../formatDuration";

describe("formatDuration", () => {
  it("returns em-dash for null", () => {
    expect(formatDuration(null)).toBe("—");
  });

  it("formats plain-second strings", () => {
    expect(formatDuration("0")).toBe("0s");
    expect(formatDuration("45")).toBe("45s");
    expect(formatDuration("90")).toBe("1m 30s");
    expect(formatDuration("3600")).toBe("1h 0m");
    expect(formatDuration("3650.5")).toBe("1h 0m");
  });

  it("formats Python timedelta repr (H:MM:SS[.fff])", () => {
    // Regression: parseFloat("1:00:50.96") == 1, so a 1-hour run rendered "1s".
    expect(formatDuration("1:00:50.963068")).toBe("1h 0m");
    expect(formatDuration("0:31:45.849557")).toBe("31m 46s");
    expect(formatDuration("0:00:45")).toBe("45s");
    expect(formatDuration("2:15:00")).toBe("2h 15m");
  });

  it("formats Python timedelta with days", () => {
    expect(formatDuration("1 day, 2:00:00")).toBe("26h 0m");
    expect(formatDuration("2 days, 0:30:00")).toBe("48h 30m");
  });

  it("returns the raw string for unrecognized input", () => {
    expect(formatDuration("forever")).toBe("forever");
  });
});
