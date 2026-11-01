import { RotateCcw } from "lucide-react";
import { useState } from "react";
import { fieldLabel, NOT_YET, UI_ONLY } from "../lib/labels";
import type { Field } from "../lib/types";

export type Values = Record<string, any>;

export function visible(field: Field, values: Values) {
  for (const c of field.visible_when ?? []) {
    if ("toggles" in c) {
      const states = c.toggles.map((k) => Boolean(values[k]));
      const state = c.mode === "any" ? states.some(Boolean) : states.every(Boolean);
      if (state !== c.value) return false;
    } else if (String(values[c.select]) !== c.equals) return false;
  }
  return true;
}

export const shown = (f: Field) => !UI_ONLY.has(f.key) && !NOT_YET.has(f.key);

export const same = (a: any, b: any) => (typeof a === "number" && typeof b === "number" ? Math.abs(a - b) < 1e-9 : a === b);

function SliderRow({ field, value, label, reset, className, onChange }: {
  field: Field; value: number; label: string; reset: JSX.Element; className: string; onChange: (v: number) => void;
}) {
  const min = field.min ?? 0;
  const max = field.max ?? 100;
  const step = field.type === "decimal" ? field.step ?? 0.1 : field.step ?? 1;
  const [draft, setDraft] = useState<string | null>(null);
  const pct = max > min ? ((value - min) / (max - min)) * 100 : 0;
  const text = field.type === "decimal" ? Number(value).toFixed(field.decimals ?? 2) : String(Math.round(value));
  const commit = (raw: string) => {
    setDraft(null);
    const v = Number(raw);
    if (Number.isFinite(v)) onChange(Math.min(max, Math.max(min, v)));
  };
  return (
    <div className={className} title={field.help}>
      <div className="top">
        <div className="label">
          <span>{label}</span>
          {reset}
        </div>
        <input
          className="num"
          aria-label={label}
          value={draft ?? text}
          onChange={(e) => setDraft(e.target.value)}
          onBlur={(e) => commit(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") (e.target as HTMLInputElement).blur();
            if (e.key === "Escape") setDraft(null);
          }}
        />
      </div>
      <input
        className="slider"
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        aria-label={label}
        style={{ ["--p" as any]: `${pct}%` }}
        onChange={(e) => onChange(Number(e.target.value))}
      />
    </div>
  );
}

export function FieldRow({ field, value, label, onChange, onReset }: {
  field: Field; value: any; label?: string; onChange: (v: any) => void; onReset: () => void;
}) {
  const modified = !same(value, field.default);
  const text = label ?? fieldLabel(field.key, field.label);
  const reset = (
    <button className="icon-btn small reset" title="恢复默认" onClick={onReset} disabled={!modified} aria-label="恢复默认">
      <RotateCcw size={11} />
    </button>
  );
  const sub = field.level > 1 ? " sub" : "";
  if (field.type === "integer" || field.type === "decimal") {
    return (
      <SliderRow field={field} value={Number(value ?? field.default)} label={text} reset={reset}
        className={`row slider${sub}${modified ? " mod" : ""}`} onChange={onChange} />
    );
  }
  let control;
  if (field.type === "toggle") {
    control = <button className={`switch${value ? " on" : ""}`} role="switch" aria-checked={Boolean(value)} aria-label={text} onClick={() => onChange(!value)} />;
  } else if (field.type === "select") {
    const options = field.options?.length ? field.options : [String(value ?? "")];
    control = (
      <select className="select" value={String(value ?? "")} onChange={(e) => onChange(e.target.value)} aria-label={text}>
        {options.map((o) => <option key={o} value={o}>{o || "—"}</option>)}
      </select>
    );
  } else {
    control = <input className="text" defaultValue={String(value ?? "")} onBlur={(e) => e.target.value !== value && onChange(e.target.value)} aria-label={text} />;
  }
  return (
    <div className={`row${sub}${modified ? " mod" : ""}`} title={field.help}>
      <div className="label">
        <span>{text}</span>
        {reset}
      </div>
      {control}
    </div>
  );
}
