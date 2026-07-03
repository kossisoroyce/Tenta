# 14 - Kubernetes

Kubernetes deployment should isolate the live scoring path from analysis, training, and dashboard workloads.

## Services

- `runtime`: transaction scoring service.
- `controller`: policy and healing orchestration.
- `drift-detector`: streaming or scheduled drift jobs.
- `dashboard`: operator interface.
- `model-registry-adapter`: model metadata and artifact access.
- `event-writer`: durable event persistence.

## Kubernetes Objects

- Deployments for stateless services.
- StatefulSets or managed services for stateful stores when needed.
- HorizontalPodAutoscalers for runtime and streaming consumers.
- ConfigMaps for non-secret configuration.
- Secrets for credentials.
- NetworkPolicies for service isolation.

## Operational Requirements

- Readiness checks must verify model and policy availability.
- Liveness checks must avoid restarting slow but healthy services.
- Runtime pods should have strict CPU and memory limits.
- Shadow models should be deployed separately from active scoring.

