import { useEffect, useMemo, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { Badge, Button } from "@cloudflare/kumo";
import {
  ChartLineUpIcon,
  ChatCircleDotsIcon,
  CommandIcon,
  DatabaseIcon,
  GaugeIcon,
  HeartbeatIcon,
  LightningIcon,
  ListIcon,
  MoonIcon,
  ScalesIcon,
  StackIcon,
  SunIcon,
  WarningDiamondIcon,
} from "@phosphor-icons/react";

import type { OverviewResponse } from "./api";
import { Logo } from "./components/Logo";
import { isOperatorRole, useOperator, type OperatorRole } from "./governance";
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

const ROLE_LABELS: Record<OperatorRole, string> = {
  viewer: "Viewer",
  operator: "Operator",
  analyst: "Analyst",
  detector: "Detector",
  "model-risk": "Model risk",
  admin: "Admin",
};

function initials(actor: string): string {
  const name = actor.split("@")[0] || actor;
  const parts = name.split(/[._-]/).filter(Boolean);
  const value = parts.length > 1 ? `${parts[0][0]}${parts[1][0]}` : name.slice(0, 2);
  return value.toUpperCase();
}

function CommandPalette({
  open,
  onOpenChange,
  overview,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  overview: OverviewResponse | null;
}) {
  const route = useRoute();
  const [query, setQuery] = useState("");

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onOpenChange(false);
    };
    if (open) {
      setQuery("");
      window.addEventListener("keydown", onKey);
    }
    return () => window.removeEventListener("keydown", onKey);
  }, [onOpenChange, open]);

  if (!open) return null;

  const items = NAV.flatMap((group) =>
    group.items.map((item) => ({
      ...item,
      group: group.label,
      count: item.badge ? item.badge(overview) : null,
    })),
  ).filter((item) => {
    const needle = `${item.group} ${item.label}`.toLowerCase();
    return needle.includes(query.trim().toLowerCase());
  });

  return createPortal(
    <div className="modal-overlay command-overlay" onMouseDown={(event) => event.target === event.currentTarget && onOpenChange(false)}>
      <div className="command-panel" role="dialog" aria-modal="true" aria-label="Command palette">
        <div className="command-input-row">
          <CommandIcon size={18} />
          <input
            autoFocus
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Search pages and console actions..."
          />
        </div>
        <div className="command-list">
          {items.map((item) => (
            <button
              type="button"
              className={route === item.route ? "command-item active" : "command-item"}
              key={item.route}
              onClick={() => {
                navigate(item.route);
                onOpenChange(false);
              }}
            >
              <span className="command-icon">{item.icon}</span>
              <span>
                <strong>{item.label}</strong>
                <small>{item.group}</small>
              </span>
              {item.count ? <span className="nav-count">{item.count}</span> : null}
            </button>
          ))}
        </div>
      </div>
    </div>,
    document.body,
  );
}

interface ShellProps {
  overview: OverviewResponse | null;
  mode: "light" | "dark";
  onToggleTheme: () => void;
  children: ReactNode;
}

export function Shell({ overview, mode, onToggleTheme, children }: ShellProps) {
  const route = useRoute();
  const operator = useOperator();
  const [actorDraft, setActorDraft] = useState(operator.actor);
  const [mobileOpen, setMobileOpen] = useState(false);
  const [commandOpen, setCommandOpen] = useState(false);
  const runtimeStatus = overview?.health.status ?? "unknown";
  const healthy = runtimeStatus === "healthy";

  useEffect(() => {
    setActorDraft(operator.actor);
  }, [operator.actor]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setCommandOpen(true);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const sidebar = useMemo(
    () => (
      <aside className={`sidebar${mobileOpen ? " open" : ""}`}>
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
                      setMobileOpen(false);
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
            Live model / {overview?.summary.champion ?? "-"}
          </div>
        </div>
      </aside>
    ),
    [healthy, mobileOpen, overview, route, runtimeStatus],
  );

  return (
    <div className="app-shell">
      {mobileOpen && <button type="button" className="sidebar-backdrop" aria-label="Close menu" onClick={() => setMobileOpen(false)} />}
      {sidebar}

      <div className="main">
        <header className="topbar">
          <Button
            variant="ghost"
            shape="square"
            aria-label="Open navigation"
            className="mobile-menu-button"
            onClick={() => setMobileOpen(true)}
          >
            <ListIcon size={18} />
          </Button>
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
              icon={<CommandIcon size={16} />}
              className="command-button"
              onClick={() => setCommandOpen(true)}
            >
              K
            </Button>
            <Button
              variant="ghost"
              shape="square"
              aria-label="Toggle colour theme"
              onClick={onToggleTheme}
            >
              {mode === "dark" ? <SunIcon size={18} /> : <MoonIcon size={18} />}
            </Button>
            <div className="operator">
              <span className="operator-avatar">{initials(operator.actor)}</span>
              <div className="operator-meta">
                <input
                  className="operator-input"
                  aria-label="Operator identity"
                  value={actorDraft}
                  onChange={(event) => setActorDraft(event.target.value)}
                  onBlur={() => operator.setActor(actorDraft)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter") {
                      operator.setActor(actorDraft);
                      event.currentTarget.blur();
                    }
                  }}
                />
                <select
                  className="operator-role-select"
                  aria-label="Operator role"
                  value={operator.role}
                  onChange={(event) => {
                    const next = event.target.value;
                    if (isOperatorRole(next)) operator.setRole(next);
                  }}
                >
                  {Object.entries(ROLE_LABELS).map(([value, label]) => (
                    <option key={value} value={value}>
                      {label}
                    </option>
                  ))}
                </select>
              </div>
            </div>
          </div>
        </header>

        <main className="workspace">{children}</main>
      </div>
      <CommandPalette open={commandOpen} onOpenChange={setCommandOpen} overview={overview} />
    </div>
  );
}
