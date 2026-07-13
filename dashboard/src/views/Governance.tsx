import { useCallback } from "react";
import { Badge, Button, Table, Text } from "@cloudflare/kumo";
import { ArrowsClockwiseIcon } from "@phosphor-icons/react";

import {
  getAuditIntegrity,
  getOperations,
  getPolicyHistory,
  type AuditChainReport,
} from "../api";
import { ErrorState, InfoGrid, InfoRow, LoadingState, PageHeader, Panel, RefreshMeta, StatTile } from "../components";
import { useApi } from "../hooks";
import { fmtInt, relTime, runtimeStatusVariant, titleize } from "../lib";
import { navigate } from "../router";

function summarize(record: Record<string, unknown>): string {
  const entries = Object.entries(record);
  if (!entries.length) return "—";
  return entries.map(([k, v]) => `${k}: ${v === null ? "none" : String(v)}`).join(", ");
}

function shortHash(hash: string | null | undefined): string {
  if (!hash) return "—";
  return `${hash.slice(0, 10)}…${hash.slice(-6)}`;
}

function issueText(value: AuditChainReport["warnings"][number] | undefined): string | null {
  if (!value) return null;
  if (typeof value === "string") return value;
  return value.message ? String(value.message) : JSON.stringify(value);
}

function chainNote(report: AuditChainReport): string {
  const issue = issueText(report.issues[0]);
  const warning = issueText(report.warnings[0]);
  if (issue) return issue;
  if (warning) return warning;
  if (report.status === "valid") return "Hash chain verified";
  return "No integrity issues reported";
}

function ChainPanel({ report }: { report: AuditChainReport }) {
  return (
    <Panel eyebrow="Integrity" title={`${titleize(report.chain)} chain`}>
      <InfoGrid>
        <InfoRow label="Status">
          <Badge variant={runtimeStatusVariant(report.status)} appearance="dot">
            {report.status}
          </Badge>
        </InfoRow>
        <InfoRow label="Verified">
          {fmtInt(report.events_verified)} of {fmtInt(report.total_events)}
        </InfoRow>
        <InfoRow label="Legacy">
          {fmtInt(report.legacy_events)}
        </InfoRow>
        <InfoRow label="Head hash">
          <span className="mono">{shortHash(report.head_hash)}</span>
        </InfoRow>
        <InfoRow label="Tail hash">
          <span className="mono">{shortHash(report.tail_hash)}</span>
        </InfoRow>
        <InfoRow label="Note">
          {chainNote(report)}
        </InfoRow>
      </InfoGrid>
    </Panel>
  );
}

export function Governance() {
  const policy = useApi(getPolicyHistory, 8000);
  const operations = useApi(() => getOperations(18), 8000);
  const integrity = useApi(getAuditIntegrity, 10000);

  const refreshAll = useCallback(async () => {
    await Promise.all([policy.refresh(), operations.refresh(), integrity.refresh()]);
  }, [integrity.refresh, operations.refresh, policy.refresh]);

  const loading =
    policy.loading &&
    operations.loading &&
    integrity.loading &&
    !policy.data &&
    !operations.data &&
    !integrity.data;
  const loadError = policy.error || operations.error || integrity.error;

  if (loading) return <LoadingState />;
  if (loadError && !policy.data && !operations.data && !integrity.data) {
    return <ErrorState message={loadError} />;
  }

  const entries = policy.data?.entries ?? [];
  const events = operations.data?.operations ?? [];
  const report = integrity.data;

  return (
    <>
      <PageHeader
        eyebrow="Governance"
        title="Audit, approvals & operation ledger"
        description="Policy changes, database provisioning, model promotions, healing actions, feedback writes, and integrity status in one place."
        actions={
          <>
            <Button variant="ghost" shape="square" aria-label="Refresh" onClick={refreshAll}>
              <ArrowsClockwiseIcon size={16} />
            </Button>
            <RefreshMeta updatedAt={policy.updatedAt ?? operations.updatedAt ?? integrity.updatedAt} intervalMs={8000} />
          </>
        }
      />

      {loadError && <div className="error-state">{loadError}</div>}

      <div className="kpi-row">
        <StatTile
          label="Audit integrity"
          value={report ? titleize(report.status) : "Unknown"}
          sub={report ? `${fmtInt(report.decisions.events_verified + report.operations.events_verified)} events verified` : "No report"}
          accent={
            <Badge variant={runtimeStatusVariant(report?.status)} appearance="dot">
              {report?.status ?? "unknown"}
            </Badge>
          }
          tone={report?.status === "invalid" ? "danger" : report?.status === "partial" ? "warning" : "default"}
        />
        <StatTile
          label="Operation events"
          value={fmtInt(report?.operations.total_events ?? events.length)}
          sub="Hash-chained mutations"
        />
        <StatTile
          label="Policy entries"
          value={fmtInt(entries.length)}
          sub="Approvals and config changes"
        />
        <StatTile
          label="Legacy events"
          value={fmtInt((report?.decisions.legacy_events ?? 0) + (report?.operations.legacy_events ?? 0))}
          sub="Pre-chain records"
          tone={(report?.decisions.legacy_events ?? 0) + (report?.operations.legacy_events ?? 0) > 0 ? "warning" : "default"}
        />
      </div>

      {report && (
        <div className="grid-2 align-start">
          <ChainPanel report={report.decisions} />
          <ChainPanel report={report.operations} />
        </div>
      )}

      <Panel eyebrow="Operation ledger" title="Recent control-plane events" padding={false}>
        {events.length === 0 ? (
          <div className="panel-body">
            <p className="empty-hint">No operation events recorded yet.</p>
          </div>
        ) : (
          <div className="table-scroll">
            <Table>
              <Table.Header>
                <Table.Row>
                  <Table.Head>Operation</Table.Head>
                  <Table.Head>Status</Table.Head>
                  <Table.Head>Actor</Table.Head>
                  <Table.Head>Target</Table.Head>
                  <Table.Head>Request</Table.Head>
                  <Table.Head>Hash</Table.Head>
                  <Table.Head>When</Table.Head>
                </Table.Row>
              </Table.Header>
              <Table.Body>
                {events.map((event) => (
                  <Table.Row key={event.id}>
                    <Table.Cell>
                      <span className="mono">{event.operation_type}</span>
                    </Table.Cell>
                    <Table.Cell>
                      <Badge variant={runtimeStatusVariant(event.status)} appearance="dot">
                        {event.status}
                      </Badge>
                    </Table.Cell>
                    <Table.Cell>
                      <span className="cell-stacked">
                        <span className="mono">{event.actor}</span>
                        <span className="cell-sub">{event.role ?? "role unknown"}</span>
                      </span>
                    </Table.Cell>
                    <Table.Cell>
                      <Text variant="secondary" size="sm">
                        {event.target ?? "—"}
                      </Text>
                    </Table.Cell>
                    <Table.Cell>
                      <span className="cell-stacked">
                        <span>{event.reason ?? event.message ?? "—"}</span>
                        <span className="cell-sub mono">{event.request_id ?? event.source ?? "—"}</span>
                      </span>
                    </Table.Cell>
                    <Table.Cell>
                      <span className="mono">{shortHash(event.event_hash)}</span>
                    </Table.Cell>
                    <Table.Cell>
                      <Text variant="secondary" size="sm">
                        {relTime(event.created_at)}
                      </Text>
                    </Table.Cell>
                  </Table.Row>
                ))}
              </Table.Body>
            </Table>
          </div>
        )}
      </Panel>

      <Panel eyebrow="Change log" title="Decision governance trail" padding={false}>
        {entries.length === 0 ? (
          <div className="panel-body">
            <p className="empty-hint">No policy changes recorded yet.</p>
          </div>
        ) : (
          <ol className="timeline">
            {entries.map((entry) => (
              <li className="timeline-item" key={entry.id}>
                <div className={`timeline-node type-${entry.approval_type}`} />
                <div className="timeline-body">
                  <div className="timeline-head">
                    <span className="timeline-change">{entry.change}</span>
                    <div className="timeline-badges">
                      <Badge variant={entry.approval_type === "human" ? "purple" : "neutral"} appearance="dot">
                        {entry.approval_type === "human" ? "Human approval" : "Auto"}
                      </Badge>
                      <Badge variant={runtimeStatusVariant(entry.status)}>{entry.status}</Badge>
                    </div>
                  </div>
                  <div className="timeline-diff">
                    <span className="diff-before">{summarize(entry.before)}</span>
                    <span className="diff-arrow">→</span>
                    <span className="diff-after">{summarize(entry.after)}</span>
                  </div>
                  <div className="timeline-meta">
                    <span className="kind-chip">{titleize(entry.kind)}</span>
                    <span className="mono">{entry.approved_by}</span>
                    <span className="muted">{relTime(entry.timestamp)}</span>
                    {entry.reason && <span className="reason-chip">{entry.reason}</span>}
                    {entry.linked_action && (
                      <button type="button" className="timeline-link" onClick={() => navigate("healing", { focus: entry.linked_action })}>
                        action {entry.linked_action}
                      </button>
                    )}
                  </div>
                </div>
              </li>
            ))}
          </ol>
        )}
      </Panel>
    </>
  );
}
