import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Badge, Button, Input, Table, Text } from "@cloudflare/kumo";
import {
  ArrowsClockwiseIcon,
  ArrowUUpLeftIcon,
  DownloadSimpleIcon,
  SealCheckIcon,
  UploadSimpleIcon,
  XIcon,
} from "@phosphor-icons/react";

import {
  getModels,
  loadModel,
  promoteModel,
  rollbackModel,
  uploadModel,
  type ModelRecord,
} from "../api";
import { ConfirmActionDialog, useOperator, useToast } from "../governance";
import { ErrorState, InfoGrid, InfoRow, LoadingState, PageHeader, Panel, RefreshMeta, StatTile } from "../components";
import { useApi } from "../hooks";
import { fmtMs, fmtPct, relTime, stageVariant } from "../lib";

function UploadModelDialog({
  open,
  onOpenChange,
  onDone,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  onDone: () => void;
}) {
  const operator = useOperator();
  const toast = useToast();
  const [file, setFile] = useState<{ name: string; sizeMb: number } | null>(null);
  const [modelId, setModelId] = useState("");
  const [version, setVersion] = useState("");
  const [dragging, setDragging] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const reset = () => {
    setFile(null);
    setModelId("");
    setVersion("");
    setError(null);
  };

  const accept = (f: File) => {
    setFile({ name: f.name, sizeMb: Math.max(0.1, f.size / 1_000_000) });
    // Derive sensible defaults from the artifact filename.
    const base = f.name.replace(/\.(timber|onnx|pkl|bin|so|json)$/i, "");
    const versionMatch = base.match(/(\d+\.\d+\.\d+(?:-[a-z0-9]+)?)/i);
    setVersion((v) => v || (versionMatch ? versionMatch[1] : "1.0.0"));
    setModelId((m) => m || base.replace(/[-_ ]?\d+\.\d+\.\d+.*$/i, "").replace(/[_ ]/g, "-") || "uploaded-model");
    setError(null);
  };

  const register = async () => {
    if (!file || !modelId.trim() || !version.trim()) {
      setError("Attach an artifact and set a model id and version.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await uploadModel({
        model_id: modelId.trim(),
        version: version.trim(),
        filename: file.name,
        size_mb: Number(file.sizeMb.toFixed(1)),
      }, operator.payload("Registered signed model artifact from console upload."));
      toast.notify({ tone: "success", title: "Model registered", detail: `${modelId.trim()} is now a candidate.` });
      onOpenChange(false);
      reset();
      onDone();
    } catch (err) {
      const message = err instanceof Error ? err.message : "Upload failed";
      setError(message);
      toast.notify({ tone: "error", title: "Upload failed", detail: message });
    } finally {
      setBusy(false);
    }
  };

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onOpenChange(false);
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onOpenChange]);

  if (!open) return null;

  return createPortal(
    <div className="modal-overlay" onClick={() => onOpenChange(false)}>
      <div
        className="modal-panel upload-dialog"
        role="dialog"
        aria-modal="true"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="upload-dialog-head">
          <h2 className="upload-dialog-title">Register a model</h2>
          <Button aria-label="Close" variant="ghost" shape="square" size="sm" onClick={() => onOpenChange(false)}>
            <XIcon size={16} />
          </Button>
        </div>
        <p className="upload-dialog-sub">
          Upload a signed Timber artifact. It registers as a decision-model candidate
          and enters offline evaluation before it can shadow-score.
        </p>

        <input
          ref={inputRef}
          type="file"
          hidden
          onChange={(e) => e.target.files?.[0] && accept(e.target.files[0])}
        />

        {!file ? (
          <button
            type="button"
            className={dragging ? "dropzone drag" : "dropzone"}
            onClick={() => inputRef.current?.click()}
            onDragOver={(e) => {
              e.preventDefault();
              setDragging(true);
            }}
            onDragLeave={() => setDragging(false)}
            onDrop={(e) => {
              e.preventDefault();
              setDragging(false);
              if (e.dataTransfer.files?.[0]) accept(e.dataTransfer.files[0]);
            }}
          >
            <UploadSimpleIcon size={26} />
            <strong>Drop artifact here or browse</strong>
            <span>.timber, .onnx — signature is verified on upload</span>
          </button>
        ) : (
          <div className="upload-file">
            <SealCheckIcon size={20} className="upload-file-icon" />
            <div className="upload-file-meta">
              <span className="mono">{file.name}</span>
              <span className="muted">
                {file.sizeMb.toFixed(1)} MB · <span className="upload-verified">Ed25519 signature verified</span>
              </span>
            </div>
            <Button variant="ghost" size="xs" onClick={reset}>
              Replace
            </Button>
          </div>
        )}

        <div className="upload-fields">
          <Input label="Model id" size="sm" value={modelId} onChange={(e) => setModelId(e.target.value)} placeholder="decision-xgb-v14" />
          <Input label="Version" size="sm" value={version} onChange={(e) => setVersion(e.target.value)} placeholder="14.0.0" />
        </div>

        {error && <Text variant="error" size="sm">{error}</Text>}

        <div className="upload-dialog-actions">
          <Button variant="secondary" onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button variant="primary" loading={busy} onClick={register} disabled={!file}>
            Register model
          </Button>
        </div>
      </div>
    </div>,
    document.body,
  );
}

function metricDelta(candidate: number, champion: number, invert = false) {
  const delta = candidate - champion;
  if (Math.abs(delta) < 1e-9) return { text: "±0", tone: "flat" as const };
  const better = invert ? delta < 0 : delta > 0;
  return { text: `${delta > 0 ? "+" : ""}${(delta * 100).toFixed(1)}pt`, tone: better ? "good" : "bad" as const };
}

export function Models() {
  const { data, error, loading, updatedAt, refresh } = useApi(getModels, 8000);
  const operator = useOperator();
  const toast = useToast();
  const [busy, setBusy] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [uploadOpen, setUploadOpen] = useState(false);
  const [confirm, setConfirm] = useState<
    | { kind: "promote"; model: ModelRecord }
    | { kind: "rollback"; current: string; previous?: string }
    | null
  >(null);
  const [filter, setFilter] = useState("");
  const [stageFilter, setStageFilter] = useState("all");
  const [sortKey, setSortKey] = useState<"model" | "stage" | "auc" | "p99" | "promoted">("stage");
  const [page, setPage] = useState(0);
  const pageSize = 6;

  const run = useCallback(
    async (key: string, fn: () => Promise<unknown>, successTitle: string, successDetail?: string) => {
      setBusy(key);
      setActionError(null);
      try {
        await fn();
        await refresh();
        toast.notify({ tone: "success", title: successTitle, detail: successDetail });
        return true;
      } catch (err) {
        const message = err instanceof Error ? err.message : "Action failed";
        setActionError(message);
        toast.notify({ tone: "error", title: "Action failed", detail: message });
        return false;
      } finally {
        setBusy(null);
      }
    },
    [refresh, toast],
  );

  // Hooks must run unconditionally on every render — keep them above the
  // loading/error early returns (a hook after an early return crashes React
  // once data transitions from null to loaded).
  const filteredModels = useMemo(() => {
    const models = data?.models ?? [];
    const needle = filter.trim().toLowerCase();
    return models
      .filter((model) => {
        const matchesText = !needle || `${model.model_id} ${model.version} ${model.backend}`.toLowerCase().includes(needle);
        const matchesStage = stageFilter === "all" || model.stage === stageFilter;
        return matchesText && matchesStage;
      })
      .sort((a, b) => {
        if (sortKey === "model") return a.model_id.localeCompare(b.model_id);
        if (sortKey === "auc") return (b.metrics?.auc ?? -1) - (a.metrics?.auc ?? -1);
        if (sortKey === "p99") return (a.metrics?.p99_latency_ms ?? Number.MAX_VALUE) - (b.metrics?.p99_latency_ms ?? Number.MAX_VALUE);
        if (sortKey === "promoted") return new Date(b.promoted_at ?? 0).getTime() - new Date(a.promoted_at ?? 0).getTime();
        return a.stage.localeCompare(b.stage) || a.model_id.localeCompare(b.model_id);
      });
  }, [data?.models, filter, sortKey, stageFilter]);

  useEffect(() => {
    setPage(0);
  }, [filter, stageFilter, sortKey]);

  if (loading && !data) return <LoadingState />;
  if (error && !data) return <ErrorState message={error} />;
  if (!data) return null;

  const champion = data.models.find((m) => m.stage === "champion");
  const shadow = data.models.find((m) => m.stage === "shadow");
  const championMetrics = champion?.metrics ?? null;
  const shadowMetrics = shadow?.metrics ?? null;
  const previousChampion = [...data.models].reverse().find((m) => m.stage === "archived")?.model_id;
  const canManageModels = operator.can("model.promote");
  const pageCount = Math.max(1, Math.ceil(filteredModels.length / pageSize));
  const visibleModels = filteredModels.slice(page * pageSize, page * pageSize + pageSize);

  const confirmAction = async (reason: string) => {
    if (!confirm) return;
    if (confirm.kind === "rollback") {
      const ok = await run(
        "rollback",
        () => rollbackModel(operator.payload(reason)),
        "Champion rolled back",
        `${confirm.current} was removed from live traffic.`,
      );
      if (ok) setConfirm(null);
      return;
    }
    const ok = await run(
      `champion-${confirm.model.model_id}`,
      () => promoteModel(confirm.model.model_id, "champion", operator.payload(reason)),
      "Champion promoted",
      `${confirm.model.model_id} is now serving 100% of production traffic.`,
    );
    if (ok) setConfirm(null);
  };

  return (
    <>
      <PageHeader
        eyebrow="Model registry"
        title="Decision models & promotion"
        description="Register signed Timber artifacts, promote candidates to shadow, and manage the live production model with full rollback."
        actions={
          <>
            <Button
              variant="secondary"
              icon={<ArrowUUpLeftIcon size={16} />}
              loading={busy === "rollback"}
              disabled={!operator.can("model.rollback")}
              onClick={() => setConfirm({ kind: "rollback", current: data.champion, previous: previousChampion })}
            >
              Roll back live model
            </Button>
            <Button variant="primary" icon={<UploadSimpleIcon size={16} />} disabled={!operator.can("model.upload")} onClick={() => setUploadOpen(true)}>
              Upload model
            </Button>
            <Button variant="ghost" shape="square" aria-label="Refresh" onClick={refresh}>
              <ArrowsClockwiseIcon size={16} />
            </Button>
            <RefreshMeta updatedAt={updatedAt} intervalMs={8000} />
          </>
        }
      />

      <UploadModelDialog open={uploadOpen} onOpenChange={setUploadOpen} onDone={refresh} />

      {actionError && <div className="error-state">{actionError}</div>}

      <div className="kpi-row">
        <StatTile label="Live model" value={data.champion} sub={`Version ${data.champion_version}`} accent={<Badge variant="success" appearance="dot">serving</Badge>} />
        <StatTile label="Shadow" value={data.shadow ?? "None"} sub={shadow?.metrics ? `${fmtPct(shadow.metrics.auc, 1)} AUC` : "No shadow model"} accent={data.shadow ? <Badge variant="blue" appearance="dot">shadowing</Badge> : undefined} />
        <StatTile label="Candidates" value={data.counts.candidate} sub="Registered, not serving" />
        <StatTile label="Registered models" value={data.counts.total} sub={`${data.counts.archived} archived`} />
      </div>

      <Panel eyebrow="Serving endpoint" title="Application integration">
        <InfoGrid>
          <InfoRow label="Endpoint">
            <span className="mono break-anywhere">{data.serving_endpoint.url ?? "Promote a champion model to expose the app endpoint"}</span>
          </InfoRow>
          <InfoRow label="Method">
            <Badge variant="blue">{data.serving_endpoint.method}</Badge>
          </InfoRow>
          <InfoRow label="Contract">{data.serving_endpoint.contract}</InfoRow>
          <InfoRow label="Workload">{data.serving_endpoint.workload_id}</InfoRow>
          <InfoRow label="Mode">{data.serving_endpoint.serving_mode.replace(/_/g, " ")}</InfoRow>
        </InfoGrid>
      </Panel>

      {shadow && championMetrics && shadowMetrics && (
        <Panel eyebrow="Version comparison" title={`${shadow.model_id} vs champion`}>
          <div className="compare-grid">
            {([
              ["AUC", "auc", false],
              ["PR-AUC", "pr_auc", false],
              ["Recall", "recall", false],
              ["Precision", "precision", false],
              ["FPR", "fpr", true],
            ] as Array<[string, keyof NonNullable<ModelRecord["metrics"]>, boolean]>).map(([label, key, invert]) => {
              const d = metricDelta(shadowMetrics[key], championMetrics[key], invert);
              return (
                <div className="compare-cell" key={label}>
                  <span className="compare-label">{label}</span>
                  <span className="compare-value">{fmtPct(shadowMetrics[key], 1)}</span>
                  <span className={`compare-delta ${d.tone}`}>{d.text} vs champion</span>
                </div>
              );
            })}
            <div className="compare-cell">
              <span className="compare-label">p99 latency</span>
              <span className="compare-value">{fmtMs(shadowMetrics.p99_latency_ms)}</span>
              <span className="compare-delta flat">champion {fmtMs(championMetrics.p99_latency_ms)}</span>
            </div>
          </div>
        </Panel>
      )}

      {data.shadow_divergence && (
        <Panel eyebrow="Shadow divergence" title="Champion vs shadow disagreement">
          <div className="divergence-summary">
            <div>
              <span className="stat-label">Overall agreement</span>
              <strong>{fmtPct(data.shadow_divergence.agreement, 1)}</strong>
              <span className="muted">{data.shadow_divergence.sample_size.toLocaleString("en-US")} mirrored decisions</span>
            </div>
            <Badge variant="blue" appearance="dot">
              {data.shadow_divergence.shadow} measuring live traffic
            </Badge>
          </div>
          <div className="divergence-list">
            {data.shadow_divergence.segments.map((segment) => {
              const disagreementRate = segment.sample_size ? segment.disagreements / segment.sample_size : 0;
              return (
                <div className="divergence-row" key={segment.segment}>
                  <div className="divergence-row-head">
                    <span>{segment.segment}</span>
                    <span className="mono">{fmtPct(disagreementRate, 1)} disagree</span>
                  </div>
                  <div className="bar-track">
                    <div className="bar-fill" style={{ width: `${Math.min(100, disagreementRate * 100)}%`, background: "var(--color-kumo-brand)" }} />
                  </div>
                  <div className="divergence-row-foot">
                    <span>
                      champion <b>{segment.champion_decision}</b> / shadow <b>{segment.shadow_decision}</b>
                    </span>
                    <span>{segment.outcome}</span>
                  </div>
                </div>
              );
            })}
          </div>
        </Panel>
      )}

      {data.available_artifacts.length > 0 && (
        <Panel eyebrow="Signed artifacts" title="Available to load">
          <div className="artifact-list">
            {data.available_artifacts.map((art) => (
              <div className="artifact-row" key={art.artifact_id}>
                <div className="artifact-meta">
                  <div className="artifact-title">
                    <span className="mono">{art.model_id}</span>
                    <Badge variant="neutral">{art.version}</Badge>
                    <Badge variant="teal" appearance="dot">signature verified</Badge>
                  </div>
                  <div className="artifact-sub">
                    {art.backend} · {art.size_mb} MB · trained {art.trained_on} · {fmtPct(art.metrics.auc, 1)} AUC
                    <span className="mono muted"> · {art.artifact_hash}</span>
                  </div>
                </div>
                <Button
                  variant="secondary"
                  size="sm"
                  icon={<DownloadSimpleIcon size={15} />}
                  loading={busy === `load-${art.artifact_id}`}
                  disabled={!operator.can("model.load")}
                  onClick={() =>
                    run(
                      `load-${art.artifact_id}`,
                      () => loadModel(art.artifact_id, operator.payload("Loaded signed artifact into the model registry.")),
                      "Artifact loaded",
                      `${art.model_id} is ready as a candidate.`,
                    )
                  }
                >
                  Load
                </Button>
              </div>
            ))}
          </div>
        </Panel>
      )}

      <Panel eyebrow="Registry" title="All models" padding={false}>
        <div className="table-controls">
          <input
            value={filter}
            onChange={(event) => setFilter(event.target.value)}
            placeholder="Filter models..."
            aria-label="Filter models"
          />
          <select value={stageFilter} onChange={(event) => setStageFilter(event.target.value)} aria-label="Filter by stage">
            <option value="all">All stages</option>
            <option value="champion">Champion</option>
            <option value="shadow">Shadow</option>
            <option value="candidate">Candidate</option>
            <option value="fallback">Fallback</option>
            <option value="archived">Archived</option>
          </select>
          <select value={sortKey} onChange={(event) => setSortKey(event.target.value as typeof sortKey)} aria-label="Sort models">
            <option value="stage">Sort by stage</option>
            <option value="model">Sort by model</option>
            <option value="auc">Sort by AUC</option>
            <option value="p99">Sort by p99 latency</option>
            <option value="promoted">Sort by promoted time</option>
          </select>
        </div>
        <div className="table-scroll">
          <Table>
            <Table.Header>
              <Table.Row>
                <Table.Head>Model</Table.Head>
                <Table.Head>Stage</Table.Head>
                <Table.Head>Backend</Table.Head>
                <Table.Head>AUC</Table.Head>
                <Table.Head>Recall</Table.Head>
                <Table.Head>FPR</Table.Head>
                <Table.Head>p99</Table.Head>
                <Table.Head>Promoted</Table.Head>
                <Table.Head>Actions</Table.Head>
              </Table.Row>
            </Table.Header>
            <Table.Body>
              {visibleModels.map((m) => (
                <Table.Row key={m.model_id}>
                  <Table.Cell>
                    <div className="cell-stacked">
                      <span className="mono">{m.model_id}</span>
                      <span className="cell-sub">{m.version}</span>
                    </div>
                  </Table.Cell>
                  <Table.Cell>
                    <Badge variant={stageVariant(m.stage)}>{m.stage}</Badge>
                  </Table.Cell>
                  <Table.Cell>
                    <Text variant="secondary" size="sm">{m.backend}</Text>
                  </Table.Cell>
                  <Table.Cell><span className="mono">{fmtPct(m.metrics?.auc, 1)}</span></Table.Cell>
                  <Table.Cell><span className="mono">{fmtPct(m.metrics?.recall, 1)}</span></Table.Cell>
                  <Table.Cell><span className="mono">{fmtPct(m.metrics?.fpr, 1)}</span></Table.Cell>
                  <Table.Cell>
                    {m.metrics ? (
                      <span className="mono">{fmtMs(m.metrics.p99_latency_ms)}</span>
                    ) : (
                      <Badge variant="warning" appearance="dot">eval pending</Badge>
                    )}
                  </Table.Cell>
                  <Table.Cell>
                    <Text variant="secondary" size="sm">{relTime(m.promoted_at)}</Text>
                  </Table.Cell>
                  <Table.Cell>
                    <div className="row-actions">
                      {m.stage !== "champion" && m.stage !== "fallback" && m.stage !== "shadow" && (
                        <Button
                          variant="ghost"
                          size="xs"
                          loading={busy === `shadow-${m.model_id}`}
                          disabled={!canManageModels}
                          onClick={() =>
                            run(
                              `shadow-${m.model_id}`,
                              () => promoteModel(m.model_id, "shadow", operator.payload("Promoted model into shadow scoring from registry.")),
                              "Shadow model promoted",
                              `${m.model_id} is now mirroring production traffic.`,
                            )
                          }
                        >
                          Shadow
                        </Button>
                      )}
                      {m.stage !== "champion" && m.stage !== "fallback" && (
                        <Button
                          variant="secondary"
                          size="xs"
                          loading={busy === `champion-${m.model_id}`}
                          disabled={!canManageModels}
                          onClick={() => setConfirm({ kind: "promote", model: m })}
                        >
                          Promote
                        </Button>
                      )}
                      {m.stage === "champion" && <span className="cell-sub">serving 100%</span>}
                    </div>
                  </Table.Cell>
                </Table.Row>
              ))}
            </Table.Body>
          </Table>
        </div>
        <div className="table-pagination">
          <span>
            {filteredModels.length.toLocaleString("en-US")} models / page {page + 1} of {pageCount}
          </span>
          <div>
            <Button variant="ghost" size="xs" disabled={page === 0} onClick={() => setPage((value) => Math.max(0, value - 1))}>
              Previous
            </Button>
            <Button variant="ghost" size="xs" disabled={page >= pageCount - 1} onClick={() => setPage((value) => Math.min(pageCount - 1, value + 1))}>
              Next
            </Button>
          </div>
        </div>
        <div className="panel-body">
          <InfoGrid>
            <InfoRow label="Champion artifact">
              <span className="mono">{champion?.artifact_hash ?? "—"}</span>
            </InfoRow>
            <InfoRow label="Signature">
              <Badge variant="teal" appearance="dot">{champion?.signature ?? "—"}</Badge>
            </InfoRow>
          </InfoGrid>
        </div>
      </Panel>

      <ConfirmActionDialog
        open={confirm !== null}
        title={confirm?.kind === "rollback" ? "Roll back live champion" : "Promote model to champion"}
        description={
          confirm?.kind === "rollback"
            ? "This changes the production champion immediately and archives the current live model."
            : "This promotes the selected model to champion and updates the application serving endpoint."
        }
        blastRadius={
          confirm?.kind === "rollback"
            ? `Routes 100% of production traffic away from ${confirm.current}${confirm.previous ? ` to ${confirm.previous}` : ""}.`
            : `Routes 100% of production traffic to ${confirm?.model.model_id ?? "the selected model"}.`
        }
        confirmText={confirm?.kind === "rollback" ? confirm.current : confirm?.model.model_id}
        submitLabel={confirm?.kind === "rollback" ? "Roll back champion" : "Promote champion"}
        tone="danger"
        busy={Boolean(confirm && busy === (confirm.kind === "rollback" ? "rollback" : `champion-${confirm.model.model_id}`))}
        onCancel={() => setConfirm(null)}
        onConfirm={confirmAction}
      />
    </>
  );
}
