// Connection to the local processing backend (JSON-RPC over WebSocket).

export type BackendInfo = { state: "starting" | "ready" | "failed"; port: number; token: string; error: string; log: string };

type Pending = { resolve: (v: any) => void; reject: (e: Error) => void };
type Listener = (data: any) => void;

export class ApiError extends Error {
  code: string;
  constructor(message: string, code = "error") {
    super(message);
    this.code = code;
  }
}

export const isTauri = () => typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;

export async function backendInfo(): Promise<BackendInfo> {
  if (isTauri()) {
    const { invoke } = await import("@tauri-apps/api/core");
    return invoke<BackendInfo>("backend_info");
  }
  // Browser development: ?port=…&token=… from a manually started backend.
  const q = new URLSearchParams(location.search);
  const port = Number(q.get("port") || import.meta.env.VITE_BACKEND_PORT || 0);
  const token = q.get("token") || import.meta.env.VITE_BACKEND_TOKEN || "";
  return port ? { state: "ready", port, token, error: "", log: "" } : { state: "failed", port: 0, token: "", error: "未连接处理组件", log: "" };
}

export async function onBackendChange(listener: (info: BackendInfo) => void): Promise<() => void> {
  if (!isTauri()) return () => {};
  const { listen } = await import("@tauri-apps/api/event");
  return listen<BackendInfo>("backend", (e) => listener(e.payload));
}

export async function restartBackend(): Promise<BackendInfo> {
  const { invoke } = await import("@tauri-apps/api/core");
  return invoke<BackendInfo>("restart_backend");
}

export class Client {
  private ws: WebSocket | null = null;
  private seq = 0;
  private pending = new Map<number, Pending>();
  private listeners = new Map<string, Set<Listener>>();
  private opened: Promise<void> | null = null;
  base = "";
  token = "";
  onClose: (() => void) | null = null;

  connect(info: BackendInfo): Promise<void> {
    this.base = `http://127.0.0.1:${info.port}`;
    this.token = info.token;
    this.opened = new Promise((resolve, reject) => {
      const ws = new WebSocket(`ws://127.0.0.1:${info.port}/rpc?token=${encodeURIComponent(info.token)}`);
      this.ws = ws;
      ws.onopen = () => resolve();
      ws.onerror = () => reject(new ApiError("无法连接处理组件", "connect"));
      ws.onclose = () => {
        for (const p of this.pending.values()) p.reject(new ApiError("处理组件连接已断开", "connect"));
        this.pending.clear();
        this.onClose?.();
      };
      ws.onmessage = (m) => {
        const msg = JSON.parse(m.data);
        if (msg.event) {
          this.listeners.get(msg.event)?.forEach((l) => l(msg.data));
          return;
        }
        const p = this.pending.get(msg.id);
        if (!p) return;
        this.pending.delete(msg.id);
        if (msg.error) p.reject(new ApiError(msg.error.message, msg.error.code));
        else p.resolve(msg.result);
      };
    });
    return this.opened;
  }

  async call<T = any>(method: string, params: Record<string, unknown> = {}): Promise<T> {
    await this.opened;
    const ws = this.ws;
    if (!ws || ws.readyState !== WebSocket.OPEN) throw new ApiError("处理组件未连接", "connect");
    const id = ++this.seq;
    return new Promise<T>((resolve, reject) => {
      this.pending.set(id, { resolve, reject });
      ws.send(JSON.stringify({ id, method, params }));
    });
  }

  on(event: string, listener: Listener): () => void {
    if (!this.listeners.has(event)) this.listeners.set(event, new Set());
    this.listeners.get(event)!.add(listener);
    return () => this.listeners.get(event)?.delete(listener);
  }

  image(key: string | null | undefined): string {
    return key ? `${this.base}/img/${encodeURIComponent(key)}?token=${encodeURIComponent(this.token)}` : "";
  }

  close() {
    this.ws?.close();
  }
}

export const client = new Client();
