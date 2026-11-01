import {
  AlertCircle, Bookmark, Camera, CircleStop, ChevronDown, ChevronLeft, ChevronRight, ListPlus, ScanSearch, Check, Columns2, Download, Film, FolderOpen, Image as ImageIcon, ListChecks, Loader2, Pause, Play, Plus,
  RefreshCw, Settings as SettingsIcon, SkipBack, SkipForward, SquareDashed, X,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { AdvancedButton, AdvancedPanel, BasicAdjust, FacesSection } from "./components/Inspector";
import { same, shown, type Values } from "./components/Params";
import { JobsPopover, Settings, type SettingsTab } from "./components/Settings";
import { Menu, NamePrompt } from "./components/Menu";
import { ApiError, backendInfo, client, isTauri, onBackendChange, restartBackend, type BackendInfo } from "./lib/backend";
import { formatBytes, formatTime } from "./lib/labels";

const BASIC_KEYS = new Set(["SwapModelSelection", "SimilarityThresholdSlider", "FaceRestorerEnableToggle", "FaceRestorerBlendSlider", "OverallMaskBlendAmountSlider", "OccluderEnableToggle", "FaceExpressionEnableBothToggle"]);
const ADVANCED_GLOBAL = new Set(["settings:Frame Enhancer", "settings:Detectors", "settings:Face Tracking", "settings:Swap settings"]);
import type { Face, Field, Hello, Job, Media, Models, Preview, Schema } from "./lib/types";

type View = "result" | "original" | "compare" | "mask";
type Toast = { id: number; text: string; error?: boolean; action?: { label: string; run: () => void } };

const IMAGE_EXT = ["jpg", "jpeg", "png", "webp", "bmp", "tif", "tiff", "jfif"];
const VIDEO_EXT = ["mp4", "mov", "m4v", "mkv", "avi", "webm", "wmv", "mpg", "mpeg", "flv", "ts"];
const isMac = navigator.userAgent.includes("Mac");

async function pickFiles(kinds: "media" | "faces"): Promise<string[]> {
  const { open } = await import("@tauri-apps/plugin-dialog");
  const filters = kinds === "faces"
    ? [{ name: "图片", extensions: IMAGE_EXT }]
    : [{ name: "图片或视频", extensions: [...IMAGE_EXT, ...VIDEO_EXT] }];
  const r = await open({ multiple: true, filters });
  return Array.isArray(r) ? r : r ? [r] : [];
}

export default function App() {
  const [conn, setConn] = useState<BackendInfo | null>(null);
  const [connected, setConnected] = useState(false);
  const [connError, setConnError] = useState<string | null>(null);
  const [connAttempt, setConnAttempt] = useState(0);
  const [hello, setHello] = useState<Hello | null>(null);
  const [schema, setSchema] = useState<Schema | null>(null);
  const [models, setModels] = useState<Models | null>(null);
  const [engine, setEngine] = useState<"idle" | "starting" | "ready" | "error">("idle");
  const [media, setMedia] = useState<Media[]>([]);
  const [current, setCurrent] = useState<Media | null>(null);
  const [sources, setSources] = useState<Face[]>([]);
  const [targets, setTargets] = useState<Face[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [faceValues, setFaceValues] = useState<Values>({});
  const [globals, setGlobals] = useState<Values>({});
  const [frame, setFrame] = useState(0);
  const [range, setRange] = useState<{ start: number; end: number } | null>(null);
  const [view, setView] = useState<View>("result");
  const [preview, setPreview] = useState<Preview | null>(null);
  const [rendering, setRendering] = useState(false);
  const [renderError, setRenderError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [playing, setPlaying] = useState(false);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [jobsOpen, setJobsOpen] = useState(false);
  const [settingsTab, setSettingsTab] = useState<SettingsTab | null>(null);
  const [advanced, setAdvanced] = useState(false);
  const [markers, setMarkers] = useState<number[]>([]);
  const [issues, setIssues] = useState<number[]>([]);
  const [live, setLive] = useState<null | { running: boolean; fps: number; frames: number; error: string; width: number; height: number; virtual_camera: string }>(null);
  const [liveMode, setLiveMode] = useState(false);
  const [camera, setCamera] = useState("0");
  const [streamKey, setStreamKey] = useState(0);
  const [segments, setSegments] = useState<[number, number][]>([]);
  const [embeddings, setEmbeddings] = useState<{ id: string; name: string }[]>([]);
  const [project, setProject] = useState<string | null>(null);
  const [presets, setPresets] = useState<string[]>([]);
  const [prompt, setPrompt] = useState<null | { title: string; initial?: string; confirm: string; resolve: (v: string | null) => void }>(null);
  const ask = (title: string, confirm: string, initial?: string) =>
    new Promise<string | null>((resolve) => setPrompt({ title, confirm, initial, resolve }));
  const applyExtras = (st: any) => {
    setMarkers(st.markers ?? []);
    setSegments(st.segments ?? []);
    setEmbeddings(st.embeddings ?? []);
    setProject(st.project ?? null);
    setIssues(st.issues ?? []);
  };
  const [toasts, setToasts] = useState<Toast[]>([]);
  const [drop, setDrop] = useState<null | "media" | "faces">(null);
  const toastId = useRef(0);
  const renderTimer = useRef<number>();
  const renderSeq = useRef(0);
  const playingRef = useRef(false);
  const sourcesPane = useRef<HTMLDivElement>(null);

  // ---------------------------------------------------------------- toasts
  const toast = useCallback((text: string, error = false, action?: Toast["action"]) => {
    const id = ++toastId.current;
    setToasts((t) => [...t.slice(-2), { id, text, error, action }]);
    window.setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), error ? 7000 : action ? 6000 : 3200);
  }, []);
  const fail = useCallback((e: unknown) => {
    const message = e instanceof Error ? e.message : String(e);
    toast(message, true);
  }, [toast]);

  // ------------------------------------------------------------ connection
  useEffect(() => {
    let stop = false;
    let unlisten = () => {};
    const poll = async () => {
      while (!stop) {
        const info = await backendInfo();
        setConn(info);
        if (info.state !== "starting") return;
        await new Promise((r) => setTimeout(r, 250));
      }
    };
    poll();
    onBackendChange((info) => setConn(info)).then((u) => (unlisten = u));
    return () => {
      stop = true;
      unlisten();
    };
  }, []);

  const refreshModels = useCallback(() => client.call<Models>("models.list").then(setModels).catch(() => {}), []);

  const engineStarting = useRef(false);
  const startEngine = useCallback(async () => {
    if (engineStarting.current) return;
    engineStarting.current = true;
    setEngine("starting");
    try {
      const h = await client.call<Hello>("app.startEngine");
      setHello(h);
      setSchema(await client.call<Schema>("app.schema"));
      const p = await client.call("params.get");
      setGlobals(p.global);
      setFaceValues(p.face);
      // Rebuild from the backend workspace (window reload or reconnect keeps the work).
      const st = await client.call("workspace.state");
      setMedia(st.media);
      setSources(st.sources);
      setJobs(st.jobs);
      setTargets(st.targets);
      setSelected(st.targets[0]?.id ?? null);
      setCurrent(st.media.find((m: Media) => m.id === st.current) ?? null);
      applyExtras(st);
      setEngine("ready");
    } catch (e) {
      engineStarting.current = false;
      setEngine(e instanceof ApiError && e.code === "models_missing" ? "idle" : "error");
      if (!(e instanceof ApiError && e.code === "models_missing")) fail(e);
    }
  }, [fail]);

  useEffect(() => {
    if (conn?.state !== "ready" || connected) return;
    client.onClose = () => {
      setConnected(false);
      setConnError("与处理组件的连接已断开");
    };
    setConnError(null);
    client
      .connect(conn)
      .then(async () => {
        setConnected(true);
        const h = await client.call<Hello>("app.hello");
        setHello(h);
        setSchema(await client.call<Schema>("app.schema"));
        await refreshModels();
        setJobs(await client.call<Job[]>("jobs.list"));
        if (h.base_models_ready) startEngine();
      })
      .catch((e) => setConnError(e instanceof Error ? e.message : String(e)));
  }, [conn, connected, connAttempt, refreshModels, startEngine]);

  useEffect(() => {
    if (!connected) return;
    const offs = [
      client.on("job", (job: Job) => {
        setJobs((list) => {
          const i = list.findIndex((j) => j.id === job.id);
          if (i < 0) return [...list, job];
          const next = list.slice();
          next[i] = job;
          return next;
        });
        if (job.kind === "export" && job.state === "done" && job.result.path) {
          const path = job.result.path;
          toast(`已导出 ${path.split(/[\\/]/).pop()}`, false, { label: "显示", run: () => client.call("system.reveal", { path }).catch(fail) });
        }
        if (job.state === "failed") toast(`${job.title}：${job.message}`, true);
        if (job.kind === "scan" && job.state === "done") toast(job.message);
        if (job.kind === "models" && job.state !== "running") refreshModels();
      }),
      client.on("models", setModels),
      client.on("live", (d: any) => setLive(d)),
      client.on("issues", (d: { media: string; frames: number[] }) => {
        if (d.media === currentRef.current) setIssues(d.frames);
      }),
      client.on("notice", (d: { text: string }) => toast(d.text)),
      client.on("engine", (d: { state: string }) => d.state === "ready" && setEngine("ready")),
    ];
    return () => offs.forEach((o) => o());
  }, [connected, toast, fail, refreshModels]);

  // When base models finish downloading, start the engine.
  const baseReady = models ? models.items.filter((m) => m.base).every((m) => m.state === "installed") : false;
  useEffect(() => {
    if (connected && baseReady && engine === "idle") startEngine();
  }, [connected, baseReady, engine, startEngine]);

  // --------------------------------------------------------------- preview
  const render = useCallback(
    (at?: number, mode?: View) => {
      window.clearTimeout(renderTimer.current);
      const seq = ++renderSeq.current;
      renderTimer.current = window.setTimeout(async () => {
        if (!current) return;
        const v = mode ?? view;
        setRendering(true);
        try {
          const p = await client.call<Preview & { marker_applied?: boolean }>("preview.render", {
            follow_markers: true,
            frame: at ?? frame,
            original: v === "original",
            compare: v === "compare",
            mask: v === "mask",
          });
          if (p.skipped || seq !== renderSeq.current) return;
          if (p.marker_applied) {
            const q = await client.call("params.get", { face_id: selectedRef.current });
            setFaceValues(q.face);
            setGlobals(q.global);
          }
          setPreview(p);
          setRenderError(null);
        } catch (e) {
          if (seq !== renderSeq.current) return;
          setRenderError(e instanceof Error ? e.message : String(e));
          setPlaying(false);
        } finally {
          if (seq === renderSeq.current) setRendering(false);
        }
      }, 60);
    },
    [current, frame, view],
  );

  const selectedRef = useRef<string | null>(null);
  const currentRef = useRef<string | null>(null);
  const loadTargets = useCallback(async (list: Face[]) => {
    setTargets(list);
    setSelected((sel) => (sel && list.some((t) => t.id === sel) ? sel : list[0]?.id ?? null));
  }, []);

  useEffect(() => {
    selectedRef.current = selected;
  }, [selected]);
  useEffect(() => {
    currentRef.current = current?.id ?? null;
  }, [current]);

  // Per-face parameters follow the selected target face.
  useEffect(() => {
    if (engine !== "ready") return;
    client.call("params.get", { face_id: selected }).then((p) => {
      setFaceValues(p.face);
      setGlobals(p.global);
    }, fail);
  }, [selected, engine, fail]);

  // ---------------------------------------------------------------- media
  const selectMedia = useCallback(async (m: Media) => {
    if (liveMode) {
      await client.call("live.stop").catch(() => {});
      setLiveMode(false);
      setLive(null);
    }
    setPlaying(false);
    setCurrent(m);
    setFrame(0);
    setRange(null);
    setPreview(null);
    setRenderError(null);
    setTargets([]);
    setBusy("正在识别人脸…");
    try {
      const r = await client.call("media.select", { media_id: m.id });
      await loadTargets(r.targets);
      setIssues(r.issues ?? []);
    } catch (e) {
      fail(e);
    } finally {
      setBusy(null);
    }
  }, [fail, loadTargets, liveMode]);

  useEffect(() => {
    if (current && engine === "ready") render(frame);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [current, view, engine, targets]);

  const addMedia = useCallback(async (paths?: string[]) => {
    try {
      const list = paths ?? (await pickFiles("media"));
      if (!list.length) return;
      const added = await client.call<Media[]>("media.add", { paths: list });
      setMedia((m) => [...m, ...added]);
      if (added[0]) selectMedia(added[0]);
    } catch (e) {
      fail(e);
    }
  }, [fail, selectMedia]);

  const removeMedia = async (m: Media) => {
    await client.call("media.remove", { media_id: m.id }).catch(fail);
    setMedia((list) => list.filter((x) => x.id !== m.id));
    if (current?.id === m.id) {
      setCurrent(null);
      setPreview(null);
      setTargets([]);
    }
  };

  const addSources = useCallback(async (paths?: string[]) => {
    try {
      const list = paths ?? (await pickFiles("faces"));
      if (!list.length) return;
      setBusy("正在读取参考脸…");
      const r = await client.call("faces.addSources", { paths: list });
      setSources(await client.call<Face[]>("faces.sources"));
      await loadTargets(r.targets);
      if (r.failed.length) toast(r.failed.join("；"), true);
    } catch (e) {
      fail(e);
    } finally {
      setBusy(null);
    }
  }, [fail, loadTargets, toast]);

  const removeSource = async (id: string) => {
    try {
      const r = await client.call("faces.removeSource", { face_id: id });
      setSources(r.sources);
      await loadTargets(r.targets);
    } catch (e) {
      fail(e);
    }
  };

  const toggleAssign = async (sourceId: string) => {
    const target = targets.find((t) => t.id === selected);
    if (!target) return;
    const has = target.sources?.includes(sourceId);
    const next = has ? target.sources!.filter((s) => s !== sourceId) : [...(target.sources ?? []), sourceId];
    try {
      await loadTargets(await client.call<Face[]>("faces.assign", { target_id: target.id, source_ids: next }));
    } catch (e) {
      fail(e);
    }
  };

  const toggleEmbedding = async (embeddingId: string) => {
    const target = targets.find((t) => t.id === selected);
    if (!target) return;
    const list = target.embeddings ?? [];
    const next = list.includes(embeddingId) ? list.filter((x) => x !== embeddingId) : [...list, embeddingId];
    try {
      await loadTargets(await client.call<Face[]>("faces.assign", { target_id: target.id, source_ids: target.sources ?? [], embedding_ids: next }));
    } catch (e) {
      fail(e);
    }
  };

  // ------------------------------------------------------------ projects
  const applyState = async (st: any) => {
    setMedia(st.media);
    setSources(st.sources);
    await loadTargets(st.targets);
    applyExtras(st);
    const cur = st.media.find((m: Media) => m.id === st.current) ?? null;
    setCurrent(cur);
    setFrame(0);
    setRange(null);
    setPreview(null);
  };
  const newProject = async () => {
    try {
      await applyState(await client.call("project.new"));
    } catch (e) {
      fail(e);
    }
  };
  const openProject = async () => {
    try {
      const { open } = await import("@tauri-apps/plugin-dialog");
      const path = await open({ multiple: false, filters: [{ name: "VisoMaster 项目", extensions: ["json"] }] });
      if (typeof path !== "string") return;
      setBusy("正在打开项目…");
      const st = await client.call("project.open", { path });
      await applyState(st);
      if (st.warnings?.length) toast(st.warnings.join("；"), true);
      else toast("已打开项目");
    } catch (e) {
      fail(e);
    } finally {
      setBusy(null);
    }
  };
  const saveProject = async (as = false) => {
    try {
      let path = project;
      if (as || !path) {
        const { save } = await import("@tauri-apps/plugin-dialog");
        const chosen = await save({ defaultPath: path ?? "VisoMaster 项目.json", filters: [{ name: "VisoMaster 项目", extensions: ["json"] }] });
        if (!chosen) return;
        path = chosen;
      }
      const r = await client.call("project.save", { path });
      setProject(r.path);
      toast("项目已保存");
    } catch (e) {
      fail(e);
    }
  };

  // ------------------------------------------------------ markers / segments
  const addMarker = async () => setMarkers(await client.call("markers.add", { frame }).catch((e) => (fail(e), markers)));
  const removeMarker = async (f: number) => setMarkers(await client.call("markers.remove", { frame: f }).catch((e) => (fail(e), markers)));
  const addSegment = async () => {
    if (!range) return;
    try {
      setSegments(await client.call("segments.add", { start: range.start, end: range.end }));
      setRange(null);
    } catch (e) {
      fail(e);
    }
  };
  const removeSegment = async (i: number) => setSegments(await client.call("segments.remove", { index: i }).catch((e) => (fail(e), segments)));

  // ------------------------------------------------- embeddings / presets
  const mergeSources = async () => {
    const target = targets.find((t) => t.id === selected);
    const ids = target?.sources?.length ? target.sources : sources.map((s) => s.id);
    if (!ids.length) return;
    const name = await ask("合并为一个人脸", "合并", `合并人脸 ${embeddings.length + 1}`);
    if (!name) return;
    try {
      setEmbeddings(await client.call("embeddings.create", { name, source_ids: ids }));
    } catch (e) {
      fail(e);
    }
  };
  const removeEmbedding = async (id: string) => {
    try {
      const r = await client.call("embeddings.remove", { embedding_id: id });
      setEmbeddings(r.embeddings);
      await loadTargets(r.targets);
    } catch (e) {
      fail(e);
    }
  };
  const loadEmbeddings = async () => {
    try {
      const { open } = await import("@tauri-apps/plugin-dialog");
      const path = await open({ multiple: false, filters: [{ name: "人脸特征", extensions: ["json"] }] });
      if (typeof path === "string") setEmbeddings(await client.call("embeddings.load", { path }));
    } catch (e) {
      fail(e);
    }
  };
  const saveEmbeddings = async () => {
    try {
      const { save } = await import("@tauri-apps/plugin-dialog");
      const path = await save({ defaultPath: "人脸特征.json", filters: [{ name: "人脸特征", extensions: ["json"] }] });
      if (path) toast(`已保存 ${(await client.call("embeddings.save", { path })).count} 个人脸`);
    } catch (e) {
      fail(e);
    }
  };
  const refreshPresets = () => client.call<string[]>("presets.list").then(setPresets).catch(() => {});
  const savePreset = async () => {
    const name = await ask("保存为预设", "保存");
    if (!name) return;
    try {
      setPresets(await client.call("presets.save", { name, face_id: selected }));
      toast(`已保存预设“${name}”`);
    } catch (e) {
      fail(e);
    }
  };
  const applyPreset = async (name: string) => {
    try {
      const p = await client.call("presets.apply", { name, face_id: selected });
      setFaceValues(p.face);
      setGlobals(p.global);
      render();
    } catch (e) {
      fail(e);
    }
  };
  const deletePreset = async (name: string) => setPresets(await client.call("presets.delete", { name }).catch((e) => (fail(e), presets)));
  const applyReaging = async () => {
    if (!selected) return;
    setBusy("正在应用年龄调整…");
    try {
      await client.call("faces.applyReaging", { face_id: selected });
      render();
    } catch (e) {
      fail(e);
    } finally {
      setBusy(null);
    }
  };
  const startLive = async () => {
    try {
      setLive(await client.call("live.start", { source: /^\d+$/.test(camera) ? Number(camera) : camera }));
      setStreamKey((k) => k + 1);
    } catch (e) {
      fail(e);
    }
  };
  const stopLive = async () => {
    try {
      setLive(await client.call("live.stop"));
    } catch (e) {
      fail(e);
    }
  };
  const openLive = async () => {
    setPlaying(false);
    setCurrent(null);
    setPreview(null);
    setTargets([]);
    setLiveMode(true);
  };
  const detectLive = async () => {
    try {
      await loadTargets(await client.call<Face[]>("live.detect"));
    } catch (e) {
      fail(e);
    }
  };
  const toggleVirtualCam = async () => {
    const on = !globals.SendVirtCamFramesEnableToggle;
    setGlobals((g) => ({ ...g, SendVirtCamFramesEnableToggle: on }));
    await client.call("params.set", { values: { SendVirtCamFramesEnableToggle: on } }).catch(fail);
  };
  const scanIssues = async () => {
    try {
      await client.call("issues.scan");
      setJobsOpen(true);
    } catch (e) {
      fail(e);
    }
  };
  const jumpIssue = (dir: 1 | -1) => {
    const next = dir > 0 ? issues.find((f) => f > frame) : [...issues].reverse().find((f) => f < frame);
    if (next !== undefined) {
      setPlaying(false);
      seek(next);
    }
  };
  const exportAll = async () => {
    try {
      const jobs = await client.call<Job[]>("export.all");
      toast(`已加入 ${jobs.length} 个导出任务`);
    } catch (e) {
      fail(e);
    }
  };

  const detect = async () => {
    setBusy("正在识别人脸…");
    try {
      const list = await client.call<Face[]>("faces.detect", { frame });
      await loadTargets(list);
    } catch (e) {
      fail(e);
    } finally {
      setBusy(null);
    }
  };

  const removeTarget = async (id: string) => {
    try {
      await loadTargets(await client.call<Face[]>("faces.removeTarget", { face_id: id }));
    } catch (e) {
      fail(e);
    }
  };

  // ------------------------------------------------------------ parameters
  const paramTimer = useRef<number>();
  const pending = useRef<{ face: Values; global: Values }>({ face: {}, global: {} });
  const flushParams = useCallback(async () => {
    const { face, global } = pending.current;
    pending.current = { face: {}, global: {} };
    try {
      if (Object.keys(global).length) await client.call("params.set", { values: global });
      if (Object.keys(face).length) await client.call("params.set", { values: face, face_id: selected });
      render();
    } catch (e) {
      fail(e);
      client.call("params.get", { face_id: selected }).then((p) => {
        setFaceValues(p.face);
        setGlobals(p.global);
      });
    }
  }, [selected, render, fail]);

  const scopeOf = useMemo(() => {
    const m = new Map<string, "face" | "global">();
    schema?.sections.forEach((s) => s.fields.forEach((f) => m.set(f.key, s.scope)));
    return m;
  }, [schema]);

  const changeParam = (f: Field, v: any) => {
    const scope = scopeOf.get(f.key) ?? "face";
    if (scope === "global") {
      setGlobals((g) => ({ ...g, [f.key]: v }));
      pending.current.global[f.key] = v;
    } else {
      setFaceValues((p) => ({ ...p, [f.key]: v }));
      pending.current.face[f.key] = v;
    }
    window.clearTimeout(paramTimer.current);
    paramTimer.current = window.setTimeout(flushParams, f.type === "integer" || f.type === "decimal" ? 140 : 0);
  };
  const resetParam = (f: Field) => changeParam(f, f.default);
  const values = useMemo(() => ({ ...globals, ...faceValues }), [globals, faceValues]);

  // ---------------------------------------------------------------- export
  const exportNow = async () => {
    if (!current || !canExport) return;
    try {
      const params: Record<string, unknown> = {};
      if (current.kind === "video" && range) Object.assign(params, { start: range.start, end: range.end });
      await client.call("export.start", params);
    } catch (e) {
      fail(e);
    }
  };
  const exportFrame = async () => {
    try {
      await client.call("export.start", { kind: "image", frame });
    } catch (e) {
      fail(e);
    }
  };

  // -------------------------------------------------------------- playback
  useEffect(() => {
    playingRef.current = playing;
  }, [playing]);
  useEffect(() => {
    if (!playing || !current || rendering) return;
    if (preview && preview.frame !== frame) return;
    const end = range?.end ?? current.frames - 1;
    if (frame >= end) {
      setPlaying(false);
      return;
    }
    const next = frame + 1;
    setFrame(next);
    render(next);
  }, [playing, rendering, preview, frame, current, range, render]);

  const seek = (f: number) => {
    if (!current) return;
    const v = Math.max(0, Math.min(current.frames - 1, Math.round(f)));
    setFrame(v);
    render(v);
  };

  // Development builds: lets automated UI tests supply paths where a native dialog would.
  useEffect(() => {
    if (!import.meta.env.DEV) return;
    (window as any).__studio = { addMedia, addSources, client, applyState };
  });

  // --------------------------------------------------------- drag and drop
  useEffect(() => {
    if (!isTauri()) return;
    let unlisten = () => {};
    import("@tauri-apps/api/webview").then(({ getCurrentWebview }) =>
      getCurrentWebview()
        .onDragDropEvent((event) => {
          const p = event.payload as any;
          const over = () => {
            if (!p.position) return "media" as const;
            const ratio = window.devicePixelRatio || 1;
            const el = document.elementFromPoint(p.position.x / ratio, p.position.y / ratio);
            return sourcesPane.current && el && sourcesPane.current.contains(el) ? ("faces" as const) : ("media" as const);
          };
          if (p.type === "enter" || p.type === "over") setDrop(over());
          else if (p.type === "leave") setDrop(null);
          else if (p.type === "drop") {
            const where = over();
            setDrop(null);
            const paths: string[] = p.paths ?? [];
            if (!paths.length) return;
            if (where === "faces") addSources(paths);
            else addMedia(paths);
          }
        })
        .then((u) => (unlisten = u)),
    );
    return () => unlisten();
  }, [addMedia, addSources]);

  // --------------------------------------------------------------- keyboard
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const typing = (e.target as HTMLElement)?.closest("input, select, textarea");
      if (e.key === "Escape") {
        if (settingsTab || jobsOpen) {
          setSettingsTab(null);
          setJobsOpen(false);
        } else setAdvanced(false);
        return;
      }
      if (typing) return;
      const mod = e.metaKey || e.ctrlKey;
      if (mod && e.key === ",") {
        e.preventDefault();
        setSettingsTab("models");
      } else if (mod && e.key.toLowerCase() === "o") {
        e.preventDefault();
        if (e.shiftKey) openProject();
        else addMedia();
      } else if (mod && e.key.toLowerCase() === "s") {
        e.preventDefault();
        saveProject(e.shiftKey);
      } else if (mod && e.key.toLowerCase() === "e") {
        e.preventDefault();
        exportNow();
      } else if (current?.kind === "video") {
        if (e.key === " ") {
          e.preventDefault();
          setPlaying((p) => !p);
        } else if (e.key === "ArrowRight") seek(frame + (e.shiftKey ? 10 : 1));
        else if (e.key === "ArrowLeft") seek(frame - (e.shiftKey ? 10 : 1));
        else if (e.key.toLowerCase() === "i") setRange((r) => ({ start: frame, end: Math.max(frame, r?.end ?? current.frames - 1) }));
        else if (e.key.toLowerCase() === "o") setRange((r) => ({ start: Math.min(frame, r?.start ?? 0), end: frame }));
        else if (e.key.toLowerCase() === "m") addMarker();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  // ------------------------------------------------------------------ views
  const runningJobs = jobs.filter((j) => j.state === "running" || j.state === "queued");
  const exportJob = jobs.find((j) => j.kind === "export" && j.state === "running");
  const modelJob = jobs.find((j) => j.kind === "models" && (j.state === "running" || j.state === "queued"));
  const selectedTarget = targets.find((t) => t.id === selected) ?? null;
  const assignedCount = targets.filter((t) => t.sources?.length).length;
  const canExport = Boolean(current && engine === "ready" && assignedCount > 0 && !busy);

  const centre = () => {
    if (connError && !connected) {
      return (
        <div className="empty">
          <div className="glyph"><AlertCircle size={22} /></div>
          <h2>无法连接处理组件</h2>
          {connError !== "无法连接处理组件" && <p>{connError}</p>}
          <div className="actions">
            <button className="btn" onClick={() => (isTauri() ? restartBackend().then(setConn) : Promise.resolve()).then(() => setConnAttempt((n) => n + 1)).catch(fail)}>
              <RefreshCw size={13} /> 重试
            </button>
          </div>
        </div>
      );
    }
    if (!conn || conn.state === "starting" || (conn.state === "ready" && !connected)) {
      return (
        <div className="empty">
          <Loader2 className="spin" size={22} />
          <p>正在启动…</p>
        </div>
      );
    }
    if (conn.state === "failed") {
      return (
        <div className="empty">
          <div className="glyph"><AlertCircle size={22} /></div>
          <h2>处理组件未能启动</h2>
          <p>{conn.error}</p>
          {isTauri() && (
            <div className="actions">
              <button className="btn" onClick={() => restartBackend().then(setConn).catch(fail)}><RefreshCw size={13} /> 重试</button>
            </div>
          )}
        </div>
      );
    }
    if (models && !baseReady) {
      const base = models.items.filter((m) => m.base);
      const need = base.filter((m) => m.state !== "installed").reduce((n, m) => n + m.size - m.partial, 0);
      const pct = modelJob?.total ? (modelJob.done / modelJob.total) * 100 : 0;
      return (
        <div className="empty">
          <div className="glyph"><Download size={22} /></div>
          <h2>下载基础模型</h2>
          <p>人脸检测、识别和换脸需要 {formatBytes(need)}，只需下载一次。</p>
          {modelJob ? (
            <>
              <div className="progress"><div style={{ width: `${pct}%` }} /></div>
              <p>{modelJob.message || "准备中"} · {Math.floor(pct)}%</p>
              <div className="actions">
                <button className="btn" onClick={() => client.call("jobs.cancel", { job_id: modelJob.id }).catch(fail)}>暂停</button>
              </div>
            </>
          ) : (
            <div className="actions">
              <button className="btn primary" onClick={() => client.call("models.download", {}).then(refreshModels, fail)}><Download size={13} /> 下载</button>
              <button className="btn" onClick={() => setSettingsTab("models")}>从文件夹导入</button>
            </div>
          )}
        </div>
      );
    }
    if (engine === "starting" || engine === "idle") {
      return (
        <div className="empty">
          <Loader2 className="spin" size={22} />
          <p>正在加载…</p>
        </div>
      );
    }
    if (engine === "error") {
      return (
        <div className="empty">
          <div className="glyph"><AlertCircle size={22} /></div>
          <h2>无法加载处理引擎</h2>
          <div className="actions"><button className="btn" onClick={startEngine}><RefreshCw size={13} /> 重试</button></div>
        </div>
      );
    }
    if (liveMode) {
      return (
        <>
          {live?.running ? (
            <img key={streamKey} className="frame" src={`${client.base}/live.mjpg?token=${encodeURIComponent(client.token)}&k=${streamKey}`} alt="" draggable={false} />
          ) : (
            <div className="empty">
              <div className="glyph"><Camera size={22} /></div>
              <h2>实时换脸</h2>
              {live?.error ? <p className="err-text">{live.error}</p> : <p>选择摄像头后开始</p>}
              <div className="actions">
                <select className="select" value={camera} onChange={(e) => setCamera(e.target.value)} aria-label="摄像头">
                  {Array.from({ length: Number(globals.WebcamMaxNoSelection ?? 1) || 1 }, (_, i) => (
                    <option key={i} value={String(i)}>摄像头 {i + 1}</option>
                  ))}
                </select>
                <button className="btn primary" onClick={startLive}><Play size={14} /> 开始</button>
              </div>
            </div>
          )}
        </>
      );
    }
    if (!current) {
      return (
        <div className="empty">
          <div className="glyph"><ImageIcon size={22} /></div>
          <h2>添加图片或视频</h2>
          <p>也可以直接拖到窗口中</p>
          <div className="actions"><button className="btn primary" onClick={() => addMedia()}><Plus size={14} /> 添加素材</button></div>
        </div>
      );
    }
    if (renderError && !preview) {
      return (
        <div className="empty">
          <div className="glyph"><AlertCircle size={22} /></div>
          <h2>处理失败</h2>
          <p>{renderError}</p>
          <div className="actions"><button className="btn" onClick={() => render()}><RefreshCw size={13} /> 重试</button></div>
        </div>
      );
    }
    if (!preview) return <Loader2 className="spin" size={22} color="var(--text-3)" />;
    return (
      <>
        <img className="frame" src={client.image(preview.image)} alt="" draggable={false} />
        {preview.original && view !== "original" && <span className="tag">原图 · 导出进行中</span>}
        {view === "original" && <span className="tag">原图</span>}
        {(rendering || busy) && (
          <span className="spin-overlay"><Loader2 size={13} className="spin" />{busy ?? "处理中"}</span>
        )}
      </>
    );
  };

  const statusLine = () => {
    if (renderError && preview) return <span className="status err"><AlertCircle size={13} />{renderError}</span>;
    if (!current) return <span className="status" />;
    if (targets.length === 0) return <span className="status">未识别到人脸</span>;
    if (sources.length === 0) return <span className="status">添加参考脸后开始替换</span>;
    if (assignedCount === 0) return <span className="status">选择人脸，再点参考脸</span>;
    return (
      <span className="status">
        {targets.length} 个人脸 · {assignedCount === targets.length ? "已替换" : `${assignedCount} 个已替换`}
      </span>
    );
  };

  const faceIndex = selectedTarget ? targets.indexOf(selectedTarget) + 1 : 0;
  const advancedChanged = useMemo(() => {
    if (!schema) return 0;
    let n = 0;
    for (const s of schema.sections) for (const f of s.fields) {
      if (BASIC_KEYS.has(f.key) || !shown(f) || s.namespace === "settings" && !ADVANCED_GLOBAL.has(s.id)) continue;
      if (!same(values[f.key] ?? f.default, f.default)) n++;
    }
    return n;
  }, [schema, values]);

  const resetFace = async () => {
    try {
      const p = await client.call("params.reset", { face_id: selected });
      setFaceValues(p.face);
      render();
    } catch (e) {
      fail(e);
    }
  };
  const applyToAll = async () => {
    if (!selected) return;
    try {
      await client.call("params.copy", { from_face: selected });
      toast("已应用到所有人脸");
      render();
    } catch (e) {
      fail(e);
    }
  };

  const end = current ? current.frames - 1 : 0;
  return (
    <div className="app">
      <header className={`titlebar${isMac && isTauri() ? " mac" : ""}`} data-tauri-drag-region>
        <div className="brand" data-tauri-drag-region>
          VisoMaster Studio
          <Menu
            trigger={(open, toggle) => (
              <button className={`crumb-btn${open ? " on" : ""}`} onClick={toggle} disabled={engine !== "ready"}>
                {project ? project.split(/[\\/]/).pop()?.replace(/\.json$/, "") : "未命名项目"}
                <ChevronDown size={13} />
              </button>
            )}
            items={[
              { label: "新建项目", onSelect: newProject },
              { label: "打开项目…", hint: "⌘⇧O", onSelect: openProject },
              "divider",
              { label: "保存", hint: "⌘S", onSelect: () => saveProject(false) },
              { label: "另存为…", hint: "⌘⇧S", onSelect: () => saveProject(true) },
            ]}
          />
          {current && <span className="crumb" data-tauri-drag-region>/&nbsp;&nbsp;{current.name}</span>}
        </div>
        <div className="drag" data-tauri-drag-region />
        <button className="icon-btn" title="任务" aria-label="任务" onClick={() => setJobsOpen((o) => !o)}>
          <ListChecks size={16} />
          {runningJobs.length > 0 && <span className="badge">{runningJobs.length}</span>}
        </button>
        <button className="icon-btn" title="设置 (⌘,)" aria-label="设置" onClick={() => setSettingsTab((t) => (t ? null : "models"))}>
          <SettingsIcon size={16} />
        </button>
        <div className="split" style={{ marginLeft: 6 }}>
          <button className="btn primary" disabled={!canExport} onClick={exportNow} title="导出 (⌘E)">
            {exportJob ? <Loader2 size={14} className="spin" /> : <Download size={14} />}
            {exportJob ? `导出中 ${exportJob.total ? Math.floor((exportJob.done / exportJob.total) * 100) : 0}%` : segments.length && current?.kind === "video" ? `导出 ${segments.length} 段` : "导出"}
          </button>
          <Menu align="right"
            trigger={(_, toggle) => (
              <button className="btn primary split-more" disabled={!canExport} onClick={toggle} aria-label="更多导出选项"><ChevronDown size={14} /></button>
            )}
            items={[
              { label: segments.length && current?.kind === "video" ? `导出当前素材（${segments.length} 段）` : "导出当前素材", hint: "⌘E", onSelect: exportNow },
              { label: `导出全部素材（${media.length}）`, disabled: media.length < 2, onSelect: exportAll },
            ]}
          />
        </div>
      </header>

      <div className="body">
        <aside className="sidebar">
          <div className="pane-head">
            <span>素材</span>
            <button className="icon-btn" title="添加素材 (⌘O)" aria-label="添加素材" onClick={() => addMedia()} disabled={engine !== "ready"}>
              <Plus size={16} />
            </button>
          </div>
          <div className="scroll media-list">
            <div className={`media-row camera-row${liveMode ? " on" : ""}`} onClick={() => !liveMode && openLive()} role="button" tabIndex={0}>
              <span className="thumb cam-thumb"><Camera size={16} /></span>
              <div className="media-text">
                <div className="name">摄像头</div>
                <div className="meta">{live?.running ? `实时 · ${live.fps} 帧/秒` : "实时换脸"}</div>
              </div>
            </div>
            {media.length === 0 && <div className="hint-line">图片或视频，可直接拖入</div>}
            {media.map((m) => (
              <div key={m.id} className={`media-row${current?.id === m.id ? " on" : ""}`} onClick={() => current?.id !== m.id && selectMedia(m)} role="button" tabIndex={0}>
                {m.thumb ? <img className="thumb" src={client.image(m.thumb)} alt="" /> : <div className="thumb" />}
                <div className="media-text">
                  <div className="name" title={m.path}>{m.name}</div>
                  <div className="meta">
                    {m.kind === "video" ? <Film size={11} /> : <ImageIcon size={11} />}
                    {m.kind === "video" ? formatTime(m.duration) : `${m.width}×${m.height}`}
                  </div>
                </div>
                <button className="icon-btn small x" aria-label="移除" title="移除" onClick={(e) => { e.stopPropagation(); removeMedia(m); }}>
                  <X size={13} />
                </button>
              </div>
            ))}
          </div>
        </aside>

        <main className="stage">
          <div className="canvas">
            {centre()}
            {drop === "media" && <div className="drop-hint">添加为素材</div>}
          </div>
          {liveMode && (
            <div className="transport live-bar">
              <div className="tools">
                {live?.running ? (
                  <button className="btn small" onClick={stopLive}><CircleStop size={13} /> 停止</button>
                ) : (
                  <button className="btn small primary" onClick={startLive}><Play size={13} /> 开始</button>
                )}
              </div>
              <span className="live-stats">
                {live?.running ? `${live.width}×${live.height} · ${live.fps} 帧/秒` : live?.error || "未开始"}
              </span>
              <div className="tools">
                <button className="text-action" onClick={detectLive} disabled={!live?.running}><ScanSearch size={14} /> 识别人脸</button>
                <span className="row-inline">虚拟摄像头
                  <button className={`switch${globals.SendVirtCamFramesEnableToggle ? " on" : ""}`} role="switch" aria-label="虚拟摄像头"
                    aria-checked={Boolean(globals.SendVirtCamFramesEnableToggle)} onClick={toggleVirtualCam} />
                </span>
              </div>
            </div>
          )}
          {current?.kind === "video" && (
            <div className="transport">
              <div className="tools">
                <button className="icon-btn" aria-label="上一帧" onClick={() => seek(frame - 1)}><SkipBack size={15} /></button>
                <button className="icon-btn" aria-label={playing ? "暂停" : "播放"} onClick={() => setPlaying((p) => !p)}>
                  {playing ? <Pause size={16} /> : <Play size={16} />}
                </button>
                <button className="icon-btn" aria-label="下一帧" onClick={() => seek(frame + 1)}><SkipForward size={15} /></button>
              </div>
              <div className="track">
                <div className="rail" />
                {range && <div className="range" style={{ left: `${(range.start / Math.max(1, end)) * 100}%`, width: `${((range.end - range.start) / Math.max(1, end)) * 100}%` }} />}
                {segments.map(([a, b], i) => (
                  <div key={`s${i}`} className="segment" style={{ left: `${(a / Math.max(1, end)) * 100}%`, width: `${((b - a) / Math.max(1, end)) * 100}%` }} />
                ))}
                <div className="head" style={{ left: `${(frame / Math.max(1, end)) * 100}%` }} />
                <input type="range" min={0} max={end} value={frame} aria-label="时间轴"
                  onChange={(e) => { setPlaying(false); seek(Number(e.target.value)); }} />
                {issues.map((f) => (
                  <div key={`i${f}`} className="issue" style={{ left: `${(f / Math.max(1, end)) * 100}%` }} />
                ))}
                {markers.map((m) => (
                  <button key={m} className="marker" style={{ left: `${(m / Math.max(1, end)) * 100}%` }} title={`标记 · 第 ${m + 1} 帧（右键删除）`}
                    onClick={() => { setPlaying(false); seek(m); }} onContextMenu={(e) => { e.preventDefault(); removeMarker(m); }} />
                ))}
              </div>
              <div className="tools">
                <button className="icon-btn" title="设为起点 (I)" aria-label="设为起点"
                  onClick={() => setRange((r) => ({ start: frame, end: Math.max(frame, r?.end ?? end) }))}>
                  <SquareDashed size={14} />
                </button>
                <button className="icon-btn" title="设为终点 (O)" aria-label="设为终点"
                  onClick={() => setRange((r) => ({ start: Math.min(frame, r?.start ?? 0), end: frame }))}>
                  <Columns2 size={14} />
                </button>
                <button className="icon-btn" title="扫描问题帧" aria-label="扫描问题帧" onClick={scanIssues} disabled={!targets.length}>
                  <ScanSearch size={14} />
                </button>
                {issues.length > 0 && (
                  <span className="issue-nav">
                    <button className="icon-btn small" aria-label="上一个问题帧" onClick={() => jumpIssue(-1)}><ChevronLeft size={13} /></button>
                    <span>{issues.length} 个问题帧</span>
                    <button className="icon-btn small" aria-label="下一个问题帧" onClick={() => jumpIssue(1)}><ChevronRight size={13} /></button>
                  </span>
                )}
                <button className="icon-btn" title="添加参数标记 (M)" aria-label="添加参数标记" onClick={addMarker}>
                  <Bookmark size={14} />
                </button>
                {range && (
                  <>
                    <button className="range-chip" onClick={() => setRange(null)} title="清除范围">
                      范围 {range.start + 1}–{range.end + 1} <X size={11} />
                    </button>
                    <button className="icon-btn" title="加为导出分段" aria-label="加为导出分段" onClick={addSegment}><ListPlus size={14} /></button>
                  </>
                )}
                {segments.map(([a, b], i) => (
                  <button key={`c${i}`} className="range-chip seg-chip" onClick={() => removeSegment(i)} title="移除这一段">
                    {a + 1}–{b + 1} <X size={11} />
                  </button>
                ))}
                <span className="tc">{formatTime(frame / (current.fps || 25))} · {frame + 1} / {current.frames}</span>
              </div>
            </div>
          )}
          {!liveMode && <div className="viewbar">
            <div className="seg" role="tablist" aria-label="显示">
              {([["result", "结果"], ["original", "原图"], ["compare", "对比"], ["mask", "遮罩"]] as [View, string][]).map(([v, label]) => (
                <button key={v} className={view === v ? "on" : ""} onClick={() => setView(v)} disabled={!current}>{label}</button>
              ))}
            </div>
            {statusLine()}
            {current?.kind === "video" && (
              <button className="text-action" onClick={exportFrame} disabled={!canExport} title="导出当前帧为图片">
                <ImageIcon size={14} /> 导出此帧
              </button>
            )}
          </div>}
        </main>

        <aside className="inspector">
          {schema && engine === "ready" && advanced ? (
            <AdvancedPanel schema={schema} values={values} faceLabel={targets.length > 1 && faceIndex ? `人脸 ${faceIndex}` : null}
              onChange={changeParam} onResetAll={resetFace} onApplyAll={applyToAll} onClose={() => setAdvanced(false)}
              presets={presets} onOpenPresets={refreshPresets} onApplyPreset={applyPreset} onSavePreset={savePreset} onDeletePreset={deletePreset}
              onApplyReaging={applyReaging} />
          ) : (
            <>
              <div ref={sourcesPane} className="inspector-body">
                <FacesSection targets={targets} sources={sources} selected={selected} disabled={engine !== "ready"} hasMedia={Boolean(current)}
                  onSelect={setSelected} onToggleSource={toggleAssign} onAddSources={() => addSources()} onRemoveSource={removeSource}
                  onRemoveTarget={removeTarget} onDetect={detect} dropActive={drop === "faces"}
                  embeddings={embeddings} onToggleEmbedding={toggleEmbedding} onRemoveEmbedding={removeEmbedding}
                  onMerge={mergeSources} onLoadEmbeddings={loadEmbeddings} onSaveEmbeddings={saveEmbeddings} />
                {schema && engine === "ready" && (current || liveMode) && <BasicAdjust schema={schema} values={values} onChange={changeParam} />}
              </div>
              {schema && engine === "ready" && (current || liveMode) && (
                <div className="inspector-foot">
                  <AdvancedButton onClick={() => setAdvanced(true)} changed={advancedChanged} />
                </div>
              )}
            </>
          )}
        </aside>
      </div>

      {settingsTab && (
        <Settings tab={settingsTab} onTab={setSettingsTab} onClose={() => setSettingsTab(null)} hello={hello} schema={schema} models={models}
          jobs={jobs} globals={globals} onGlobal={changeParam} onResetGlobal={resetParam} onError={fail}
          refresh={() => { refreshModels(); client.call<Hello>("app.hello").then(setHello).catch(() => {}); }}
          onSchema={() => client.call<Schema>("app.schema").then(setSchema).catch(fail)}
          embeddings={embeddings} onEmbeddings={setEmbeddings} />
      )}
      {jobsOpen && <JobsPopover jobs={jobs} onClose={() => setJobsOpen(false)} onError={fail} />}
      {prompt && (
        <NamePrompt title={prompt.title} initial={prompt.initial} confirm={prompt.confirm}
          onDone={(v) => { prompt.resolve(v); setPrompt(null); }} />
      )}
      <div className="toasts" aria-live="polite">
        {toasts.map((t) => (
          <div key={t.id} className={`toast${t.error ? " err" : ""}`}>
            {t.error ? <AlertCircle size={14} /> : <Check size={14} color="var(--accent)" />}
            <span>{t.text}</span>
            {t.action && <button className="btn small" onClick={t.action.run}><FolderOpen size={12} /> {t.action.label}</button>}
          </div>
        ))}
      </div>
    </div>
  );
}
