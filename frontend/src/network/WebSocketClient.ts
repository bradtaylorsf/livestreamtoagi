import type { ServerEvent } from "../types/events";

export type EventCallback = (event: ServerEvent) => void;

const DEFAULT_URL = "ws://localhost:8000/ws";
const INITIAL_BACKOFF_MS = 1000;
const MAX_BACKOFF_MS = 30000;
const BACKOFF_FACTOR = 2;

export class WebSocketClient {
  private ws: WebSocket | null = null;
  private url: string;
  private callbacks: EventCallback[] = [];
  private shouldReconnect = false;
  private backoffMs = INITIAL_BACKOFF_MS;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;

  constructor(url: string = DEFAULT_URL) {
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

        // Handle history batch from backend
        if (parsed.type === "history" && Array.isArray(parsed.events)) {
          for (const evt of parsed.events) {
            this._dispatch(evt as ServerEvent);
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
    };

    this.ws.onclose = () => {
      this.ws = null;
      this._scheduleReconnect();
    };

    this.ws.onerror = () => {
      // onclose will fire after onerror, triggering reconnect
    };
  }

  private _dispatch(event: ServerEvent): void {
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
