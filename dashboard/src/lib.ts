// Formatting and semantic-mapping helpers shared across views.

type BadgeVariant =
  | "success"
  | "warning"
  | "error"
  | "neutral"
  | "blue"
  | "orange"
  | "purple"
  | "teal";

export function fmtInt(n: number | undefined | null): string {
  if (n === undefined || n === null || Number.isNaN(n)) return "—";
  return Math.round(n).toLocaleString("en-US");
}

export function fmtNum(n: number | undefined | null, digits = 3): string {
  if (n === undefined || n === null || Number.isNaN(n)) return "—";
  return n.toFixed(digits);
}

export function fmtPct(x: number | undefined | null, digits = 1): string {
  if (x === undefined || x === null || Number.isNaN(x)) return "—";
  return `${(x * 100).toFixed(digits)}%`;
}

export function fmtMs(x: number | undefined | null): string {
  if (x === undefined || x === null || Number.isNaN(x)) return "—";
  return `${x.toFixed(x < 10 ? 2 : 1)} ms`;
}

export function relTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "—";
  const diff = Date.now() - then;
  const mins = Math.round(diff / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.round(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.round(hrs / 24);
  return `${days}d ago`;
}

export function titleize(value: string): string {
  return value
    .replace(/[_-]/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

export const decisionVariant = (d: string): BadgeVariant =>
  ({ allow: "success", review: "warning", block: "error" } as Record<string, BadgeVariant>)[d] ??
  "neutral";

export const severityVariant = (s: string): BadgeVariant =>
  ({ critical: "error", warn: "orange", watch: "blue", stable: "neutral" } as Record<
    string,
    BadgeVariant
  >)[s] ?? "neutral";

export const severityColor = (s: string): string =>
  ({
    critical: "var(--color-kumo-danger)",
    warn: "var(--sev-warn)",
    watch: "var(--color-kumo-info)",
    stable: "var(--color-kumo-success)",
  } as Record<string, string>)[s] ?? "var(--text-color-kumo-subtle)";

export const stageVariant = (stage: string): BadgeVariant =>
  ({
    champion: "success",
    shadow: "blue",
    candidate: "neutral",
    fallback: "warning",
    archived: "neutral",
  } as Record<string, BadgeVariant>)[stage] ?? "neutral";

export const riskVariant = (risk: string): BadgeVariant =>
  ({ high: "error", medium: "orange", low: "neutral" } as Record<string, BadgeVariant>)[risk] ??
  "neutral";

export const healingVariant = (status: string): BadgeVariant =>
  ({
    proposed: "warning",
    running: "blue",
    completed: "success",
    rejected: "neutral",
    rolled_back: "neutral",
  } as Record<string, BadgeVariant>)[status] ?? "neutral";

export const driftStatusVariant = (status: string): BadgeVariant =>
  ({ active: "warning", acknowledged: "neutral", escalated: "error" } as Record<
    string,
    BadgeVariant
  >)[status] ?? "neutral";

export const runtimeStatusVariant = (status: string | undefined | null): BadgeVariant =>
  ({
    healthy: "success",
    connected: "success",
    valid: "success",
    succeeded: "success",
    partial: "warning",
    degraded: "warning",
    unavailable: "warning",
    failed: "error",
    invalid: "error",
    denied: "error",
  } as Record<string, BadgeVariant>)[String(status ?? "").toLowerCase()] ?? "neutral";
