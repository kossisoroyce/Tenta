import { useCallback, useState } from "react";
import { Badge, Button } from "@cloudflare/kumo";
import { ArrowsClockwiseIcon } from "@phosphor-icons/react";

import { getDrift, updateDrift } from "../api";
import { ErrorState, LoadingState, PageHeader, RefreshMeta, StatTile } from "../components";
import { useOperator, useToast } from "../governance";
import { useApi } from "../hooks";
import { driftStatusVariant, fmtInt, fmtNum, fmtPct, relTime, severityColor, severityVariant } from "../lib";
import { navigate, useRouteParams } from "../router";

export function Drift() {
  const { data, error, loading, updatedAt, refresh } = useApi(getDrift, 8000);
  const operator = useOperator();
  const toast = useToast();
  const params = useRouteParams();
  const [busy, setBusy] = useState<string | null>(null);

  const act = useCallback(
    async (key: string, fn: () => Promise<unknown>, successTitle: string, successDetail?: string) => {
      setBusy(key);
      try {
        await fn();
        await refresh();
        toast.notify({ tone: "success", title: successTitle, detail: successDetail });
      } catch (err) {
        toast.notify({ tone: "error", title: "Action failed", detail: err instanceof Error ? err.message : "Drift action failed" });
      } finally {
        setBusy(null);
      }
    },
    [refresh, toast],
  );

  if (loading && !data) return <LoadingState />;
  if (error && !data) return <ErrorState message={error} />;
  if (!data) return null;

  const c = data.counts;
  const focus = params.get("focus");
  const canAct = operator.can("drift.acknowledge");

  return (
    <>
      <PageHeader
        eyebrow="Model Health"
        title="Health signals by segment"
        description="Feature stability, data quality, and concept-drift monitors comparing the current window against baseline."
        actions={
          <>
            <Button variant="ghost" shape="square" aria-label="Refresh" onClick={refresh}>
              <ArrowsClockwiseIcon size={16} />
            </Button>
            <RefreshMeta updatedAt={updatedAt} intervalMs={8000} />
          </>
        }
      />

      <div className="kpi-row">
        <StatTile label="Open signals" value={fmtInt(data.open_alerts)} sub="Active critical + warn" tone={data.open_alerts ? "warning" : "default"} />
        <StatTile label="Critical" value={fmtInt(c.critical || 0)} tone={c.critical ? "danger" : "default"} />
        <StatTile label="Warning" value={fmtInt(c.warn || 0)} tone={c.warn ? "warning" : "default"} />
        <StatTile label="Segments monitored" value={fmtInt(data.monitors.length)} sub="Across workload, channel, device, subject age" />
      </div>

      <div className="alert-stack">
        {data.monitors.map((m) => {
          const ratio = Math.min(1.4, m.statistic / m.threshold);
          return (
            <article className={`alert-card sev-${m.severity}${focus === m.id ? " focused" : ""}`} key={m.id}>
              <div className="alert-rail" style={{ background: severityColor(m.severity) }} />
              <div className="alert-content">
                <div className="alert-head">
                  <div className="alert-titles">
                    <div className="alert-title-row">
                      <h3>{m.segment}</h3>
                      <Badge variant={severityVariant(m.severity)}>{m.severity}</Badge>
                      <Badge variant={driftStatusVariant(m.status)} appearance="dot">{m.status}</Badge>
                    </div>
                    <p className="alert-sub">
                      <span className="mono">{m.detector}</span> on{" "}
                      <span className="mono">{m.feature}</span> · {fmtInt(m.population)} events
                    </p>
                  </div>
                  <div className="alert-actions">
                    <Button
                      variant="ghost"
                      size="sm"
                      disabled={!canAct || m.status === "acknowledged"}
                      loading={busy === `ack-${m.id}`}
                      onClick={() =>
                        act(
                          `ack-${m.id}`,
                          () => updateDrift(m.id, "acknowledge", operator.payload("Acknowledged drift monitor from console.")),
                          "Drift acknowledged",
                          m.segment,
                        )
                      }
                    >
                      Acknowledge
                    </Button>
                    <Button
                      variant="secondary"
                      size="sm"
                      disabled={!operator.can("drift.escalate") || m.status === "escalated"}
                      loading={busy === `esc-${m.id}`}
                      onClick={() =>
                        act(
                          `esc-${m.id}`,
                          () => updateDrift(m.id, "escalate", operator.payload("Escalated drift monitor from console.")),
                          "Drift escalated",
                          m.segment,
                        )
                      }
                    >
                      Escalate
                    </Button>
                  </div>
                </div>

                <div className="drift-metric">
                  <div className="drift-metric-head">
                    <span>
                      Statistic <b className="mono">{fmtNum(m.statistic, 3)}</b> vs threshold{" "}
                      <span className="mono">{fmtNum(m.threshold, 3)}</span>
                    </span>
                    <span className="muted">confidence {fmtPct(m.confidence, 0)}</span>
                  </div>
                  <div className="drift-bar">
                    <div className="drift-bar-threshold" style={{ left: `${(1 / 1.4) * 100}%` }} />
                    <div
                      className="drift-bar-fill"
                      style={{ width: `${(ratio / 1.4) * 100}%`, background: severityColor(m.severity) }}
                    />
                  </div>
                </div>

                <div className="alert-foot">
                  <div className="alert-windows">
                    <span><span className="muted">Baseline</span> {m.baseline_window}</span>
                    <span><span className="muted">Current</span> {m.current_window} · detected {relTime(m.detected_at)}</span>
                  </div>
                  <p className="alert-reco">
                    <span className="muted">Recommended</span> {m.recommended_action}
                    {m.linked_action && (
                      <button type="button" className="linked-badge" onClick={() => navigate("healing", { focus: m.linked_action })}>
                        <Badge variant="purple" appearance="dot">healing linked</Badge>
                      </button>
                    )}
                  </p>
                </div>
              </div>
            </article>
          );
        })}
      </div>
    </>
  );
}
