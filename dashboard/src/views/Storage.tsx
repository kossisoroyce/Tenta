import { useCallback, useState } from "react";
import { Badge, Button } from "@cloudflare/kumo";
import { ArrowsClockwiseIcon, DatabaseIcon } from "@phosphor-icons/react";

import {
  getDatabaseStatus,
  provisionPostgres,
  provisionSQLite,
  type DatabaseBackendOption,
  type ProvisionDatabaseResponse,
} from "../api";
import { ErrorState, InfoGrid, InfoRow, LoadingState, PageHeader, Panel, RefreshMeta, StatTile } from "../components";
import { useOperator, useToast } from "../governance";
import { useApi } from "../hooks";
import { fmtInt, relTime, runtimeStatusVariant, titleize } from "../lib";

function shortHash(hash: string | null | undefined): string {
  if (!hash) return "—";
  return `${hash.slice(0, 10)}…${hash.slice(-6)}`;
}

function backendStatus(option: DatabaseBackendOption, connectedBackend?: string | null) {
  const connected = option.backend === connectedBackend;
  if (connected) return { label: "connected", variant: "success" as const };
  if (!option.provisionable) return { label: "unavailable", variant: "warning" as const };
  return { label: "ready", variant: "neutral" as const };
}

function readinessBadges(option: DatabaseBackendOption) {
  if (option.backend !== "postgres") return null;
  return (
    <div className="backend-readiness">
      <Badge variant={option.compose_file_exists ? "success" : "warning"} appearance="dot">
        compose {option.compose_file_exists ? "ready" : "missing"}
      </Badge>
      <Badge variant={option.driver_available ? "success" : "warning"} appearance="dot">
        driver {option.driver_available ? "ready" : "missing"}
      </Badge>
    </div>
  );
}

function BackendCard({
  option,
  connectedBackend,
  busy,
  onProvision,
  canProvision,
}: {
  option: DatabaseBackendOption;
  connectedBackend?: string | null;
  busy: string | null;
  onProvision: (backend: string) => void;
  canProvision: boolean;
}) {
  const state = backendStatus(option, connectedBackend);
  const running = busy === option.backend;

  return (
    <article className={option.backend === connectedBackend ? "backend-card active" : "backend-card"}>
      <div className="backend-card-head">
        <div className="backend-title">
          <span className="backend-icon">
            <DatabaseIcon size={18} />
          </span>
          <div>
            <h3>{option.label}</h3>
            <span>{option.backend === "sqlite" ? "Embedded" : option.provisioner ?? "External"}</span>
          </div>
        </div>
        <Badge variant={state.variant} appearance="dot">
          {state.label}
        </Badge>
      </div>

      <InfoGrid>
        <InfoRow label="Default">
          <span className="mono">{option.default_storage_url}</span>
        </InfoRow>
        {option.service && (
          <InfoRow label="Service">
            <span className="mono">{option.service}</span>
          </InfoRow>
        )}
        <InfoRow label="Requires">
          {option.requires.length ? option.requires.join(", ") : "none"}
        </InfoRow>
      </InfoGrid>

      {readinessBadges(option)}

      <Button
        variant={option.backend === connectedBackend ? "secondary" : "primary"}
        loading={running}
        disabled={busy !== null || !option.provisionable || !canProvision}
        onClick={() => onProvision(option.backend)}
      >
        Provision {option.backend === "sqlite" ? "SQLite" : "Postgres"}
      </Button>
    </article>
  );
}

export function Storage() {
  const { data, error, loading, updatedAt, refresh } = useApi(getDatabaseStatus, 7000);
  const operator = useOperator();
  const toast = useToast();
  const [busy, setBusy] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [lastResult, setLastResult] = useState<ProvisionDatabaseResponse | null>(null);

  const provision = useCallback(
    async (backend: string) => {
      setBusy(backend);
      setActionError(null);
      try {
        const actor = operator.payload(`Provision ${backend} storage from console.`);
        const result = backend === "sqlite" ? await provisionSQLite(actor) : await provisionPostgres(actor);
        setLastResult(result);
        await refresh();
        toast.notify({ tone: "success", title: "Database connected", detail: `${titleize(backend)} is now the runtime store.` });
      } catch (err) {
        const message = err instanceof Error ? err.message : "Provisioning failed";
        setActionError(message);
        toast.notify({ tone: "error", title: "Provisioning failed", detail: message });
      } finally {
        setBusy(null);
      }
    },
    [operator, refresh, toast],
  );

  if (loading && !data) return <LoadingState />;
  if (error && !data) return <ErrorState message={error} />;
  if (!data) return null;

  const connected = data.connected;
  const control = data.control_plane;

  return (
    <>
      <PageHeader
        eyebrow="Storage"
        title="Runtime storage"
        description="Provision and connect the self-contained database layer for decisions, audit events, feedback, and runtime memory."
        actions={
          <>
            <Button variant="ghost" shape="square" aria-label="Refresh" onClick={refresh}>
              <ArrowsClockwiseIcon size={16} />
            </Button>
            <RefreshMeta updatedAt={updatedAt} intervalMs={7000} />
          </>
        }
      />

      {actionError && <div className="error-state">{actionError}</div>}

      <div className="kpi-row">
        <StatTile
          label="Connected store"
          value={connected.backend ? titleize(connected.backend) : "Unknown"}
          sub={connected.path ?? data.configured_storage_url}
          accent={
            <Badge variant={runtimeStatusVariant(connected.status)} appearance="dot">
              {connected.status ?? "unknown"}
            </Badge>
          }
        />
        <StatTile
          label="Decision events"
          value={fmtInt(connected.decision_events ?? connected.cached_decisions)}
          sub="Persisted runtime audit"
        />
        <StatTile
          label="Operation events"
          value={fmtInt(control.operation_events)}
          sub="Control-plane ledger"
        />
        <StatTile
          label="Control plane"
          value={control.backend ? titleize(control.backend) : "Unknown"}
          sub={control.namespace ?? control.path ?? "shared runtime store"}
          accent={
            <Badge variant={runtimeStatusVariant(control.status)} appearance="dot">
              {control.status ?? "unknown"}
            </Badge>
          }
        />
      </div>

      <div className="grid-2 align-start">
        <Panel eyebrow="Connection" title="Active database">
          <InfoGrid>
            <InfoRow label="Configured">
              <span className="mono">{data.configured_storage_url}</span>
            </InfoRow>
            <InfoRow label="Runtime schema">
              <span className="mono">{connected.schema_version ?? "—"}</span>
            </InfoRow>
            <InfoRow label="Control schema">
              <span className="mono">{control.schema_version ?? "—"}</span>
            </InfoRow>
            <InfoRow label="Snapshot">
              {control.has_snapshot === undefined ? "—" : control.has_snapshot ? "available" : "not written"}
            </InfoRow>
            <InfoRow label="Updated">
              {control.updated_at ? relTime(control.updated_at) : "—"}
            </InfoRow>
          </InfoGrid>
        </Panel>

        <Panel eyebrow="Provision" title="Database backends">
          <div className="backend-grid">
            {data.available_backends.map((option) => (
              <BackendCard
                key={option.backend}
                option={option}
                connectedBackend={connected.backend}
                busy={busy}
                onProvision={provision}
                canProvision={operator.can("database.provision")}
              />
            ))}
          </div>
        </Panel>
      </div>

      {lastResult && (
        <Panel eyebrow="Provision receipt" title={`${titleize(lastResult.storage.backend ?? "database")} connected`}>
          <InfoGrid>
            <InfoRow label="Status">
              <Badge variant={runtimeStatusVariant(lastResult.status)} appearance="dot">
                {lastResult.status}
              </Badge>
            </InfoRow>
            <InfoRow label="Storage URL">
              <span className="mono">{lastResult.storage_url}</span>
            </InfoRow>
            <InfoRow label="Config">
              <span className="mono">{lastResult.config_path ?? "not persisted"}</span>
            </InfoRow>
            <InfoRow label="Operation">
              <span className="mono">{lastResult.operation?.operation_type ?? "—"}</span>
            </InfoRow>
            <InfoRow label="Event hash">
              <span className="mono">{shortHash(lastResult.operation?.event_hash)}</span>
            </InfoRow>
          </InfoGrid>
        </Panel>
      )}
    </>
  );
}
