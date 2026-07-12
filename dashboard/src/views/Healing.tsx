import { useCallback, useState } from "react";
import { Badge, Button } from "@cloudflare/kumo";
import { ArrowsClockwiseIcon, CheckIcon, XIcon } from "@phosphor-icons/react";

import { decideHealing, getHealing, rollbackHealing, type HealingAction } from "../api";
import { ErrorState, LoadingState, PageHeader, StatTile } from "../components";
import { useApi } from "../hooks";
import { fmtInt, healingVariant, relTime, riskVariant, titleize } from "../lib";

function ActionCard({
  action,
  busy,
  onApprove,
  onReject,
  onRollback,
}: {
  action: HealingAction;
  busy: string | null;
  onApprove: () => void;
  onReject: () => void;
  onRollback: () => void;
}) {
  const a = action;
  const gateHuman = a.policy_gate === "human_approval_required";
  return (
    <article className="heal-card">
      <div className="heal-head">
        <div className="heal-titles">
          <div className="heal-title-row">
            <h3>{a.title}</h3>
            <Badge variant={riskVariant(a.risk)}>{a.risk} risk</Badge>
            <Badge variant={healingVariant(a.status)} appearance="dot">{titleize(a.status)}</Badge>
          </div>
          <p className="heal-meta">
            {titleize(a.type)} · proposed by <span className="mono">{a.proposed_by}</span> · {relTime(a.proposed_at)}
            {a.linked_drift && <Badge variant="purple" appearance="dot">drift linked</Badge>}
          </p>
        </div>
        <div className="heal-actions">
          {a.status === "proposed" && (
            <>
              <Button variant="destructive" size="sm" icon={<XIcon size={14} />} loading={busy === `reject-${a.id}`} onClick={onReject}>
                Reject
              </Button>
              <Button variant="primary" size="sm" icon={<CheckIcon size={14} />} loading={busy === `approve-${a.id}`} onClick={onApprove}>
                Approve
              </Button>
            </>
          )}
          {(a.status === "running" || a.status === "completed") && (
            <Button variant="secondary" size="sm" loading={busy === `rollback-${a.id}`} onClick={onRollback}>
              Roll back
            </Button>
          )}
        </div>
      </div>

      <div className="heal-body">
        <div className="heal-field">
          <span className="heal-label">Why — trigger</span>
          <p>{a.trigger}</p>
        </div>
        <div className="heal-field">
          <span className="heal-label">Rationale</span>
          <p>{a.rationale}</p>
        </div>
        <div className="heal-field">
          <span className="heal-label">Who approved</span>
          <p>
            <Badge variant={gateHuman ? "warning" : "neutral"} appearance="dot">
              {gateHuman ? "Human approval required" : "Auto-approved"}
            </Badge>
            {a.approver && <span className="mono"> {a.approver}</span>}
            {a.decided_at && <span className="muted"> · {relTime(a.decided_at)}</span>}
          </p>
        </div>
        <div className="heal-field">
          <span className="heal-label">Estimated impact</span>
          <div className="chip-row">
            {Object.entries(a.estimated_impact).map(([k, v]) => (
              <span className="kv-chip" key={k}>
                <span className="kv-chip-k">{titleize(k)}</span>
                <span className="kv-chip-v">{v}</span>
              </span>
            ))}
          </div>
        </div>
        {a.outcome && (
          <div className="heal-field heal-outcome">
            <span className="heal-label">Outcome — how it's measured</span>
            <p>
              <Badge variant={a.outcome.status === "resolved" || a.outcome.status === "healthy" ? "success" : a.outcome.status === "rolled_back" || a.outcome.status === "rejected" ? "neutral" : "blue"} appearance="dot">
                {titleize(String(a.outcome.status))}
              </Badge>{" "}
              {a.outcome.note}
              {a.outcome.shadow_agreement ? <span className="mono muted"> · agreement {String(a.outcome.shadow_agreement)}</span> : null}
            </p>
          </div>
        )}
      </div>
    </article>
  );
}

export function Healing() {
  const { data, error, loading, refresh } = useApi(getHealing, 8000);
  const [busy, setBusy] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  const run = useCallback(
    async (key: string, fn: () => Promise<unknown>) => {
      setBusy(key);
      setActionError(null);
      try {
        await fn();
        await refresh();
      } catch (err) {
        setActionError(err instanceof Error ? err.message : "Action failed");
      } finally {
        setBusy(null);
      }
    },
    [refresh],
  );

  if (loading && !data) return <LoadingState />;
  if (error && !data) return <ErrorState message={error} />;
  if (!data) return null;

  const c = data.counts;

  return (
    <>
      <PageHeader
        eyebrow="Adaptation"
        title="Adaptive healing"
        description="Bounded runtime adaptations from drift, feedback, benchmarks, and policy gates. High-impact changes require human approval."
        actions={
          <Button variant="ghost" shape="square" aria-label="Refresh" onClick={refresh}>
            <ArrowsClockwiseIcon size={16} />
          </Button>
        }
      />

      {actionError && <div className="error-state">{actionError}</div>}

      <div className="kpi-row">
        <StatTile label="Awaiting approval" value={fmtInt(data.pending_approval)} tone={data.pending_approval ? "warning" : "default"} sub="Human-gated adaptations" />
        <StatTile label="Running" value={fmtInt(c.running || 0)} sub="Executing, monitored" />
        <StatTile label="Completed" value={fmtInt(c.completed || 0)} />
        <StatTile label="Rolled back" value={fmtInt(c.rolled_back || 0)} />
      </div>

      <div className="heal-stack">
        {data.actions.map((a) => (
          <ActionCard
            key={a.id}
            action={a}
            busy={busy}
            onApprove={() => run(`approve-${a.id}`, () => decideHealing(a.id, "approve"))}
            onReject={() => run(`reject-${a.id}`, () => decideHealing(a.id, "reject"))}
            onRollback={() => run(`rollback-${a.id}`, () => rollbackHealing(a.id))}
          />
        ))}
      </div>
    </>
  );
}
