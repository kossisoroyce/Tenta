const DECISION_COLOR: Record<string, string> = {
  allow: "var(--color-kumo-success)",
  review: "var(--color-kumo-warning)",
  block: "var(--color-kumo-danger)",
  waiting: "var(--color-kumo-line)",
};

interface DecisionGaugeProps {
  score: number;
  decision: string;
}

/** Circular progress ring: arc length tracks the score, colour tracks the decision. */
export function RiskGauge({ score, decision }: DecisionGaugeProps) {
  const radius = 82;
  const circumference = 2 * Math.PI * radius;
  const clamped = Math.max(0, Math.min(1, score));
  const dash = clamped * circumference;
  const color = DECISION_COLOR[decision] ?? "var(--color-kumo-brand)";

  return (
    <div className="gauge-ring">
      <svg viewBox="0 0 200 200" role="img" aria-label={`Decision score ${score.toFixed(2)}`}>
        <circle
          cx="100"
          cy="100"
          r={radius}
          fill="none"
          stroke="var(--color-kumo-fill)"
          strokeWidth="15"
        />
        <circle
          cx="100"
          cy="100"
          r={radius}
          fill="none"
          stroke={color}
          strokeWidth="15"
          strokeLinecap="round"
          strokeDasharray={`${dash} ${circumference - dash}`}
          style={{ transition: "stroke-dasharray 550ms ease, stroke 300ms ease" }}
        />
      </svg>
      <div className="gauge-center">
        <div className="gauge-score">{score.toFixed(2)}</div>
        <div className="gauge-label">Decision score</div>
      </div>
    </div>
  );
}
