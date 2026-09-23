type N = number | null | undefined;

const ok = (x: N): x is number => typeof x === "number" && Number.isFinite(x);
/** Treat float dust (e.g. -1e-12) as zero so it never renders as "-0.00%". */
const clean = (x: number) => (Math.abs(x) < 1e-9 ? 0 : x);

export const pct = (x: N, digits = 1) => (ok(x) ? `${(x * 100).toFixed(digits)}%` : "–");
export function signedPct(x: N, digits = 1): string {
  if (!ok(x)) return "–";
  const v = Number((clean(x) * 100).toFixed(digits));
  return `${v > 0 ? "+" : ""}${(v === 0 ? 0 : v).toFixed(digits)}%`;
}
export const num = (x: N, digits = 2) => (ok(x) ? x.toFixed(digits) : "–");
export const price = (x: N) =>
  ok(x) ? x.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 }) : "–";

export function money(x: N): string {
  if (!ok(x)) return "–";
  const a = Math.abs(x);
  if (a >= 1e12) return `$${(x / 1e12).toFixed(2)}T`;
  if (a >= 1e9) return `$${(x / 1e9).toFixed(1)}B`;
  if (a >= 1e6) return `$${(x / 1e6).toFixed(2)}M`;
  return `${x < 0 ? "-" : ""}$${Math.abs(x).toLocaleString("en-US", { maximumFractionDigits: 0 })}`;
}

export const tone = (x: N) => (!ok(x) || Math.abs(x) < 5e-5 ? "" : x > 0 ? "up" : "down");

export function formatMetric(x: N, fmt: string): string {
  if (fmt === "pct") return pct(x);
  if (fmt === "ratio") return ok(x) ? `${x.toFixed(2)}x` : "–";
  return num(x);
}

export const FACTOR_LABEL: Record<string, string> = {
  value: "Value",
  quality: "Quality",
  momentum: "Momentum",
  growth: "Growth",
  low_vol: "Low Vol",
};

export function gradeClass(g: string | undefined): string {
  if (!g || g === "-") return "g-none";
  if (g.startsWith("A")) return "g-a";
  if (g.startsWith("B")) return "g-b";
  if (g === "C") return "g-c";
  return "g-d";
}
