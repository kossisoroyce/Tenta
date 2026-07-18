import { useCallback, useEffect, useMemo, useState } from "react";
import { Badge, Button, Input, Select, Switch, Text } from "@cloudflare/kumo";
import { MagnifyingGlassIcon } from "@phosphor-icons/react";

import {
  activateWorkload,
  getOverview,
  getTransaction,
  getWorkloads,
  postScore,
  type DecisionRecord,
  type ScoreResponse,
} from "../api";
import { InfoGrid, InfoRow, Panel, PageHeader } from "../components";
import { RiskGauge } from "../components/RiskGauge";
import { useOperator, useToast } from "../governance";
import { useApi } from "../hooks";
import { decisionVariant, fmtMs, titleize } from "../lib";
import { useRouteParams } from "../router";

const CHANNELS = { web: "Web", mobile: "Mobile", card_present: "Card present", api: "API" };

function randomHex() {
  return Math.random().toString(16).slice(2, 8);
}

export function Scoring() {
  const { data: overview } = useApi(getOverview, 8000);
  const { data: workloads, refresh: refreshWorkloads } = useApi(getWorkloads, 10000);
  const params = useRouteParams();
  const operator = useOperator();
  const toast = useToast();

  const [transactionId, setTransactionId] = useState(`req-${randomHex()}`);
  const [selectedWorkload, setSelectedWorkload] = useState("");
  const [workloadBusy, setWorkloadBusy] = useState<string | null>(null);
  const [workloadError, setWorkloadError] = useState<string | null>(null);
  const [accountId, setAccountId] = useState(`subj-${Math.floor(1000 + Math.random() * 9000)}`);
  const [amount, setAmount] = useState("420");
  const [channel, setChannel] = useState("web");
  const [merchantRisk, setMerchantRisk] = useState(0.2);
  const [velocity, setVelocity] = useState(2);
  const [accountAge, setAccountAge] = useState("180");
  const [chargebacks, setChargebacks] = useState("0");
  const [highRisk, setHighRisk] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [trail, setTrail] = useState<DecisionRecord | null>(null);

  const [lookupId, setLookupId] = useState("");
  const [lookupError, setLookupError] = useState<string | null>(null);
  const decisionParam = params.get("decision");

  useEffect(() => {
    if (workloads?.active_workload_id && !selectedWorkload) {
      setSelectedWorkload(workloads.active_workload_id);
    }
  }, [selectedWorkload, workloads?.active_workload_id]);

  useEffect(() => {
    if (!decisionParam) return;
    let cancelled = false;
    setLookupId(decisionParam);
    getTransaction(decisionParam)
      .then((record) => {
        if (cancelled) return;
        setTrail(record);
        setLookupError(null);
      })
      .catch(() => {
        if (!cancelled) setLookupError(`No decision found for "${decisionParam}".`);
      });
    return () => {
      cancelled = true;
    };
  }, [decisionParam]);

  const workloadItems = useMemo(() => {
    if (!workloads) return {};
    return Object.fromEntries(workloads.workloads.map((w) => [w.workload_id, w.name]));
  }, [workloads]);

  const activeWorkload =
    workloads?.workloads.find((w) => w.workload_id === selectedWorkload) ?? workloads?.active;

  const changeWorkload = useCallback(
    async (value: string) => {
      setSelectedWorkload(value);
      setWorkloadBusy(value);
      setWorkloadError(null);
      try {
        await activateWorkload(value, operator.payload(`Activated workload ${value} from Live Decisions.`));
        await refreshWorkloads();
        toast.notify({ tone: "success", title: "Workload activated", detail: value });
      } catch (err) {
        const message = err instanceof Error ? err.message : "Could not activate workload";
        setWorkloadError(message);
        toast.notify({ tone: "error", title: "Workload activation failed", detail: message });
      } finally {
        setWorkloadBusy(null);
      }
    },
    [operator, refreshWorkloads, toast],
  );

  const submit = useCallback(
    async (event: React.FormEvent) => {
      event.preventDefault();
      setSubmitting(true);
      setError(null);
      try {
        const result: ScoreResponse = await postScore({
          decision_request_id: transactionId.trim(),
          workload_id: selectedWorkload || workloads?.active_workload_id,
          subject_id: accountId.trim(),
          context_id: selectedWorkload || "reference-workload",
          value: Number(amount) || 0,
          currency: "USD",
          channel,
          event_time: new Date().toISOString(),
          features: {
            entity_risk: merchantRisk,
            velocity_10m: velocity,
            subject_age_days: Number(accountAge) || 0,
            prior_adverse_events: Number(chargebacks) || 0,
            high_risk_segment: highRisk,
          },
        });
        setTrail(result);
        setLookupError(null);
        setTransactionId(`req-${randomHex()}`);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Decision request failed");
      } finally {
        setSubmitting(false);
      }
    },
    [
      transactionId,
      selectedWorkload,
      workloads?.active_workload_id,
      accountId,
      amount,
      channel,
      merchantRisk,
      velocity,
      accountAge,
      chargebacks,
      highRisk,
    ],
  );

  const lookup = useCallback(async () => {
    const id = lookupId.trim();
    if (!id) return;
    try {
      const record = await getTransaction(id);
      setTrail(record);
      setLookupError(null);
    } catch {
      setLookupError(`No decision found for "${id}".`);
    }
  }, [lookupId]);

  const decision = trail ? String(trail.decision) : "waiting";
  const policy = overview?.health.policy;
  const model = overview?.health.model;

  return (
    <>
      <PageHeader
        eyebrow="Live Decisions"
        title="Run & inspect decision requests"
        description="Submit a reference workload request against the live model and inspect the full decision trail: score, policy path, model version, and reason codes."
      />

      {workloadError && <div className="error-state">{workloadError}</div>}

      <div className="grid-2 align-start">
        <Panel eyebrow="New request" title="Decision request">
          <form className="score-form" onSubmit={submit}>
            <div className="col-span">
              <Select
                label="Workload"
                size="sm"
                value={selectedWorkload || workloads?.active_workload_id || ""}
                onValueChange={(v) => changeWorkload(String(v))}
                items={workloadItems}
                disabled={!operator.can("workload.activate")}
              />
              {activeWorkload && (
                <p className="empty-hint">
                  {activeWorkload.domain} · {activeWorkload.feature_count} features · review{" "}
                  {activeWorkload.policy.review_threshold} · block {activeWorkload.policy.block_threshold}
                  {workloadBusy ? " · activating..." : ""}
                </p>
              )}
            </div>
            <Input label="Request ID" size="sm" value={transactionId} onChange={(e) => setTransactionId(e.target.value)} required />
            <Input label="Subject ID" size="sm" value={accountId} onChange={(e) => setAccountId(e.target.value)} required />
            <Input label="Amount (USD)" size="sm" type="number" min={0} value={amount} onChange={(e) => setAmount(e.target.value)} required />
            <Select label="Channel" size="sm" value={channel} onValueChange={(v) => setChannel(v as string)} items={CHANNELS} />

            <div className="slider">
              <div className="slider-head">
                <span>Entity risk</span>
                <b>{merchantRisk.toFixed(2)}</b>
              </div>
              <input type="range" min={0} max={1} step={0.01} value={merchantRisk} onChange={(e) => setMerchantRisk(Number(e.target.value))} />
            </div>
            <div className="slider">
              <div className="slider-head">
                <span>Velocity 10m</span>
                <b>{velocity}</b>
              </div>
              <input type="range" min={0} max={40} step={1} value={velocity} onChange={(e) => setVelocity(Number(e.target.value))} />
            </div>

            <Input label="Subject age (days)" size="sm" type="number" min={0} value={accountAge} onChange={(e) => setAccountAge(e.target.value)} />
            <Input label="Prior adverse events" size="sm" type="number" min={0} value={chargebacks} onChange={(e) => setChargebacks(e.target.value)} />

            <div className="col-span">
              <Switch checked={highRisk} onClick={() => setHighRisk((v) => !v)} controlFirst label="High-risk segment" />
            </div>
            {error && (
              <div className="col-span">
                <Text variant="error" size="sm">{error}</Text>
              </div>
            )}
            <div className="col-span">
              <Button type="submit" variant="primary" loading={submitting}>Run decision</Button>
            </div>
          </form>

          <div className="inspect-row">
            <Input
              size="sm"
              placeholder="Inspect an existing decision request id..."
              value={lookupId}
              onChange={(e) => setLookupId(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && lookup()}
            />
            <Button variant="secondary" size="sm" icon={<MagnifyingGlassIcon size={15} />} onClick={lookup}>
              Inspect
            </Button>
          </div>
          {lookupError && (
            <Text variant="error" size="sm">{lookupError}</Text>
          )}
        </Panel>

        <Panel
          eyebrow="Decision trail"
          title="Latest decision"
          className="sticky-panel"
          actions={<Badge variant={decisionVariant(decision)}>{decision}</Badge>}
        >
          <div className="gauge">
            <RiskGauge score={trail?.score ?? 0} decision={decision} />
          </div>

          {trail ? (
            <>
              <InfoGrid>
                <InfoRow label="Request">
                  <span className="mono">{trail.decision_request_id ?? trail.transaction_id}</span>
                </InfoRow>
                <InfoRow label="Workload">
                  <span className="mono">{trail.workload_id ?? selectedWorkload ?? overview?.health.workload?.workload_id ?? "—"}</span>
                </InfoRow>
                <InfoRow label="Decision">
                  <Badge variant={decisionVariant(decision)}>{decision}</Badge>
                </InfoRow>
                <InfoRow label="Model">
                  <span className="mono">
                    {trail.model_id ?? model?.model_id} · {trail.model_version ?? model?.model_version}
                  </span>
                </InfoRow>
                <InfoRow label="Policy">
                  <span className="mono">{trail.policy_version ?? policy?.version}</span>
                </InfoRow>
                <InfoRow label="Thresholds">
                  <span className="mono">
                    review {policy?.review_threshold ?? "—"} · block {policy?.block_threshold ?? "—"}
                  </span>
                </InfoRow>
                <InfoRow label="Latency">
                  <span className="mono">{fmtMs(trail.latency_ms)}</span>
                </InfoRow>
              </InfoGrid>

              <div className="trail-reasons">
                <span className="eyebrow">Why this decision</span>
                <div className="reason-list">
                  {(trail.reason_codes ?? []).length === 0 ? (
                    <Text variant="secondary" size="sm">No reason codes.</Text>
                  ) : (
                    (trail.reason_codes ?? []).map((code) => (
                      <Badge key={code} variant="outline">{titleize(code)}</Badge>
                    ))
                  )}
                </div>
              </div>
            </>
          ) : (
            <>
              <p className="empty-hint">
                Run or inspect a request to see its full decision trail. This request will be
                scored by:
              </p>
              <InfoGrid>
                <InfoRow label="Live model">
                  <span className="mono">
                    {model?.model_id ?? "—"} · {model?.model_version ?? ""}
                  </span>
                </InfoRow>
                <InfoRow label="Workload">
                  <span className="mono">
                    {activeWorkload?.name ?? overview?.health.workload?.name ?? "—"}
                  </span>
                </InfoRow>
                <InfoRow label="Policy">
                  <span className="mono">{policy?.version ?? "—"}</span>
                </InfoRow>
                <InfoRow label="Thresholds">
                  <span className="mono">
                    review {policy?.review_threshold ?? "—"} · block {policy?.block_threshold ?? "—"}
                  </span>
                </InfoRow>
              </InfoGrid>
            </>
          )}
        </Panel>
      </div>
    </>
  );
}
