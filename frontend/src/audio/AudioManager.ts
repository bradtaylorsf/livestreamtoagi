import { EventType, type ServerEvent } from "../types/events";
import type { WebSocketClient } from "../network/WebSocketClient";

interface QueueItem {
  agentId: string;
  audioUrl: string;
  text: string;
  resolve: () => void;
}

const DEFAULT_AGENT_VOLUME = 0.8;

const DEFAULT_AGENT_VOLUMES: Record<string, number> = {
  alpha: 0,
  management: 1.0,
};

/** Fallback duration (ms) when audio metadata cannot be loaded. */
function fallbackDuration(text: string): number {
  return Math.max(2000, Math.min(10000, text.length * 50));
}

export class AudioManager {
  private queue: QueueItem[] = [];
  private currentAudio: HTMLAudioElement | null = null;
  private _isPlaying = false;
  private masterVolume = 1.0;
  private agentVolumes: Map<string, number> = new Map();
  private unsubscribe: (() => void) | null = null;

  constructor(wsClient: WebSocketClient | null) {
    // Set default per-agent volumes
    for (const [id, vol] of Object.entries(DEFAULT_AGENT_VOLUMES)) {
      this.agentVolumes.set(id, vol);
    }

    if (wsClient) {
      this.unsubscribe = wsClient.onEvent((event) => this.handleEvent(event));
    }
  }

  /** Enqueue an audio URL for playback. Returns a promise that resolves when playback finishes. */
  enqueue(agentId: string, audioUrl: string, text: string): Promise<void> {
    return new Promise((resolve) => {
      // Alpha is silent — resolve immediately
      if (this.getEffectiveVolume(agentId) === 0) {
        resolve();
        return;
      }

      this.queue.push({ agentId, audioUrl, text, resolve });
      this.processQueue();
    });
  }

  /**
   * Get the expected duration of an audio file in milliseconds.
   * Falls back to a text-length-based estimate if the audio cannot be loaded.
   */
  getDuration(agentId: string, audioUrl: string, text: string): Promise<number> {
    // Silent agents — use text-based fallback
    if (this.getEffectiveVolume(agentId) === 0) {
      return Promise.resolve(fallbackDuration(text));
    }

    return new Promise((resolve) => {
      const audio = new Audio();

      const cleanup = () => {
        audio.removeEventListener("loadedmetadata", onLoaded);
        audio.removeEventListener("error", onError);
        audio.src = "";
      };

      const onLoaded = () => {
        const durationMs = audio.duration * 1000;
        cleanup();
        resolve(durationMs);
      };

      const onError = () => {
        cleanup();
        resolve(fallbackDuration(text));
      };

      audio.addEventListener("loadedmetadata", onLoaded);
      audio.addEventListener("error", onError);
      audio.src = audioUrl;
    });
  }

  setMasterVolume(vol: number): void {
    this.masterVolume = Math.max(0, Math.min(1, vol));
    if (this.currentAudio) {
      const agentId = this.queue[0]?.agentId;
      if (agentId) {
        this.currentAudio.volume = this.getEffectiveVolume(agentId);
      }
    }
  }

  setAgentVolume(agentId: string, vol: number): void {
    this.agentVolumes.set(agentId, vol);
  }

  getMasterVolume(): number {
    return this.masterVolume;
  }

  getAgentVolume(agentId: string): number {
    return this.agentVolumes.get(agentId) ?? DEFAULT_AGENT_VOLUME;
  }

  getQueueLength(): number {
    return this.queue.length;
  }

  isCurrentlyPlaying(): boolean {
    return this._isPlaying;
  }

  destroy(): void {
    if (this.unsubscribe) {
      this.unsubscribe();
      this.unsubscribe = null;
    }
    if (this.currentAudio) {
      this.currentAudio.pause();
      this.currentAudio.src = "";
      this.currentAudio = null;
    }
    // Resolve all pending items
    for (const item of this.queue) {
      item.resolve();
    }
    this.queue = [];
    this._isPlaying = false;
  }

  private getEffectiveVolume(agentId: string): number {
    const agentVol = this.agentVolumes.get(agentId) ?? DEFAULT_AGENT_VOLUME;
    return Math.max(0, Math.min(1, this.masterVolume * agentVol));
  }

  private processQueue(): void {
    if (this._isPlaying || this.queue.length === 0) return;

    const item = this.queue[0];
    this._isPlaying = true;

    const audio = new Audio();
    this.currentAudio = audio;

    audio.volume = this.getEffectiveVolume(item.agentId);

    const finish = () => {
      audio.removeEventListener("ended", onEnded);
      audio.removeEventListener("error", onError);
      audio.src = "";
      this.currentAudio = null;
      this._isPlaying = false;
      this.queue.shift();
      item.resolve();
      this.processQueue();
    };

    const onEnded = () => finish();
    const onError = () => {
      console.warn(`Audio load failed for agent ${item.agentId}: ${item.audioUrl}`);
      finish();
    };

    audio.addEventListener("ended", onEnded);
    audio.addEventListener("error", onError);
    audio.src = item.audioUrl;
    audio.play().catch(() => {
      // Autoplay blocked or other error — gracefully skip
      finish();
    });
  }

  private handleEvent(event: ServerEvent): void {
    if (event.event_type === EventType.TTS_PLAY) {
      const { agent_id, audio_url, text } = event.data as {
        agent_id: string;
        audio_url: string;
        text: string;
      };
      this.enqueue(agent_id, audio_url, text);
    }
  }
}
