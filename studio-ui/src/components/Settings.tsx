import { ArrowDown, ArrowUp, Cpu, Download, FolderOpen, HardDrive, Info, Loader2, Package, Trash2, Users, X } from "lucide-react";
import { useEffect, useState } from "react";
import { client } from "../lib/backend";
import { formatBytes, sectionTitle } from "../lib/labels";
import type { Field, Hello, Job, Models, Schema } from "../lib/types";
import { FieldRow, shown, visible, type Values } from "./Params";

export type SettingsTab = "models" | "library" | "run" | "output" | "about";

const TABS: { id: SettingsTab; label: string; icon: JSX.Element }[] = [
  { id: "models", label: "模型", icon: <Package size={14} /> },
  { id: "library", label: "人脸库", icon: <Users size={14} /> },
  { id: "run", label: "运行", icon: <Cpu size={14} /> },
  { id: "output", label: "输出", icon: <HardDrive size={14} /> },
  { id: "about", label: "关于", icon: <Info size={14} /> },
];

async function pickFolder(): Promise<string | null> {
  const { open } = await import("@tauri-apps/plugin-dialog");
  const r = await open({ directory: true, multiple: false });
  return typeof r === "string" ? r : null;
}

export function Settings(props: {
  tab: SettingsTab;
  onTab: (t: SettingsTab) => void;
  onClose: () => void;
  hello: Hello | null;
  schema: Schema | null;
  models: Models | null;
  jobs: Job[];
  globals: Values;
  onGlobal: (f: Field, v: any) => void;
  onResetGlobal: (f: Field) => void;
  onError: (e: unknown) => void;
  refresh: () => void;
  onSchema: () => void;
  embeddings: { id: string; name: string }[];
  onEmbeddings: (list: { id: string; name: string }[]) => void;
}) {
  const { tab, hello, schema, models, jobs } = props;
  const [paths, setPaths] = useState<{ model_dir: string; output_dir: string } | null>(null);
  const [restart, setRestart] = useState(false);
  useEffect(() => {
    client.call("settings.get").then(setPaths, props.onError);
  }, []);
  const modelJob = jobs.find((j) => j.kind === "models" && (j.state === "running" || j.state === "queued"));

  const changePath = async (key: "model_dir" | "output_dir") => {
    const dir = await pickFolder();
    if (!dir) return;
    try {
      const r = await client.call("settings.set", { [key]: dir });
      setPaths(r);
      if (r.restart_required) setRestart(true);
      props.refresh();
    } catch (e) {
      props.onError(e);
    }
  };

  const sectionRows = (ids: string[], filter?: (f: Field) => boolean) =>
    schema?.sections
      .filter((s) => ids.includes(s.id))
      .map((s) => {
        const fields = s.fields.filter(shown).filter((f) => (filter ? filter(f) : true));
        if (!fields.length) return null;
        return (
          <div key={s.id} style={{ marginBottom: 18 }}>
            <div className="k" style={{ color: "var(--text-3)", fontSize: 12, margin: "0 0 4px 2px" }}>{sectionTitle(s.id, s.title)}</div>
            {fields.filter((f) => visible(f, props.globals)).map((f) => (
              <FieldRow key={f.key} field={f} value={props.globals[f.key] ?? f.default} onChange={(v) => props.onGlobal(f, v)} onReset={() => props.onResetGlobal(f)} />
            ))}
          </div>
        );
      });

  const missing = models?.items.filter((m) => m.state !== "installed") ?? [];
  const baseMissing = missing.filter((m) => m.base);

  return (
    <>
      <div className="scrim" onClick={props.onClose} />
      <aside className="sheet" role="dialog" aria-label="设置">
        <nav>
          {TABS.map((t) => (
            <button key={t.id} className={tab === t.id ? "on" : ""} onClick={() => props.onTab(t.id)}>
              {t.icon}
              {t.label}
            </button>
          ))}
          <div className="spacer" />
          <button onClick={props.onClose}>
            <X size={14} />
            关闭
          </button>
        </nav>
        <div className="content">
          {tab === "models" && models && (
            <>
              <h3>模型</h3>
              <p className="sub">
                已安装 {models.items.length - missing.length} / {models.items.length} · 可用空间 {formatBytes(models.free)}
              </p>
              <div className="kv">
                <span className="k">位置</span>
                <div style={{ display: "flex", gap: 8, alignItems: "center", minWidth: 0 }}>
                  <span className="path" title={models.root}>{models.root}</span>
                  <button className="btn small" onClick={() => changePath("model_dir")}>更改</button>
                </div>
              </div>
              {restart && <div className="assign-hint" style={{ margin: "0 0 12px" }}>新位置将在重新启动后使用。</div>}
              <div style={{ display: "flex", gap: 8, marginBottom: 10 }}>
                {modelJob ? (
                  <>
                    <span style={{ display: "flex", alignItems: "center", gap: 6, color: "var(--text-2)", fontSize: 12 }}>
                      <Loader2 size={13} className="spin" /> {modelJob.message || "准备中"} · {modelJob.total ? Math.floor((modelJob.done / modelJob.total) * 100) : 0}%
                    </span>
                    <button className="btn small" onClick={() => client.call("jobs.cancel", { job_id: modelJob.id }).catch(props.onError)}>暂停</button>
                  </>
                ) : (
                  <>
                    {baseMissing.length > 0 && (
                      <button className="btn small primary" onClick={() => client.call("models.download", {}).then(props.refresh, props.onError)}>
                        <Download size={13} /> 下载基础模型
                      </button>
                    )}
                    <button
                      className="btn small"
                      onClick={async () => {
                        const dir = await pickFolder();
                        if (dir) client.call("models.import", { folder: dir }).then(props.refresh, props.onError);
                      }}
                    >
                      <FolderOpen size={13} /> 从文件夹导入
                    </button>
                    <button
                      className="btn small"
                      onClick={async () => {
                        const { open } = await import("@tauri-apps/plugin-dialog");
                        const r = await open({ multiple: true, filters: [{ name: "DFM 模型", extensions: ["dfm", "onnx"] }] });
                        const paths = Array.isArray(r) ? r : r ? [r] : [];
                        if (!paths.length) return;
                        client.call("dfm.import", { paths }).then((res) => {
                          if (res.failed.length) props.onError(new Error(res.failed.join("；")));
                          props.onSchema();
                        }, props.onError);
                      }}
                    >
                      导入 DFM 模型
                    </button>
                  </>
                )}
              </div>
              {models.items.map((m) => (
                <div className="model" key={m.id}>
                  <div className="n">{m.name}</div>
                  <div>
                    {m.state === "installed" ? (
                      <span className="pill ok">已安装</span>
                    ) : (
                      <button
                        className="btn small ghost"
                        disabled={Boolean(modelJob)}
                        onClick={() => client.call("models.download", { ids: [m.id] }).then(props.refresh, props.onError)}
                      >
                        <Download size={12} /> {m.state === "partial" ? "继续" : "下载"}
                      </button>
                    )}
                  </div>
                  <div className="d">
                    {formatBytes(m.size)}
                    {m.state === "partial" && ` · 已下载 ${formatBytes(m.partial)}`}
                    {m.base && " · 基础"}
                  </div>
                </div>
              ))}
            </>
          )}
          {tab === "library" && <FaceLibrary embeddings={props.embeddings} onChange={props.onEmbeddings} onError={props.onError} />}
          {tab === "run" && (
            <>
              <h3>运行</h3>
              <p className="sub">{hello ? `${hello.platform} · ${hello.machine} · 可用：${hello.providers.join(" / ")}` : ""}</p>
              {sectionRows(["settings:General", "settings:Misc"], (f) => f.key !== "ImageFormatToggle")}
              {sectionRows(["settings:Webcam and Virtualcam Settings"])}
            </>
          )}
          {tab === "output" && (
            <>
              <h3>输出</h3>
              <div className="kv" style={{ marginTop: 12 }}>
                <span className="k">保存位置</span>
                <div style={{ display: "flex", gap: 8, alignItems: "center", minWidth: 0 }}>
                  <span className="path" title={paths?.output_dir}>{paths?.output_dir}</span>
                  <button className="btn small" onClick={() => changePath("output_dir")}>更改</button>
                </div>
              </div>
              {sectionRows(["settings:Output Settings", "settings:Misc"], (f) => f.key !== "KeepModelsAliveToggle")}
              {sectionRows(["settings:Video Recording Settings"])}
            </>
          )}
          {tab === "about" && (
            <>
              <h3>VisoMaster Studio</h3>
              <p className="sub">版本 {hello?.version}</p>
              <p style={{ color: "var(--text-2)", fontSize: 12.5, lineHeight: 1.6 }}>
                基于 VisoMaster 与 VisoMaster Fusion v3.12.3 开发，遵循 GPL-3.0。模型文件来自各自发布方，使用前请确认对应许可。
              </p>
              <div className="kv">
                <span className="k">模型</span>
                <span className="path">{hello?.model_dir}</span>
                <span className="k">FFmpeg</span>
                <span>{hello?.ffmpeg ? "可用" : "未找到"}</span>
              </div>
            </>
          )}
        </div>
      </aside>
    </>
  );
}

export function JobsPopover({ jobs, onClose, onError }: { jobs: Job[]; onClose: () => void; onError: (e: unknown) => void }) {
  const list = [...jobs].reverse();
  return (
    <>
      <div style={{ position: "fixed", inset: 0, zIndex: 29 }} onClick={onClose} />
      <div className="popover" role="dialog" aria-label="任务">
        <div className="pane-head" style={{ padding: "0 6px 0 8px" }}>
          任务
          <button className="btn small ghost" onClick={() => client.call("jobs.clear").catch(onError)} disabled={!jobs.some((j) => ["done", "failed", "cancelled"].includes(j.state))}>
            清除已结束
          </button>
        </div>
        {list.length === 0 && <div className="empty-line">暂无任务</div>}
        {list.map((j) => {
          const pct = j.total ? Math.min(100, (j.done / j.total) * 100) : 0;
          const active = j.state === "running" || j.state === "queued";
          return (
            <div className="job" key={j.id}>
              <div className="t" title={j.title}>{j.title}</div>
              <div style={{ display: "flex", gap: 2 }}>
                {active && (
                  <button className="btn small ghost" onClick={() => client.call("jobs.cancel", { job_id: j.id }).catch(onError)}>取消</button>
                )}
                {j.state === "done" && j.result.path && (
                  <button className="btn small ghost" onClick={() => client.call("system.reveal", { path: j.result.path }).catch(onError)}>显示</button>
                )}
              </div>
              {active && (
                <div className="bar">
                  <div style={{ width: `${j.state === "queued" ? 0 : pct}%` }} />
                </div>
              )}
              <div className={`m${j.state === "failed" ? " err" : ""}`}>
                <span>
                  {j.state === "queued" ? "排队中" : j.state === "running" ? j.message || "处理中" : j.state === "done" ? "已完成" : j.state === "cancelled" ? "已取消" : j.message || "失败"}
                </span>
                {j.state === "done" && j.result.seconds != null && <span>{j.result.seconds} 秒</span>}
              </div>
            </div>
          );
        })}
      </div>
    </>
  );
}

function FaceLibrary({ embeddings, onChange, onError }: {
  embeddings: { id: string; name: string }[]; onChange: (l: { id: string; name: string }[]) => void; onError: (e: unknown) => void;
}) {
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const run = (p: Promise<any>) => p.then(onChange, onError);
  const load = async (replace: boolean) => {
    const { open } = await import("@tauri-apps/plugin-dialog");
    const path = await open({ multiple: false, filters: [{ name: "人脸特征", extensions: ["json", "txt"] }] });
    if (typeof path === "string") run(client.call("embeddings.load", { path, replace }));
  };
  const save = async (fmt: "json" | "txt") => {
    const { save } = await import("@tauri-apps/plugin-dialog");
    const path = await save({ defaultPath: fmt === "txt" ? "人脸特征.txt" : "人脸特征.json",
      filters: [fmt === "txt" ? { name: "Rope 文本", extensions: ["txt"] } : { name: "VisoMaster JSON", extensions: ["json"] }] });
    if (!path) return;
    const ids = picked.size ? [...picked] : null;
    client.call("embeddings.save", { path, ids, fmt }).catch(onError);
  };
  const move = (i: number, d: number) => {
    const ids = embeddings.map((e) => e.id);
    const j = i + d;
    if (j < 0 || j >= ids.length) return;
    [ids[i], ids[j]] = [ids[j], ids[i]];
    run(client.call("embeddings.order", { ids }));
  };
  const sortByName = () => run(client.call("embeddings.order", { ids: [...embeddings].sort((a, b) => a.name.localeCompare(b.name, "zh")).map((e) => e.id) }));
  return (
    <>
      <h3>人脸库</h3>
      <p className="sub">{embeddings.length} 个合并人脸{picked.size ? ` · 已选 ${picked.size}` : ""}</p>
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 12 }}>
        <button className="btn small" onClick={() => load(false)}><FolderOpen size={13} /> 载入（追加）</button>
        <button className="btn small" onClick={() => load(true)}>载入（替换）</button>
        <button className="btn small" disabled={!embeddings.length} onClick={() => save("json")}>{picked.size ? "保存所选" : "全部保存"}</button>
        <button className="btn small" disabled={!embeddings.length} onClick={() => save("txt")}>导出为 Rope 格式</button>
        <button className="btn small ghost" disabled={embeddings.length < 2} onClick={sortByName}>按名称排序</button>
      </div>
      {embeddings.length === 0 && <div className="hint-card">在参考脸的“…”菜单里把参考脸合并为一个人脸，或载入人脸特征文件。</div>}
      {embeddings.map((e, i) => (
        <div className="lib-row" key={e.id}>
          <input type="checkbox" checked={picked.has(e.id)} aria-label="选择"
            onChange={(ev) => setPicked((p) => { const n = new Set(p); ev.target.checked ? n.add(e.id) : n.delete(e.id); return n; })} />
          <input className="text lib-name" defaultValue={e.name} aria-label="名称"
            onBlur={(ev) => ev.target.value.trim() && ev.target.value !== e.name && run(client.call("embeddings.rename", { embedding_id: e.id, name: ev.target.value }))}
            onKeyDown={(ev) => ev.key === "Enter" && (ev.target as HTMLInputElement).blur()} />
          <button className="icon-btn small" aria-label="上移" onClick={() => move(i, -1)} disabled={i === 0}><ArrowUp size={13} /></button>
          <button className="icon-btn small" aria-label="下移" onClick={() => move(i, 1)} disabled={i === embeddings.length - 1}><ArrowDown size={13} /></button>
          <button className="icon-btn small" aria-label="删除" onClick={() => client.call("embeddings.remove", { embedding_id: e.id }).then((r) => onChange(r.embeddings), onError)}>
            <Trash2 size={13} />
          </button>
        </div>
      ))}
    </>
  );
}
