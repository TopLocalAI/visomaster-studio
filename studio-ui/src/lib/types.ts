export type FieldType = "toggle" | "select" | "decimal" | "integer" | "text";

export type Clause =
  | { toggles: string[]; mode: "all" | "any"; value: boolean }
  | { select: string; equals: string };

export type Field = {
  key: string;
  type: FieldType;
  label: string;
  help: string;
  level: number;
  default: any;
  options?: string[];
  min?: number;
  max?: number;
  step?: number;
  decimals?: number;
  visible_when?: Clause[];
  effect?: string;
  dynamic?: string;
};

export type Section = { id: string; namespace: string; scope: "face" | "global"; title: string; fields: Field[] };
export type Schema = { version: number; sections: Section[]; defaults: { face: Record<string, any>; global: Record<string, any> } };

export type Media = {
  id: string;
  name: string;
  path: string;
  kind: "image" | "video";
  width: number;
  height: number;
  fps: number;
  frames: number;
  duration: number;
  has_audio: boolean;
  thumb: string | null;
};

export type Face = { id: string; kind: "source" | "target"; image: string; name: string; sources?: string[]; embeddings?: string[] };

export type Job = {
  id: string;
  kind: "export" | "models" | "scan";
  title: string;
  state: "queued" | "running" | "done" | "failed" | "cancelled";
  done: number;
  total: number;
  message: string;
  result: { path?: string; seconds?: number };
  created: number;
};

export type Hello = {
  version: string;
  platform: string;
  machine: string;
  providers: string[];
  provider: string | null;
  engine_ready: boolean;
  model_dir: string;
  output_dir: string;
  ffmpeg: boolean;
  base_models_ready: boolean;
};

export type ModelItem = { id: string; name: string; file: string; size: number; state: "installed" | "partial" | "missing"; partial: number; sources: number; base: boolean };
export type Models = { root: string; free: number; items: ModelItem[] };

export type Preview = { image: string; frame: number; width: number; height: number; original: boolean; ms: number; busy: boolean; skipped?: boolean };
