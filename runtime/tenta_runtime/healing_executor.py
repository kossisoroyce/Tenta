"""Apply and roll back approved healing actions."""

from __future__ import annotations

from typing import Any, Dict, Optional

from .control_plane import ControlPlane
from .engine import RuntimeEngine
from .governance import ActorContext
from .policy import DecisionPolicy


class HealingExecutor:
    def __init__(self, engine: RuntimeEngine, control_plane: ControlPlane) -> None:
        self.engine = engine
        self.cp = control_plane

    def execute(self, action_id: str, actor_context: ActorContext) -> Dict[str, Any]:
        action = self._action(action_id)
        effect = self._apply_effect(action)
        return self.cp.apply_healing_execution(
            action_id,
            effect,
            actor_context.actor,
            operation_context=actor_context.to_dict(),
        )

    def rollback(self, action_id: str, actor_context: ActorContext) -> Dict[str, Any]:
        action = self._action(action_id)
        rollback_effect = self._rollback_effect(action)
        return self.cp.rollback_action(
            action_id,
            actor_context.actor,
            operation_context=actor_context.to_dict(),
            rollback_effect=rollback_effect,
        )

    def _action(self, action_id: str) -> Dict[str, Any]:
        action = next((item for item in self.cp.healing_actions()["actions"] if item["id"] == action_id), None)
        if action is None:
            raise KeyError(f"healing action '{action_id}' not found")
        return action

    def _apply_effect(self, action: Dict[str, Any]) -> Dict[str, Any]:
        plan = dict(action.get("execution_plan") or {})
        kind = str(plan.get("kind") or self._default_kind(action)).strip()
        if kind == "policy_threshold":
            return self._apply_policy_threshold(action, plan)
        if kind == "manual_review_override":
            return self._apply_manual_review(action, plan)
        if kind == "fallback_traffic":
            return self._apply_runtime_control(action, "fallback_traffic_pct", int(plan.get("traffic_pct", 5)))
        if kind == "online_learning":
            return self._apply_runtime_control(action, "online_learning_enabled", bool(plan.get("enabled", False)))
        if kind == "shadow_scoring":
            return self._apply_runtime_control(action, "shadow_scoring_enabled", bool(plan.get("enabled", True)))
        return {
            "kind": "noop",
            "note": f"No executor effect registered for action type {action.get('type')}.",
            "rollback_criteria": dict(action.get("rollback_criteria") or {}),
        }

    def _apply_policy_threshold(self, action: Dict[str, Any], plan: Dict[str, Any]) -> Dict[str, Any]:
        before_policy = self.engine.policy
        target = plan.get("review_threshold")
        if target is None:
            target = before_policy.review_threshold + float(plan.get("review_threshold_delta", -0.01))
        bounds = dict(plan.get("bounds") or {})
        lo, hi = _threshold_bounds(bounds.get("review_threshold"), default=(0.60, 0.70))
        target = round(max(lo, min(hi, float(target))), 4)
        after_policy = DecisionPolicy(
            version=f"{before_policy.version}+{action['id']}",
            review_threshold=target,
            block_threshold=before_policy.block_threshold,
        )
        self.engine.replace_policy(after_policy)
        return {
            "kind": "policy_threshold",
            "note": f"Review threshold changed {before_policy.review_threshold:.2f} -> {target:.2f}.",
            "before": before_policy.health(),
            "after": after_policy.health(),
            "rollback": {"policy": before_policy.health()},
            "rollback_criteria": dict(action.get("rollback_criteria") or {}),
        }

    def _apply_manual_review(self, action: Dict[str, Any], plan: Dict[str, Any]) -> Dict[str, Any]:
        monitor = self._linked_monitor(action.get("linked_drift"))
        override = {
            "segment": monitor.get("segment") if monitor else "Unsegmented",
            "review_rate_delta": plan.get("review_rate_delta", "+2.5pp"),
            "linked_drift": action.get("linked_drift"),
            "action_id": action["id"],
        }
        before = self.cp.set_manual_review_override(action["id"], override)
        return {
            "kind": "manual_review_override",
            "note": f"Manual review override applied for {override['segment']}.",
            "before": before,
            "after": override,
            "rollback": {"previous_override": before},
            "rollback_criteria": dict(action.get("rollback_criteria") or {}),
        }

    def _apply_runtime_control(self, action: Dict[str, Any], key: str, value: Any) -> Dict[str, Any]:
        before = self.cp.set_runtime_control(key, value)
        return {
            "kind": "runtime_control",
            "control": key,
            "note": f"Runtime control {key} changed from {before} to {value}.",
            "before": before,
            "after": value,
            "rollback": {"control": key, "value": before},
            "rollback_criteria": dict(action.get("rollback_criteria") or {}),
        }

    def _rollback_effect(self, action: Dict[str, Any]) -> Dict[str, Any]:
        effect = dict(action.get("execution") or {})
        kind = effect.get("kind")
        if kind == "policy_threshold":
            policy = dict(effect.get("rollback", {}).get("policy") or {})
            restored = DecisionPolicy(
                version=str(policy.get("version") or "policy-baseline-0.1.0"),
                review_threshold=float(policy.get("review_threshold", 0.65)),
                block_threshold=float(policy.get("block_threshold", 0.85)),
            )
            before = self.engine.policy.health()
            self.engine.replace_policy(restored)
            return {"kind": kind, "before": before, "after": restored.health()}
        if kind == "manual_review_override":
            previous = effect.get("rollback", {}).get("previous_override")
            before = self.cp.set_manual_review_override(action["id"], previous)
            return {"kind": kind, "before": before, "after": previous}
        if kind == "runtime_control":
            rollback = dict(effect.get("rollback") or {})
            control = str(rollback.get("control") or "")
            before = self.cp.set_runtime_control(control, rollback.get("value"))
            return {"kind": kind, "control": control, "before": before, "after": rollback.get("value")}
        return {"kind": "noop", "note": "No execution effect was present to roll back."}

    def _linked_monitor(self, monitor_id: Optional[str]) -> Optional[Dict[str, Any]]:
        if not monitor_id:
            return None
        return next((item for item in self.cp.drift()["monitors"] if item["id"] == monitor_id), None)

    def _default_kind(self, action: Dict[str, Any]) -> str:
        action_type = action.get("type")
        if action_type == "adjust_threshold":
            return "policy_threshold"
        if action_type == "increase_manual_review":
            return "manual_review_override"
        if action_type == "shift_to_fallback":
            return "fallback_traffic"
        if action_type == "disable_online_learning":
            return "online_learning"
        if action_type == "enable_shadow":
            return "shadow_scoring"
        return "noop"


def _threshold_bounds(raw: Any, default: tuple[float, float]) -> tuple[float, float]:
    if isinstance(raw, (list, tuple)) and len(raw) == 2:
        return float(raw[0]), float(raw[1])
    return default
