import { ArrowRight, Bookmark, ChevronDown, ChevronLeft, ChevronRight, Combine, MoreHorizontal, Plus, RotateCcw, ScanFace, Search, SlidersHorizontal, UserRound, X } from "lucide-react";
import { Menu } from "./Menu";
import { useMemo, useState } from "react";
import { client } from "../lib/backend";
import { fieldLabel, sectionTitle, TABS } from "../lib/labels";
import type { Face, Field, Schema } from "../lib/types";
import { FieldRow, same, shown, visible, type Values } from "./Params";

// Everyday adjustments shown on the main panel; everything else is under 高级设置.
const BASIC: { key: string; label: string; child?: string; childLabel?: string }[] = [
  { key: "SwapModelSelection", label: "换脸模型" },
  { key: "SimilarityThresholdSlider", label: "相似度" },
  { key: "FaceRestorerEnableToggle", label: "画质修复", child: "FaceRestorerBlendSlider", childLabel: "修复强度" },
  { key: "OverallMaskBlendAmountSlider", label: "边缘柔化" },
  { key: "OccluderEnableToggle", label: "保留遮挡物" },
  { key: "FaceExpressionEnableBothToggle", label: "还原表情" },
];

const GROUP_HINT: Record<string, string> = {
  swap: "模型 · 强度 · 相似度 · 年龄",
  mask: "遮挡 · XSeg · 边框 · 原脸区域",
  quality: "修复 · 色彩 · 融合 · 去噪 · 增强",
  motion: "表情 · 人脸编辑 · 关键点",
  detect: "检测 · 跟踪 · 匹配 · VR180",
};

type Change = (f: Field, v: any) => void;

export function FacesSection(props: {
  targets: Face[];
  sources: Face[];
  selected: string | null;
  disabled: boolean;
  hasMedia: boolean;
  onSelect: (id: string) => void;
  onToggleSource: (id: string) => void;
  onAddSources: () => void;
  onRemoveSource: (id: string) => void;
  onRemoveTarget: (id: string) => void;
  onDetect: () => void;
  dropActive: boolean;
  embeddings: { id: string; name: string }[];
  onToggleEmbedding: (id: string) => void;
  onRemoveEmbedding: (id: string) => void;
  onMerge: () => void;
  onLoadEmbeddings: () => void;
  onSaveEmbeddings: () => void;
}) {
  const byId = useMemo(() => new Map(props.sources.map((s) => [s.id, s])), [props.sources]);
  const target = props.targets.find((t) => t.id === props.selected);
  return (
    <section className="section-block">
      <div className="block-head">
        <span>人脸替换</span>
        <button className="text-action" onClick={props.onDetect} disabled={props.disabled || !props.hasMedia}>
          <ScanFace size={14} /> 重新识别
        </button>
      </div>
      {props.targets.length === 0 ? (
        <div className="hint-card">{props.hasMedia ? "当前画面没有识别到人脸" : "选择素材后自动识别人脸"}</div>
      ) : (
        <div className="mappings">
          {props.targets.map((t, i) => {
            const assigned = (t.sources ?? []).map((id) => byId.get(id)).filter(Boolean) as Face[];
            const merged = (t.embeddings ?? []).map((id) => props.embeddings.find((e) => e.id === id)).filter(Boolean) as { id: string; name: string }[];
            const count = assigned.length + merged.length;
            const on = t.id === props.selected;
            return (
              <div key={t.id} className={`mapping${on ? " on" : ""}`} onClick={() => props.onSelect(t.id)} role="button" tabIndex={0}>
                <img className="avatar" src={client.image(t.image)} alt="" />
                <ArrowRight size={15} className="arrow" />
                {assigned[0] ? (
                  <img className="avatar" src={client.image(assigned[0].image)} alt="" />
                ) : merged[0] ? (
                  <span className="avatar merged"><Combine size={18} /></span>
                ) : (
                  <span className="avatar empty"><UserRound size={16} /></span>
                )}
                <div className="mapping-text">
                  <span className="title">人脸 {i + 1}</span>
                  <span className="sub">
                    {count === 0 ? "未替换" : count > 1 ? `${count} 个来源合并` : assigned[0] ? assigned[0].name.replace(/\.[^.]+$/, "") : merged[0].name}
                  </span>
                </div>
                {props.targets.length > 1 && (
                  <button className="icon-btn small ghost-x" aria-label="移除人脸" title="移除" onClick={(e) => { e.stopPropagation(); props.onRemoveTarget(t.id); }}>
                    <X size={13} />
                  </button>
                )}
              </div>
            );
          })}
        </div>
      )}
      <div className={`library${props.dropActive ? " drop" : ""}`}>
        <span className="library-label">参考脸</span>
        <div className="library-faces">
          {props.sources.map((s) => {
            const on = Boolean(target?.sources?.includes(s.id));
            return (
              <div key={s.id} className={`ref${on ? " on" : ""}`} title={target ? (on ? "取消使用" : `用于人脸 ${props.targets.indexOf(target) + 1}`) : s.name}
                onClick={() => target && props.onToggleSource(s.id)} role="button" tabIndex={0}>
                <img src={client.image(s.image)} alt="" />
                <button className="ref-x" aria-label="移除参考脸" onClick={(e) => { e.stopPropagation(); props.onRemoveSource(s.id); }}>
                  <X size={10} strokeWidth={2.5} />
                </button>
              </div>
            );
          })}
          {props.embeddings.map((e) => {
            const on = Boolean(target?.embeddings?.includes(e.id));
            return (
              <div key={e.id} className={`ref merged${on ? " on" : ""}`} title={`${e.name}（合并人脸）`} onClick={() => target && props.onToggleEmbedding(e.id)} role="button" tabIndex={0}>
                <span>{e.name.slice(0, 1)}</span>
                <button className="ref-x" aria-label="移除合并人脸" onClick={(ev) => { ev.stopPropagation(); props.onRemoveEmbedding(e.id); }}>
                  <X size={10} strokeWidth={2.5} />
                </button>
              </div>
            );
          })}
          <button className="ref add" title="添加参考脸" aria-label="添加参考脸" onClick={props.onAddSources} disabled={props.disabled}>
            <Plus size={14} />
          </button>
        </div>
        <Menu align="right" title="人脸库"
          trigger={(_, toggle) => (
            <button className="icon-btn small library-more" onClick={toggle} aria-label="人脸库" title="人脸库" disabled={props.disabled}>
              <MoreHorizontal size={15} />
            </button>
          )}
          items={[
            { label: "把参考脸合并为一个人脸…", disabled: props.sources.length === 0, onSelect: props.onMerge },
            "divider",
            { label: "载入人脸特征…", onSelect: props.onLoadEmbeddings },
            { label: "保存人脸特征…", disabled: props.embeddings.length === 0, onSelect: props.onSaveEmbeddings },
          ]}
        />
      </div>
    </section>
  );
}

export function BasicAdjust({ schema, values, onChange }: { schema: Schema; values: Values; onChange: Change }) {
  const fields = useMemo(() => new Map(schema.sections.flatMap((s) => s.fields.map((f) => [f.key, f] as const))), [schema]);
  const rows: JSX.Element[] = [];
  for (const b of BASIC) {
    const f = fields.get(b.key);
    if (!f) continue;
    rows.push(<FieldRow key={b.key} field={f} label={b.label} value={values[b.key] ?? f.default} onChange={(v) => onChange(f, v)} onReset={() => onChange(f, f.default)} />);
    const child = b.child ? fields.get(b.child) : undefined;
    if (child && values[b.key]) {
      rows.push(<FieldRow key={child.key} field={{ ...child, level: 2 }} label={b.childLabel} value={values[child.key] ?? child.default}
        onChange={(v) => onChange(child, v)} onReset={() => onChange(child, child.default)} />);
    }
  }
  return (
    <section className="section-block">
      <div className="block-head"><span>调整</span></div>
      <div className="rows">{rows}</div>
    </section>
  );
}

export function AdvancedPanel({ schema, values, faceLabel, onChange, onResetAll, onApplyAll, onClose, presets, onOpenPresets,
  onApplyPreset, onSavePreset, onDeletePreset, onApplyReaging }: {
  schema: Schema; values: Values; faceLabel: string | null; onChange: Change;
  onResetAll: () => void; onApplyAll: () => void; onClose: () => void;
  presets: string[]; onOpenPresets: () => void; onApplyPreset: (n: string) => void; onSavePreset: () => void;
  onDeletePreset: (n: string) => void; onApplyReaging: () => void;
}) {
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState<string | null>(null);
  const [openSection, setOpenSection] = useState<Record<string, boolean>>({});
  const byId = useMemo(() => new Map(schema.sections.map((s) => [s.id, s])), [schema]);
  const total = useMemo(() => schema.sections.reduce((n, s) => n + s.fields.filter(shown).length, 0), [schema]);
  const q = query.trim().toLowerCase();
  const hits = useMemo(() => {
    if (!q) return [];
    const out: { title: string; field: Field }[] = [];
    for (const s of schema.sections) for (const f of s.fields) {
      if (!shown(f)) continue;
      const hay = `${fieldLabel(f.key, f.label)} ${f.label} ${f.key} ${sectionTitle(s.id, s.title)}`.toLowerCase();
      if (hay.includes(q)) out.push({ title: sectionTitle(s.id, s.title), field: f });
    }
    return out.slice(0, 80);
  }, [q, schema]);
  const row = (f: Field) => <FieldRow key={f.key} field={f} value={values[f.key] ?? f.default} onChange={(v) => onChange(f, v)} onReset={() => onChange(f, f.default)} />;

  return (
    <div className="advanced">
      <div className="advanced-head">
        <button className="icon-btn" onClick={onClose} aria-label="返回" title="返回 (Esc)"><ChevronLeft size={17} /></button>
        <span className="title">高级设置</span>
        {faceLabel && <span className="muted">{faceLabel}</span>}
        <Menu align="right" title="预设"
          trigger={(_, toggle) => (
            <button className="text-action" onClick={() => { onOpenPresets(); toggle(); }}><Bookmark size={13} /> 预设</button>
          )}
          items={[
            ...presets.map((n) => ({ label: n, hint: "应用", onSelect: () => onApplyPreset(n) })),
            ...(presets.length ? (["divider"] as const) : []),
            { label: "保存当前设置为预设…", onSelect: onSavePreset },
            ...presets.map((n) => ({ label: `删除“${n}”`, danger: true, onSelect: () => onDeletePreset(n) })),
          ]}
        />
      </div>
      <label className="search">
        <Search size={14} />
        <input placeholder={`搜索 ${total} 项参数`} value={query} onChange={(e) => setQuery(e.target.value)} onKeyDown={(e) => e.key === "Escape" && (setQuery(""), e.stopPropagation())} />
        {query && <button className="icon-btn small" onClick={() => setQuery("")} aria-label="清除"><X size={12} /></button>}
      </label>
      <div className="scroll advanced-body">
        {q ? (
          <div className="rows">
            {hits.length === 0 && <div className="hint-card">没有匹配的参数</div>}
            {hits.map(({ title, field }) => (
              <div key={field.key} className="hit">
                <span className="hit-path">{title}{!visible(field, values) && " · 需先开启上级选项"}</span>
                {row(field)}
              </div>
            ))}
          </div>
        ) : (
          TABS.map((g) => {
            const sections = g.sections.map((id) => byId.get(id)).filter(Boolean) as typeof schema.sections;
            const fields = sections.flatMap((s) => s.fields.filter(shown));
            const changed = fields.filter((f) => !same(values[f.key] ?? f.default, f.default)).length;
            const isOpen = open === g.id;
            return (
              <div key={g.id} className={`group${isOpen ? " open" : ""}`}>
                <button className="group-head" onClick={() => setOpen(isOpen ? null : g.id)} aria-expanded={isOpen}>
                  <span className="group-text">
                    <span className="name">{g.label}{changed > 0 && <em>已调整 {changed}</em>}</span>
                    <span className="desc">{GROUP_HINT[g.id]}</span>
                  </span>
                  <span className="count">{fields.length}</span>
                  {isOpen ? <ChevronDown size={15} /> : <ChevronRight size={15} />}
                </button>
                {isOpen && sections.map((s) => {
                  const list = s.fields.filter(shown);
                  if (!list.length) return null;
                  const sOpen = openSection[s.id] ?? sections.length === 1;
                  const sChanged = list.filter((f) => !same(values[f.key] ?? f.default, f.default)).length;
                  return (
                    <div key={s.id} className="subsection">
                      {sections.length > 1 && (
                        <button className="sub-head" onClick={() => setOpenSection((o) => ({ ...o, [s.id]: !sOpen }))}>
                          <ChevronRight size={13} className={sOpen ? "rot" : ""} />
                          {sectionTitle(s.id, s.title)}
                          {sChanged > 0 && <em>{sChanged}</em>}
                        </button>
                      )}
                      {sOpen && (
                        <div className="rows">
                          {list.filter((f) => visible(f, values)).map(row)}
                          {s.id === "swapper:Face Re-Aging" && values.FaceReagingEnableToggle && (
                            <button className="btn small apply-btn" onClick={onApplyReaging}>应用年龄调整</button>
                          )}
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            );
          })
        )}
      </div>
      <div className="advanced-foot">
        <button className="text-action" onClick={onResetAll}><RotateCcw size={13} /> 全部恢复默认</button>
        <span className="spacer" />
        <button className="text-action" onClick={onApplyAll}>应用到所有人脸</button>
      </div>
    </div>
  );
}

export function AdvancedButton({ onClick, changed }: { onClick: () => void; changed: number }) {
  return (
    <button className="btn advanced-btn" onClick={onClick}>
      <SlidersHorizontal size={15} /> 高级设置
      {changed > 0 && <span className="pill-count">{changed}</span>}
    </button>
  );
}
