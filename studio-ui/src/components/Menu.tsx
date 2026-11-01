import { useEffect, useRef, useState, type ReactNode } from "react";

export type MenuItem = { label: string; hint?: string; danger?: boolean; disabled?: boolean; onSelect: () => void } | "divider";

/** Small dropdown anchored to its trigger. Closes on Escape, outside click or selection. */
export function Menu({ trigger, items, align = "left", title }: {
  trigger: (open: boolean, toggle: () => void) => ReactNode; items: MenuItem[]; align?: "left" | "right"; title?: string;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => ref.current && !ref.current.contains(e.target as Node) && setOpen(false);
    const key = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.stopPropagation();
        setOpen(false);
      }
    };
    window.addEventListener("mousedown", close);
    window.addEventListener("keydown", key, true);
    return () => {
      window.removeEventListener("mousedown", close);
      window.removeEventListener("keydown", key, true);
    };
  }, [open]);
  return (
    <div className="menu-anchor" ref={ref}>
      {trigger(open, () => setOpen((o) => !o))}
      {open && (
        <div className={`menu ${align}`} role="menu">
          {title && <div className="menu-title">{title}</div>}
          {items.map((item, i) =>
            item === "divider" ? (
              <div key={i} className="menu-divider" />
            ) : (
              <button key={i} role="menuitem" className={`menu-item${item.danger ? " danger" : ""}`} disabled={item.disabled}
                onClick={() => { setOpen(false); item.onSelect(); }}>
                <span>{item.label}</span>
                {item.hint && <span className="menu-hint">{item.hint}</span>}
              </button>
            ),
          )}
        </div>
      )}
    </div>
  );
}

/** Asks for a short name inside the window. Resolves null when cancelled. */
export function NamePrompt({ title, initial, confirm, onDone }: {
  title: string; initial?: string; confirm: string; onDone: (value: string | null) => void;
}) {
  const [value, setValue] = useState(initial ?? "");
  const input = useRef<HTMLInputElement>(null);
  useEffect(() => input.current?.select(), []);
  return (
    <>
      <div className="scrim" style={{ inset: 0 }} onClick={() => onDone(null)} />
      <form className="prompt" role="dialog" aria-label={title}
        onSubmit={(e) => { e.preventDefault(); if (value.trim()) onDone(value.trim()); }}>
        <div className="prompt-title">{title}</div>
        <input ref={input} className="text prompt-input" value={value} onChange={(e) => setValue(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Escape") { e.stopPropagation(); onDone(null); } }} />
        <div className="prompt-actions">
          <button type="button" className="btn" onClick={() => onDone(null)}>取消</button>
          <button type="submit" className="btn primary" disabled={!value.trim()}>{confirm}</button>
        </div>
      </form>
    </>
  );
}
