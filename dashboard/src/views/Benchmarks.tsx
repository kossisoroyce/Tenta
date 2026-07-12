import { Badge, Button, Table } from "@cloudflare/kumo";
import { ArrowsClockwiseIcon } from "@phosphor-icons/react";

import { getBenchmarks } from "../api";
import { ErrorState, LoadingState, PageHeader, Panel, Sparkline, StatTile } from "../components";
import { useApi } from "../hooks";
import { fmtInt, fmtMs, fmtPct, stageVariant } from "../lib";

export function Benchmarks() {
  const { data, error, loading, refresh } = useApi(getBenchmarks, 10000);

  if (loading && !data) return <LoadingState />;
  if (error && !data) return <ErrorState message={error} />;
  if (!data) return null;

  const sloBreach = data.latency_ms.p99 > data.slo_p99_ms;

  return (
    <>
      <PageHeader
        eyebrow="Performance"
        title="Runtime metrics"
        description="Decision-path latency, throughput, fallback behavior, and side-by-side offline metrics for every registered model."
        actions={
          <Button variant="ghost" shape="square" aria-label="Refresh" onClick={refresh}>
            <ArrowsClockwiseIcon size={16} />
          </Button>
        }
      />

      <div className="kpi-row">
        <StatTile
          label="p99 latency"
          value={fmtMs(data.latency_ms.p99)}
          sub={`SLO ${data.slo_p99_ms} ms`}
          accent={<Badge variant={sloBreach ? "error" : "success"} appearance="dot">{sloBreach ? "breach" : "ok"}</Badge>}
          tone={sloBreach ? "danger" : "default"}
        />
        <StatTile label="Throughput" value={`${fmtInt(data.throughput_tps)} tps`} sub={`peak ${fmtInt(data.peak_tps_24h)} tps / 24h`} />
        <StatTile label="Fallback rate" value={fmtPct(data.fallback_rate_24h, 2)} sub="Traffic on rule fallback" />
        <StatTile label="Error rate" value={fmtPct(data.error_rate_24h, 2)} sub="24h decision errors" tone={data.error_rate_24h > 0.01 ? "warning" : "default"} />
      </div>

      <div className="grid-2 align-start">
        <Panel eyebrow="Decision path" title="Latency (last 12 windows)">
          <div className="chart-block">
            <Sparkline data={data.latency_trend} stroke="var(--color-kumo-brand)" fill="var(--spark-fill)" height={80} width={360} />
          </div>
          <div className="metric-inline">
            <div><span className="muted">p50</span> <b className="mono">{fmtMs(data.latency_ms.p50)}</b></div>
            <div><span className="muted">p95</span> <b className="mono">{fmtMs(data.latency_ms.p95)}</b></div>
            <div><span className="muted">p99</span> <b className="mono">{fmtMs(data.latency_ms.p99)}</b></div>
            <div><span className="muted">max</span> <b className="mono">{fmtMs(data.latency_ms.max)}</b></div>
          </div>
          {data.live_latency_ms && (
            <p className="empty-hint">
              Live window: p50 {fmtMs(data.live_latency_ms.p50)} · p99 {fmtMs(data.live_latency_ms.p99)} over {data.live_latency_ms.samples} decisions.
            </p>
          )}
        </Panel>

        <Panel eyebrow="Volume" title="Throughput (last 12 windows)">
          <div className="chart-block">
            <Sparkline data={data.throughput_trend} stroke="var(--color-kumo-info)" fill="var(--spark-fill-info)" height={80} width={360} />
          </div>
          <div className="metric-inline">
            <div><span className="muted">current</span> <b className="mono">{fmtInt(data.throughput_tps)} tps</b></div>
            <div><span className="muted">peak 24h</span> <b className="mono">{fmtInt(data.peak_tps_24h)} tps</b></div>
          </div>
        </Panel>
      </div>

      <Panel eyebrow="Model comparison" title="Offline metrics by model" padding={false}>
        <div className="table-scroll">
          <Table>
            <Table.Header>
              <Table.Row>
                <Table.Head>Model</Table.Head>
                <Table.Head>Stage</Table.Head>
                <Table.Head>AUC</Table.Head>
                <Table.Head>PR-AUC</Table.Head>
                <Table.Head>Recall</Table.Head>
                <Table.Head>Precision</Table.Head>
                <Table.Head>FPR</Table.Head>
                <Table.Head>p99</Table.Head>
              </Table.Row>
            </Table.Header>
            <Table.Body>
              {data.model_comparison.map((m) => (
                <Table.Row key={m.model_id}>
                  <Table.Cell>
                    <div className="cell-stacked">
                      <span className="mono">{m.model_id}</span>
                      <span className="cell-sub">{m.version} · {m.backend}</span>
                    </div>
                  </Table.Cell>
                  <Table.Cell><Badge variant={stageVariant(m.stage)}>{m.stage}</Badge></Table.Cell>
                  <Table.Cell><span className="mono">{fmtPct(m.auc, 1)}</span></Table.Cell>
                  <Table.Cell><span className="mono">{fmtPct(m.pr_auc, 1)}</span></Table.Cell>
                  <Table.Cell><span className="mono">{fmtPct(m.recall, 1)}</span></Table.Cell>
                  <Table.Cell><span className="mono">{fmtPct(m.precision, 1)}</span></Table.Cell>
                  <Table.Cell><span className="mono">{fmtPct(m.fpr, 1)}</span></Table.Cell>
                  <Table.Cell><span className="mono">{fmtMs(m.p99_latency_ms)}</span></Table.Cell>
                </Table.Row>
              ))}
            </Table.Body>
          </Table>
        </div>
      </Panel>
    </>
  );
}
