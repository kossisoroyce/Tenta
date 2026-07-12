import type { ReactNode } from "react";
import { Badge, Button } from "@cloudflare/kumo";
import {
  ChartLineUpIcon,
  ChatCircleDotsIcon,
  DatabaseIcon,
  GaugeIcon,
  HeartbeatIcon,
  LightningIcon,
  MoonIcon,
  ScalesIcon,
  StackIcon,
  SunIcon,
  WarningDiamondIcon,
} from "@phosphor-icons/react";

import type { OverviewResponse } from "./api";
import { Logo } from "./components/Logo";
import { navigate, type Route, useRoute } from "./router";

interface NavItem {
  route: Route;
  label: string;
  icon: ReactNode;
  badge?: (o: OverviewResponse | null) => number | null;
}

interface NavGroup {
  label: string;
  items: NavItem[];
}

const NAV: NavGroup[] = [
  {
    label: "Runtime",
    items: [
      { route: "overview", label: "Overview", icon: <GaugeIcon size={17} weight="bold" /> },
      { route: "scoring", label: "Live Decisions", icon: <LightningIcon size={17} /> },
      { route: "storage", label: "Storage", icon: <DatabaseIcon size={17} /> },
    ],
  },
  {
    label: "Intelligence",
    items: [
      { route: "models", label: "Models", icon: <StackIcon size={17} /> },
      {
        route: "drift",
        label: "Model Health",
        icon: <WarningDiamondIcon size={17} />,
        badge: (o) => o?.summary.open_drift_alerts || null,
      },
    ],
  },
  {
    label: "Adaptation",
    items: [
      {
        route: "healing",
        label: "Adaptive Healing",
        icon: <HeartbeatIcon size={17} />,
        badge: (o) => o?.summary.healing_pending || null,
      },
    ],
  },
  {
    label: "Govern",
    items: [
      { route: "governance", label: "Audit & Approvals", icon: <ScalesIcon size={17} /> },
      { route: "feedback", label: "Human Feedback", icon: <ChatCircleDotsIcon size={17} /> },
    ],
  },
  {
    label: "Performance",
    items: [{ route: "benchmarks", label: "Metrics", icon: <ChartLineUpIcon size={17} /> }],
  },
];

interface ShellProps {
  overview: OverviewResponse | null;
  mode: "light" | "dark";
  onToggleTheme: () => void;
  children: ReactNode;
}

export function Shell({ overview, mode, onToggleTheme, children }: ShellProps) {
  const route = useRoute();
  const runtimeStatus = overview?.health.status ?? "unknown";
  const healthy = runtimeStatus === "healthy";

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark">
            <Logo size={26} />
          </div>
          <div>
            <div className="brand-name">Tenta</div>
            <div className="brand-sub">Decision Runtime</div>
          </div>
        </div>

        <nav className="nav" aria-label="Primary">
          {NAV.map((group) => (
            <div className="nav-group" key={group.label}>
              <span className="nav-group-label">{group.label}</span>
              {group.items.map((item) => {
                const count = item.badge ? item.badge(overview) : null;
                return (
                  <a
                    key={item.route}
                    href={`#/${item.route}`}
                    className={route === item.route ? "nav-item active" : "nav-item"}
                    onClick={(e) => {
                      e.preventDefault();
                      navigate(item.route);
                    }}
                  >
                    <span className="nav-icon">{item.icon}</span>
                    <span className="nav-text">{item.label}</span>
                    {count ? <span className="nav-count">{count}</span> : null}
                  </a>
                );
              })}
            </div>
          ))}
        </nav>

        <div className="sidebar-footer">
          <div className="sidebar-health">
            <span className={`dot ${healthy ? "ok" : "bad"}`} />
            <span>Runtime {healthy ? "healthy" : runtimeStatus}</span>
          </div>
          <div className="sidebar-champion">
            Live model · {overview?.summary.champion ?? "—"}
          </div>
        </div>
      </aside>

      <div className="main">
        <header className="topbar">
          <div className="topbar-status">
            <Badge variant="success" appearance="dot">
              Production
            </Badge>
            <span className="topbar-sep" />
            <span className="topbar-chip">
              <span className="topbar-chip-label">Workload</span>
              <span className="topbar-chip-value">
                {overview?.health.workload?.name ?? "—"}
              </span>
            </span>
            <span className="topbar-chip">
              <span className="topbar-chip-label">Live model</span>
              <span className="topbar-chip-value">
                {overview?.summary.champion ?? "—"}{" "}
                <span className="muted">{overview?.summary.champion_version ?? ""}</span>
              </span>
            </span>
            {overview && overview.summary.shadow && (
              <span className="topbar-chip">
                <span className="topbar-chip-label">Shadow</span>
                <span className="topbar-chip-value">{overview.summary.shadow}</span>
              </span>
            )}
            {overview && overview.summary.open_drift_alerts > 0 && (
              <Badge variant="orange" appearance="dot">
                {overview.summary.open_drift_alerts} open drift
              </Badge>
            )}
            {overview && overview.summary.healing_pending > 0 && (
              <Badge variant="warning" appearance="dot">
                {overview.summary.healing_pending} awaiting approval
              </Badge>
            )}
          </div>

          <div className="topbar-actions">
            <Button
              variant="ghost"
              shape="square"
              aria-label="Toggle colour theme"
              onClick={onToggleTheme}
            >
              {mode === "dark" ? <SunIcon size={18} /> : <MoonIcon size={18} />}
            </Button>
            <div className="operator">
              <span className="operator-avatar">OC</span>
              <div className="operator-meta">
                <span className="operator-name">Operator</span>
                <span className="operator-role">ML governance</span>
              </div>
            </div>
          </div>
        </header>

        <main className="workspace">{children}</main>
      </div>
    </div>
  );
}
