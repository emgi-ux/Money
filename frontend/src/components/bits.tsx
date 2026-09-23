import { Fragment, type CSSProperties, type ReactNode } from "react";
import { FACTOR_LABEL, gradeClass, num } from "../format";

export function Card({ title, sub, right, children, pad = true, className = "" }: {
  title?: ReactNode; sub?: ReactNode; right?: ReactNode; children: ReactNode; pad?: boolean; className?: string;
}) {
  return (
    <section className={`card ${className}`}>
      {(title || right) && (
        <div className="card-head">
          {title && <h2>{title}</h2>}
          {sub && <span className="sub">{sub}</span>}
          {right && <div className="right">{right}</div>}
        </div>
      )}
      {pad ? <div className="card-body">{children}</div> : children}
    </section>
  );
}

export function Grade({ g }: { g?: string }) {
  return <span className={`grade ${gradeClass(g)}`}>{g ?? "-"}</span>;
}

/** Z-score shown as a small diverging bar centred on zero (range ±3). */
export function ZCell({ z }: { z: number | null | undefined }) {
  if (z === null || z === undefined) return <span className="muted">–</span>;
  const w = Math.min(Math.abs(z) / 3, 1) * 50;
  return (
    <span className="zcell" title={`z = ${z.toFixed(2)}`}>
      <span>{num(z, 2)}</span>
      <span className="zbar"><span className={z >= 0 ? "pos" : "neg"} style={{ width: `${w}%` }} /></span>
    </span>
  );
}

export function ScoreBar({ score }: { score: number | null | undefined }) {
  if (score === null || score === undefined) return <span className="muted">–</span>;
  return (
    <span className="scorebar">
      <span>{score.toFixed(0)}</span>
      <span className="track"><span className="fill" style={{ width: `${score}%`, display: "block" }} /></span>
    </span>
  );
}

/** Percentile (0-100) bars for each factor. */
export function FactorBars({ pcts }: { pcts: Record<string, number | null | undefined> }) {
  return (
    <div>
      {Object.keys(FACTOR_LABEL).map((f) => {
        const v = pcts[f];
        return (
          <div className="fbar" key={f}>
            <span className="label">{FACTOR_LABEL[f]}</span>
            <span className="track">
              {v != null && <span className="fill" style={{ width: `${v}%` }} />}
              <span className="mid" />
            </span>
            <span className="v">{v == null ? "–" : v.toFixed(0)}</span>
          </div>
        );
      })}
      <div className="hint">Percentile vs universe (sector-neutral). 50 = median.</div>
    </div>
  );
}

export function Stat({ k, v, s, tone }: { k: string; v: ReactNode; s?: ReactNode; tone?: string }) {
  return (
    <div className="stat">
      <div className="k">{k}</div>
      <div className={`v ${tone ?? ""}`}>{v}</div>
      {s && <div className="s">{s}</div>}
    </div>
  );
}

export function Seg<T extends string>({ value, options, onChange }: {
  value: T; options: { v: T; label: string }[]; onChange: (v: T) => void;
}) {
  return (
    <div className="seg">
      {options.map((o) => (
        <button key={o.v} className={o.v === value ? "on" : ""} onClick={() => onChange(o.v)}>{o.label}</button>
      ))}
    </div>
  );
}

/** Diverging background for a value in [-max, max]: red <- gray -> blue. */
export function divergingBg(v: number, max: number): string {
  const t = Math.max(-1, Math.min(1, v / max));
  const pole = t >= 0 ? "var(--div-pos)" : "var(--div-neg)";
  const pctMix = Math.round(Math.abs(t) * 85);
  return `color-mix(in oklab, ${pole} ${pctMix}%, var(--div-mid))`;
}

export function textOn(v: number, max: number): string {
  return Math.abs(v / max) > 0.55 ? "#fff" : "var(--text)";
}

/** Two-column key/value list. */
export function KV({ rows, style }: { rows: [ReactNode, ReactNode][]; style?: CSSProperties }) {
  return (
    <div className="kv" style={style}>
      {rows.map(([k, v], i) => (
        <Fragment key={i}><span className="k">{k}</span><span className="v">{v}</span></Fragment>
      ))}
    </div>
  );
}
