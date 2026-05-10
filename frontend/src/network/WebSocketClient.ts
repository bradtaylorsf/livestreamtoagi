import type { ServerEvent } from "../types/events";

export type EventCallback = (event: ServerEvent) => void;

export const DEFAULT_WS_URL = "ws://localhost:8010/ws";
const INITIAL_BACKOFF_MS = 1000;
const MAX_BACKOFF_MS = 30000;
const BACKOFF_FACTOR = 2;

export function resolveWebSocketUrl(url?: string): string {
  return url ?? DEFAULT_WS_URL;
}

export class WebSocketClient {
  private ws: WebSocket | null = null;
  private url: string;
  private callbacks: EventCallback[] = [];
  private shouldReconnect = false;
  private backoffMs = INITIAL_BACKOFF_MS;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  /** Timestamp of the last event dispatched to subscribers (seconds, matches backend). */
  private lastEventTimestamp = 0;

  /** Called when the WebSocket connection opens. */
  onConnect: (() => void) | null = null;
  /** Called when the WebSocket connection closes (before reconnect scheduling). */
  onDisconnect: (() => void) | null = null;

  constructor(url: string = DEFAULT_WS_URL) {
    this.url = url;
  }

  connect(url?: string): void {
    if (url) this.url = url;
    this.shouldReconnect = true;
    this.backoffMs = INITIAL_BACKOFF_MS;
    this._connect();
  }

  disconnect(): void {
    this.shouldReconnect = false;
    if (this.reconnectTimer !== null) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    if (this.ws) {
      this.ws.close();
      this.ws = null;
    }
  }

  onEvent(callback: EventCallback): () => void {
    this.callbacks.push(callback);
    return () => {
      this.callbacks = this.callbacks.filter((cb) => cb !== callback);
    };
  }

  get connected(): boolean {
    return this.ws?.readyState === WebSocket.OPEN;
  }

  get currentBackoff(): number {
    return this.backoffMs;
  }

  private _connect(): void {
    if (this.ws) {
      this.ws.close();
      this.ws = null;
    }

    this.ws = new WebSocket(this.url);

    this.ws.onmessage = (event: MessageEvent) => {
      try {
        const parsed = JSON.parse(event.data);

        // Handle history batch from backend.
        // On reconnect the backend replays its full buffer; we skip any events
        // already seen (timestamp <= lastEventTimestamp) to avoid duplicates.
        if (parsed.type === "history" && Array.isArray(parsed.events)) {
          const cutoff = this.lastEventTimestamp;
          for (const evt of parsed.events) {
            const e = evt as ServerEvent;
            if (e.timestamp > cutoff) {
              this._dispatch(e);
            }
          }
          return;
        }

        this._dispatch(parsed as ServerEvent);
      } catch {
        // Ignore malformed messages
      }
    };

    this.ws.onopen = () => {
      this.backoffMs = INITIAL_BACKOFF_MS;
      this.onConnect?.();
    };

    this.ws.onclose = () => {
      this.ws = null;
      this.onDisconnect?.();
      this._scheduleReconnect();
    };

    this.ws.onerror = () => {
      // onclose will fire after onerror, triggering reconnect
    };
  }

  private _dispatch(event: ServerEvent): void {
    if (event.timestamp > this.lastEventTimestamp) {
      this.lastEventTimestamp = event.timestamp;
    }
    for (const cb of this.callbacks) {
      cb(event);
    }
  }

  private _scheduleReconnect(): void {
    if (!this.shouldReconnect) return;

    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      this._connect();
    }, this.backoffMs);

    this.backoffMs = Math.min(this.backoffMs * BACKOFF_FACTOR, MAX_BACKOFF_MS);
  }
}
