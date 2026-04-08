// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { SpeechBubble, type SpeechBubbleOptions } from "./SpeechBubble";

describe("SpeechBubble", () => {
  let container: HTMLDivElement;

  beforeEach(() => {
    vi.useFakeTimers();
    container = document.createElement("div");
    document.body.appendChild(container);
  });

  afterEach(() => {
    vi.useRealTimers();
    container.remove();
  });

  function createBubble(overrides: Partial<SpeechBubbleOptions> = {}): SpeechBubble {
    return new SpeechBubble({
      agentId: "vera",
      text: "Hello world",
      tone: "casual",
      duration: 5000,
      container,
      ...overrides,
    });
  }

  it("creates a DOM element in the container", () => {
    const bubble = createBubble();
    expect(container.children.length).toBe(1);
    expect(container.children[0]).toBe(bubble.getElement());
    bubble.destroy();
  });

  it("applies casual tone class", () => {
    const bubble = createBubble({ tone: "casual" });
    expect(bubble.getElement().classList.contains("bubble-casual")).toBe(true);
    bubble.destroy();
  });

  it("applies urgent tone class", () => {
    const bubble = createBubble({ tone: "urgent" });
    expect(bubble.getElement().classList.contains("bubble-urgent")).toBe(true);
    bubble.destroy();
  });

  it("applies dramatic tone class", () => {
    const bubble = createBubble({ tone: "dramatic" });
    expect(bubble.getElement().classList.contains("bubble-dramatic")).toBe(true);
    bubble.destroy();
  });

  it("applies sarcastic tone class", () => {
    const bubble = createBubble({ tone: "sarcastic" });
    expect(bubble.getElement().classList.contains("bubble-sarcastic")).toBe(true);
    bubble.destroy();
  });

  it("positions bubble at given coordinates", () => {
    const bubble = createBubble();
    bubble.updatePosition(100, 200);
    expect(bubble.getElement().style.left).toBe("100px");
    expect(bubble.getElement().style.top).toBe("200px");
    bubble.destroy();
  });

  describe("typewriter effect", () => {
    it("starts with empty text", () => {
      const bubble = createBubble({ text: "Hello" });
      expect(bubble.getDisplayedText()).toBe("");
      bubble.destroy();
    });

    it("reveals characters one by one", () => {
      const bubble = createBubble({ text: "Hi" });
      vi.advanceTimersByTime(SpeechBubble.CHAR_DELAY_MS);
      expect(bubble.getDisplayedText()).toBe("H");
      vi.advanceTimersByTime(SpeechBubble.CHAR_DELAY_MS);
      expect(bubble.getDisplayedText()).toBe("Hi");
      bubble.destroy();
    });

    it("completes in expected time", () => {
      const text = "Hello world";
      const bubble = createBubble({ text });
      const expectedTime = text.length * SpeechBubble.CHAR_DELAY_MS;
      vi.advanceTimersByTime(expectedTime);
      expect(bubble.getDisplayedText()).toBe(text);
      bubble.destroy();
    });
  });

  describe("auto-dismiss", () => {
    it("auto-dismisses after specified duration", () => {
      const bubble = createBubble({ duration: 3000 });
      expect(bubble.dismissed).toBe(false);
      vi.advanceTimersByTime(3000);
      expect(bubble.dismissed).toBe(true);
      bubble.destroy();
    });

    it("removes element from DOM after fade", () => {
      const bubble = createBubble({ duration: 1000 });
      vi.advanceTimersByTime(1000); // trigger dismiss
      vi.advanceTimersByTime(SpeechBubble.FADE_DURATION_MS); // fade completes
      expect(container.children.length).toBe(0);
    });

    it("sets opacity to 0 on dismiss", () => {
      const bubble = createBubble({ duration: 1000 });
      vi.advanceTimersByTime(1000);
      expect(bubble.getElement().style.opacity).toBe("0");
      bubble.destroy();
    });
  });

  describe("dismiss()", () => {
    it("is idempotent", () => {
      const bubble = createBubble();
      bubble.dismiss();
      bubble.dismiss(); // should not throw
      expect(bubble.dismissed).toBe(true);
      bubble.destroy();
    });
  });

  describe("alpha agent", () => {
    it("uses emoji instead of text", () => {
      const bubble = createBubble({
        agentId: "alpha",
        text: "Fetch the package now!",
        isAlpha: true,
      });
      expect(bubble.getElement().classList.contains("bubble-alpha")).toBe(true);
      // Should contain emoji characters, not original text
      expect(bubble.getDisplayedText()).not.toBe("Fetch the package now!");
      expect(bubble.getDisplayedText().length).toBeGreaterThan(0);
      bubble.destroy();
    });

    it("does not use typewriter effect", () => {
      const bubble = createBubble({
        agentId: "alpha",
        text: "Short",
        isAlpha: true,
      });
      // Text should be set immediately (no typewriter)
      expect(bubble.getDisplayedText().length).toBeGreaterThan(0);
      bubble.destroy();
    });
  });

  describe("convertToEmoji", () => {
    it("returns emoji symbols based on text length", () => {
      const short = SpeechBubble.convertToEmoji("Hi");
      const long = SpeechBubble.convertToEmoji("This is a much longer message for the wolf");
      expect(short.length).toBeGreaterThan(0);
      expect(long.length).toBeGreaterThan(short.length);
    });

    it("caps at 5 emoji", () => {
      const veryLong = SpeechBubble.convertToEmoji("a".repeat(200));
      // 5 emoji characters (each is 2 code units for surrogate pairs)
      const emojiCount = [...veryLong].length;
      expect(emojiCount).toBeLessThanOrEqual(5);
    });
  });

  it("cleans up on destroy", () => {
    const bubble = createBubble();
    expect(container.children.length).toBe(1);
    bubble.destroy();
    expect(container.children.length).toBe(0);
  });
});
