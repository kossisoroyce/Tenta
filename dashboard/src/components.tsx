import type { ReactNode } from "react";
import { Text } from "@cloudflare/kumo";

/* -------------------------------- Panel ----------------------------------- */

interface PanelProps {
  title?: ReactNode;
  eyebrow?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
  padding?: boolean;
}

export function Panel({ title, eyebrow, actions, children, className, padding = true }: PanelProps) {
  return (
    <section className={`panel${className ? ` ${className}` : ""}`}>
      {(title || eyebrow || actions) && (
        <header className="panel-head">
          <div className="panel-head-titles">
            {eyebrow && <p className="eyebrow">{eyebrow}</p>}
            {title && (
              <Text variant="heading3" as="h2">
                {title}
              </Text>
            )}
          </div>
          {actions && <div className="panel-head-actions">{actions}</div>}
        </header>
      )}
      <div className={padding ? "panel-body" : "panel-body flush"}>{children}</div>
    </section>
  );
}

/* ------------------------------- Stat tile -------------------------------- */

interface StatTileProps {
  label: ReactNode;
  value: ReactNode;
  sub?: ReactNode;
  accent?: ReactNode;
  tone?: "default" | "danger" | "warning" | "success";
}

export function StatTile({ label, value, sub, accent, tone = "default" }: StatTileProps) {
  return (
    <div className={`stat-tile tone-${tone}`}>
      <div className="stat-tile-top">
        <span className="stat-label">{label}</span>
        {accent}
      </div>
      <div className="stat-value">{value}</div>
      {sub && <div className="stat-sub">{sub}</div>}
    </div>
  );
}

/* ----------------------------- Info grid ---------------------------------- */

export function InfoGrid({ children }: { children: ReactNode }) {
  return <dl className="info-grid">{children}</dl>;
}

export function InfoRow({ label, children }: { label: ReactNode; children: ReactNode }) {
  return (
    <div className="info-row">
      <dt>{label}</dt>
      <dd>{children}</dd>
    </div>
  );
}

/* ------------------------------- Sparkline -------------------------------- */

interface SparklineProps {
  data: number[];
  stroke?: string;
  fill?: string;
  height?: number;
  width?: number;
}

export function Sparkline({
  data,
  stroke = "var(--color-kumo-brand)",
  fill = "transparent",
  height = 44,
  width = 160,
}: SparklineProps) {
  if (data.length < 2) return <div className="sparkline-empty" />;
  const min = Math.min(...data);
  const max = Math.max(...data);
  const range = max - min || 1;
  const stepX = width / (data.length - 1);
  const points = data.map((v, i) => {
    const x = i * stepX;
    const y = height - 4 - ((v - min) / range) * (height - 8);
    return [x, y] as const;
  });
  const line = points.map(([x, y], i) => `${i === 0 ? "M" : "L"}${x.toFixed(1)} ${y.toFixed(1)}`).join(" ");
  const area = `${line} L${width} ${height} L0 ${height} Z`;
  return (
    <svg className="sparkline" viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none">
      {fill !== "transparent" && <path d={area} fill={fill} stroke="none" />}
      <path d={line} fill="none" stroke={stroke} strokeWidth={1.75} strokeLinejoin="round" />
    </svg>
  );
}

/* --------------------------------- Bars ----------------------------------- */

export function Bars({
  items,
}: {
  items: Array<{ label: string; value: number; max: number; color: string }>;
}) {
  return (
    <div className="bars">
      {items.map((item) => (
        <div className="bar-row" key={item.label}>
          <span className="bar-label">{item.label}</span>
          <div className="bar-track">
            <div
              className="bar-fill"
              style={{
                width: `${item.max ? (item.value / item.max) * 100 : 0}%`,
                background: item.color,
              }}
            />
          </div>
          <span className="bar-value">{item.value.toLocaleString("en-US")}</span>
        </div>
      ))}
    </div>
  );
}

/* --------------------------------- Misc ----------------------------------- */

export function PageHeader({
  eyebrow,
  title,
  description,
  actions,
}: {
  eyebrow: string;
  title: string;
  description?: string;
  actions?: ReactNode;
}) {
  return (
    <div className="page-header">
      <div>
        <p className="eyebrow">{eyebrow}</p>
        <Text variant="heading2" as="h1">
          {title}
        </Text>
        {description && (
          <p className="page-description">{description}</p>
        )}
      </div>
      {actions && <div className="page-header-actions">{actions}</div>}
    </div>
  );
}

export function EmptyState({ title, hint }: { title: string; hint?: string }) {
  return (
    <div className="empty-state">
      <strong>{title}</strong>
      {hint && <span>{hint}</span>}
    </div>
  );
}

export function LoadingState() {
  return <div className="loading-state">Loading…</div>;
}

export function ErrorState({ message }: { message: string }) {
  return <div className="error-state">Could not load data — {message}</div>;
}

export function Dot({ color }: { color: string }) {
  return <span className="dot" style={{ background: color }} />;
}
