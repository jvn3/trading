// WebSocket adapter (S1.10). The backend exposes no socket until Phase 2 (S2.7 streaming), so
// this stays dormant — but the reconnect/backoff plumbing and the single subscription surface
// exist now so screens can subscribe without caring when the transport goes live.

export type WsMessage = { type: string; payload: unknown };
type Listener = (msg: WsMessage) => void;

const MAX_BACKOFF_MS = 30_000;

export class WsAdapter {
  private socket: WebSocket | null = null;
  private listeners = new Set<Listener>();
  private backoff = 1_000;
  private closedByUser = false;

  constructor(private url: string) {}

  connect(): void {
    this.closedByUser = false;
    try {
      this.socket = new WebSocket(this.url);
    } catch {
      this.scheduleReconnect();
      return;
    }
    this.socket.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data) as WsMessage;
        this.listeners.forEach((fn) => fn(msg));
      } catch {
        // ignore malformed frames
      }
    };
    this.socket.onopen = () => {
      this.backoff = 1_000;
    };
    this.socket.onclose = () => {
      if (!this.closedByUser) this.scheduleReconnect();
    };
  }

  private scheduleReconnect(): void {
    setTimeout(() => this.connect(), this.backoff);
    this.backoff = Math.min(this.backoff * 2, MAX_BACKOFF_MS);
  }

  subscribe(fn: Listener): () => void {
    this.listeners.add(fn);
    return () => this.listeners.delete(fn);
  }

  close(): void {
    this.closedByUser = true;
    this.socket?.close();
  }
}

// Dormant until S2.7 ships a socket endpoint; screens import this and subscribe.
export const wsAdapter = new WsAdapter(
  `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/api/ws`,
);
