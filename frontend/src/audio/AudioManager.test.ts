// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { AudioManager } from "./AudioManager";
import { EventType } from "../types/events";

function createMockWsClient() {
  const callbacks: Array<(event: any) => void> = [];
  return {
    onEvent: vi.fn((cb: (event: any) => void) => {
      callbacks.push(cb);
      return () => {
        const idx = callbacks.indexOf(cb);
        if (idx >= 0) callbacks.splice(idx, 1);
      };
    }),
    emit: (event: any) => {
      for (const cb of callbacks) cb(event);
    },
  };
}

// Mock HTMLAudioElement since jsdom doesn't support audio playback
class MockAudio {
  src = "";
  volume = 1;
  duration = 3;
  private eventListeners: Record<string, Function[]> = {};

  addEventListener(event: string, cb: Function) {
    if (!this.eventListeners[event]) this.eventListeners[event] = [];
    this.eventListeners[event].push(cb);
  }

  removeEventListener(event: string, cb: Function) {
    if (this.eventListeners[event]) {
      this.eventListeners[event] = this.eventListeners[event].filter((f) => f !== cb);
    }
  }

  play() {
    // Simulate immediate playback completion
    setTimeout(() => this.triggerEvent("ended"), 10);
    return Promise.resolve();
  }

  pause() {}

  triggerEvent(event: string) {
    for (const cb of this.eventListeners[event] || []) {
      cb();
    }
  }
}

describe("AudioManager", () => {
  let manager: AudioManager;
  let wsClient: ReturnType<typeof createMockWsClient>;
  let originalAudio: typeof Audio;

  beforeEach(() => {
    vi.useFakeTimers();
    originalAudio = globalThis.Audio;
    globalThis.Audio = MockAudio as any;
    wsClient = createMockWsClient();
    manager = new AudioManager(wsClient as any);
  });

  afterEach(() => {
    manager.destroy();
    vi.useRealTimers();
    globalThis.Audio = originalAudio;
  });

  it("subscribes to WebSocket events", () => {
    expect(wsClient.onEvent).toHaveBeenCalledTimes(1);
  });

  it("starts with empty queue", () => {
    expect(manager.getQueueLength()).toBe(0);
    expect(manager.isCurrentlyPlaying()).toBe(false);
  });

  it("enqueues and plays audio", async () => {
    const promise = manager.enqueue("vera", "http://audio.test/vera.mp3", "Hello world");
    expect(manager.getQueueLength()).toBe(1);
    expect(manager.isCurrentlyPlaying()).toBe(true);
    vi.advanceTimersByTime(50);
    await promise;
    expect(manager.isCurrentlyPlaying()).toBe(false);
  });

  it("queues multiple items in FIFO order", () => {
    manager.enqueue("vera", "http://audio.test/1.mp3", "First");
    manager.enqueue("rex", "http://audio.test/2.mp3", "Second");
    manager.enqueue("aurora", "http://audio.test/3.mp3", "Third");
    // First is playing, 2 and 3 are in queue
    expect(manager.isCurrentlyPlaying()).toBe(true);
    expect(manager.getQueueLength()).toBe(3);
  });

  it("alpha produces no audio (silent)", async () => {
    const promise = manager.enqueue("alpha", "http://audio.test/alpha.mp3", "Woof");
    // Should resolve immediately without adding to queue
    await promise;
    expect(manager.getQueueLength()).toBe(0);
    expect(manager.isCurrentlyPlaying()).toBe(false);
  });

  it("handles audio load failure gracefully", async () => {
    // Override mock to trigger error instead of ended
    globalThis.Audio = class extends MockAudio {
      play() {
        setTimeout(() => this.triggerEvent("error"), 10);
        return Promise.resolve();
      }
    } as any;

    const newManager = new AudioManager(null);
    const promise = newManager.enqueue("vera", "http://bad-url.test/fail.mp3", "Hello");
    vi.advanceTimersByTime(50);
    await promise;
    // Should not throw, just resolve
    expect(newManager.isCurrentlyPlaying()).toBe(false);
    newManager.destroy();
  });

  describe("volume control", () => {
    it("defaults master volume to 1.0", () => {
      expect(manager.getMasterVolume()).toBe(1.0);
    });

    it("sets master volume clamped to 0-1", () => {
      manager.setMasterVolume(0.5);
      expect(manager.getMasterVolume()).toBe(0.5);
      manager.setMasterVolume(2);
      expect(manager.getMasterVolume()).toBe(1);
      manager.setMasterVolume(-1);
      expect(manager.getMasterVolume()).toBe(0);
    });

    it("defaults agent volume to 0.8", () => {
      expect(manager.getAgentVolume("vera")).toBe(0.8);
    });

    it("alpha has 0 volume by default", () => {
      expect(manager.getAgentVolume("alpha")).toBe(0);
    });

    it("management has 1.0 volume by default (louder than 0.8 default)", () => {
      expect(manager.getAgentVolume("management")).toBe(1.0);
    });

    it("allows setting per-agent volume", () => {
      manager.setAgentVolume("vera", 0.7);
      expect(manager.getAgentVolume("vera")).toBe(0.7);
    });
  });

  it("handles TTS_PLAY WebSocket events", () => {
    wsClient.emit({
      event_id: "1",
      event_type: EventType.TTS_PLAY,
      timestamp: Date.now(),
      data: { agent_id: "vera", audio_url: "http://audio.test/vera.mp3", text: "Hello" },
    });
    expect(manager.getQueueLength()).toBe(1);
    expect(manager.isCurrentlyPlaying()).toBe(true);
  });

  it("ignores non-TTS events", () => {
    wsClient.emit({
      event_id: "2",
      event_type: EventType.AGENT_SPEAK,
      timestamp: Date.now(),
      data: { agent_id: "vera", text: "Hello" },
    });
    expect(manager.getQueueLength()).toBe(0);
  });

  it("getDuration returns fallback for silent agents", async () => {
    const duration = await manager.getDuration("alpha", "http://audio.test/alpha.mp3", "Hello");
    // text.length * 50 = 5 * 50 = 250, but clamped to min 2000
    expect(duration).toBe(2000);
  });

  it("destroy clears queue and stops playback", () => {
    manager.enqueue("vera", "http://audio.test/1.mp3", "First");
    manager.enqueue("rex", "http://audio.test/2.mp3", "Second");
    manager.destroy();
    expect(manager.getQueueLength()).toBe(0);
    expect(manager.isCurrentlyPlaying()).toBe(false);
  });

  it("works without WebSocket client", () => {
    const standalone = new AudioManager(null);
    standalone.enqueue("vera", "http://audio.test/1.mp3", "Hello");
    expect(standalone.getQueueLength()).toBe(1);
    standalone.destroy();
  });
});
