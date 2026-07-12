import { Badge, Button, Table, Text } from "@cloudflare/kumo";
import { ArrowsClockwiseIcon } from "@phosphor-icons/react";

import { getFeedback } from "../api";
import { Bars, ErrorState, LoadingState, PageHeader, Panel, StatTile } from "../components";
import { useApi } from "../hooks";
import { fmtInt, fmtPct } from "../lib";

export function Feedback() {
  const { data, error, loading, refresh } = useApi(getFeedback, 10000);

  if (loading && !data) return <LoadingState />;
  if (error && !data) return <ErrorState message={error} />;
  if (!data) return null;

  const maxBucket = Math.max(...data.label_delay_buckets.map((b) => b.count), 1);

  return (
    <>
      <PageHeader
        eyebrow="Human Feedback"
        title="Outcome feedback & label delay"
        description="Confirmed outcomes close the loop that drives model health, adaptive healing, and future promotion decisions."
        actions={
          <Button variant="ghost" shape="square" aria-label="Refresh" onClick={refresh}>
            <ArrowsClockwiseIcon size={16} />
          </Button>
        }
      />

      <div className="kpi-row">
        <StatTile label="Adverse outcomes (7d)" value={fmtInt(data.confirmed_fraud_7d)} sub={`${fmtInt(data.confirmed_legit_7d)} expected outcomes`} />
        <StatTile label="Analyst overturn rate" value={fmtPct(data.analyst_overturn_rate)} sub="Model decision reversed" tone={data.analyst_overturn_rate > 0.1 ? "warning" : "default"} />
        <StatTile label="Median label delay" value={`${data.median_label_delay_hours}h`} sub={`p90 ${data.p90_label_delay_hours}h`} />
        <StatTile label="Pending labels" value={fmtInt(data.pending_labels)} sub={`${fmtInt(data.feedback_queue_depth)} in review queue`} tone="warning" />
      </div>

      <div className="grid-2 align-start">
        <Panel eyebrow="Label latency" title="Label delay distribution">
          <Bars
            items={data.label_delay_buckets.map((b, i) => ({
              label: b.bucket,
              value: b.count,
              max: maxBucket,
              color: i >= 3 ? "var(--sev-warn)" : "var(--color-kumo-brand)",
            }))}
          />
          <p className="empty-hint">Labels arriving after 3 days slow adaptation and can mask concept drift.</p>
        </Panel>

        <Panel eyebrow="Recent labels" title="Human-confirmed outcomes" padding={false}>
          <div className="table-scroll">
            <Table>
              <Table.Header>
                <Table.Row>
                  <Table.Head>Request</Table.Head>
                  <Table.Head>Model</Table.Head>
                  <Table.Head>Label</Table.Head>
                  <Table.Head>Match</Table.Head>
                  <Table.Head>Segment</Table.Head>
                  <Table.Head>Delay</Table.Head>
                </Table.Row>
              </Table.Header>
              <Table.Body>
                {data.recent.map((r) => (
                  <Table.Row key={r.decision_request_id ?? r.transaction_id}>
                    <Table.Cell><span className="mono">{r.decision_request_id ?? r.transaction_id}</span></Table.Cell>
                    <Table.Cell><Text variant="secondary" size="sm">{r.model_decision}</Text></Table.Cell>
                    <Table.Cell>
                      <Badge variant={r.analyst_label === "fraud" ? "error" : "success"}>
                        {r.outcome_label ?? (r.analyst_label === "fraud" ? "adverse" : "expected")}
                      </Badge>
                    </Table.Cell>
                    <Table.Cell>
                      <Badge variant={r.agreement ? "success" : "orange"} appearance="dot">
                        {r.agreement ? "agree" : "overturn"}
                      </Badge>
                    </Table.Cell>
                    <Table.Cell><Text variant="secondary" size="sm">{r.segment}</Text></Table.Cell>
                    <Table.Cell><span className="mono">{r.delay_hours}h</span></Table.Cell>
                  </Table.Row>
                ))}
              </Table.Body>
            </Table>
          </div>
        </Panel>
      </div>
    </>
  );
}
