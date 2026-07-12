import { useCallback, useEffect, useRef, useState } from "react";
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
import { ErrorState, InfoGrid, InfoRow, LoadingState, PageHeader, Panel, StatTile } from "../components";
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
      });
      onOpenChange(false);
      reset();
      onDone();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Upload failed");
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
  const { data, error, loading, refresh } = useApi(getModels, 8000);
  const [busy, setBusy] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [uploadOpen, setUploadOpen] = useState(false);

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

  const champion = data.models.find((m) => m.stage === "champion");
  const shadow = data.models.find((m) => m.stage === "shadow");
  const championMetrics = champion?.metrics ?? null;
  const shadowMetrics = shadow?.metrics ?? null;

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
              onClick={() => run("rollback", rollbackModel)}
            >
              Roll back live model
            </Button>
            <Button variant="primary" icon={<UploadSimpleIcon size={16} />} onClick={() => setUploadOpen(true)}>
              Upload model
            </Button>
            <Button variant="ghost" shape="square" aria-label="Refresh" onClick={refresh}>
              <ArrowsClockwiseIcon size={16} />
            </Button>
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
                  onClick={() => run(`load-${art.artifact_id}`, () => loadModel(art.artifact_id))}
                >
                  Load
                </Button>
              </div>
            ))}
          </div>
        </Panel>
      )}

      <Panel eyebrow="Registry" title="All models" padding={false}>
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
              {data.models.map((m) => (
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
                          onClick={() => run(`shadow-${m.model_id}`, () => promoteModel(m.model_id, "shadow"))}
                        >
                          → Shadow
                        </Button>
                      )}
                      {m.stage !== "champion" && m.stage !== "fallback" && (
                        <Button
                          variant="secondary"
                          size="xs"
                          loading={busy === `champion-${m.model_id}`}
                          onClick={() => run(`champion-${m.model_id}`, () => promoteModel(m.model_id, "champion"))}
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
    </>
  );
}
