import { Badge, Button, Table, Text } from "@cloudflare/kumo";
import { ArrowsClockwiseIcon } from "@phosphor-icons/react";

import { getOverview } from "../api";
import { Bars, ErrorState, InfoGrid, InfoRow, LoadingState, PageHeader, Panel, RefreshMeta, StatTile } from "../components";
import { useApi } from "../hooks";
import { decisionVariant, fmtInt, fmtMs, fmtPct, relTime } from "../lib";
import { navigate } from "../router";

export function Overview() {
  const { data, error, loading, updatedAt, refresh } = useApi(getOverview, 5000);

  if (loading && !data) return <LoadingState />;
  if (error && !data) return <ErrorState message={error} />;
  if (!data) return null;

  const { health, summary, distribution, latency, recent } = data;
  const sloBreach = latency.p99 > 25;
  const components: Array<[string, string | undefined]> = [
    ["Workload", health.workload?.status],
    ["Model", health.model?.status],
    ["Policy", health.policy?.status],
    ["Audit", health.audit?.status],
    ["Storage", health.storage?.status],
  ];

  return (
    <>
      <PageHeader
        eyebrow="Decision Runtime"
        title="Production decision control"
        description="Runtime health, decision throughput, policy compliance, and the adaptive changes currently in flight."
        actions={
          <>
            <Button variant="secondary" icon={<ArrowsClockwiseIcon size={16} />} onClick={refresh}>
              Refresh
            </Button>
            <RefreshMeta updatedAt={updatedAt} intervalMs={5000} />
          </>
        }
      />

      <div className="kpi-row">
        <StatTile
          label="Runtime health"
          value={health.status === "healthy" ? "Healthy" : "Degraded"}
          sub={`${fmtInt(health.runtime?.cached_decisions)} decisions persisted`}
          accent={
            <Badge variant={health.status === "healthy" ? "success" : "warning"} appearance="dot">
              {health.status}
            </Badge>
          }
          tone={health.status === "healthy" ? "default" : "warning"}
        />
        <StatTile
          label="Decision throughput"
          value={fmtInt(distribution.total)}
          sub={`${fmtPct(distribution.block_rate)} blocked · ${fmtPct(distribution.review_rate)} review`}
        />
        <StatTile
          label="Decision latency"
          value={fmtMs(latency.p99)}
          sub={`SLO 25 ms · ${latency.samples} samples`}
          accent={
            <Badge variant={sloBreach ? "error" : "success"} appearance="dot">
              {sloBreach ? "breach" : "within SLO"}
            </Badge>
          }
          tone={sloBreach ? "danger" : "default"}
        />
        <StatTile
          label="Model health alerts"
          value={fmtInt(summary.open_drift_alerts)}
          sub={`${fmtInt(summary.pending_labels)} labels pending`}
          tone={summary.open_drift_alerts > 0 ? "warning" : "default"}
        />
        <StatTile
          label="Healing status"
          value={fmtInt(summary.healing_pending)}
          sub="Human-gated adaptations"
          tone={summary.healing_pending > 0 ? "warning" : "default"}
        />
      </div>

      <div className="grid-2">
        <Panel eyebrow="Decision mix" title="Decision distribution">
          {distribution.total === 0 ? (
            <p className="empty-hint">
              No decisions in the live window yet. Run requests from Live Decisions.
            </p>
          ) : (
            <Bars
              items={[
                { label: "Allow", value: distribution.allow, max: distribution.total, color: "var(--color-kumo-success)" },
                { label: "Review", value: distribution.review, max: distribution.total, color: "var(--sev-warn)" },
                { label: "Block", value: distribution.block, max: distribution.total, color: "var(--color-kumo-danger)" },
              ]}
            />
          )}
        </Panel>

        <Panel eyebrow="Dependencies" title="System health">
          <InfoGrid>
            {components.map(([label, status]) => (
              <InfoRow key={label} label={label}>
                <Badge variant={status === "healthy" || status === "active" ? "success" : "warning"} appearance="dot">
                  {status ?? "unknown"}
                </Badge>
              </InfoRow>
            ))}
            <InfoRow label="Active model">
              <span className="mono">
                {health.model?.model_id} · {health.model?.model_version}
              </span>
            </InfoRow>
            <InfoRow label="Policy">
              <span className="mono">{health.policy?.version}</span>
            </InfoRow>
          </InfoGrid>
        </Panel>
      </div>

      <Panel eyebrow="Audit stream" title="Recent decisions" padding={false}>
        {recent.length === 0 ? (
          <div className="panel-body">
            <p className="empty-hint">No decisions recorded yet.</p>
          </div>
        ) : (
          <div className="table-scroll">
            <Table>
              <Table.Header>
                <Table.Row>
                  <Table.Head>Request</Table.Head>
                  <Table.Head>Decision</Table.Head>
                  <Table.Head>Score</Table.Head>
                  <Table.Head>Model</Table.Head>
                  <Table.Head>Latency</Table.Head>
                  <Table.Head>When</Table.Head>
                </Table.Row>
              </Table.Header>
              <Table.Body>
                {recent.map((row, i) => (
                  <Table.Row
                    key={`${row.decision_request_id ?? row.transaction_id}-${i}`}
                    className="clickable-row"
                    onClick={() => navigate("scoring", { decision: row.decision_request_id ?? row.transaction_id })}
                  >
                    <Table.Cell>
                      <span className="mono">{row.decision_request_id ?? row.transaction_id}</span>
                    </Table.Cell>
                    <Table.Cell>
                      <Badge variant={decisionVariant(String(row.decision))}>{row.decision}</Badge>
                    </Table.Cell>
                    <Table.Cell>
                      <span className="mono">{row.score.toFixed(3)}</span>
                    </Table.Cell>
                    <Table.Cell>
                      <Text variant="secondary" size="sm">
                        {row.model_version ?? "—"}
                      </Text>
                    </Table.Cell>
                    <Table.Cell>
                      <span className="mono">{fmtMs(row.latency_ms)}</span>
                    </Table.Cell>
                    <Table.Cell>
                      <Text variant="secondary" size="sm">
                        {relTime(row.created_at)}
                      </Text>
                    </Table.Cell>
                  </Table.Row>
                ))}
              </Table.Body>
            </Table>
          </div>
        )}
      </Panel>
    </>
  );
}
