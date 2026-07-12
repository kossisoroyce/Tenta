# Dashboard

Operator and analyst interface for the Tenta Decision Runtime: live decisions,
model health, adaptive healing, governance, feedback, and performance.

## Stack

- **React 19** + **TypeScript**, bundled with **Vite**.
- **[Kumo](https://github.com/cloudflare/kumo)** (`@cloudflare/kumo`) for the UI
  component library and design system — Button, Input, Select, Switch, Table,
  Badge, Meter, Text, and Kumo's design tokens (light/dark theming included).
- **[Phosphor](https://phosphoricons.com/)** icons.

The layout chrome (app shell, cards, decision gauge, sliders) lives in
[`src/styles.css`](src/styles.css) and is built entirely on Kumo's CSS design
tokens, so it stays consistent with the component palette in both themes.

## Console

A routed, multi-view operations console (hash router in [`src/router.tsx`](src/router.tsx));
each view is driven entirely by the control-plane API and every operator action
mutates real server state.

| View | Route | Backs onto |
| ---- | ----- | ---------- |
| **Overview** — runtime health, decision mix, dependency status | `#/overview` | `GET /v1/overview` |
| **Live Decisions** — decision request workbench + decision-trail inspector | `#/scoring` | `POST /v1/decision-requests`, `GET /v1/decision-requests/{id}` |
| **Model Health** — stability signals by segment; acknowledge / escalate | `#/drift` | `GET /v1/drift`, `POST /v1/drift/{id}/{acknowledge,escalate}` |
| **Models** — registry, version comparison, load / promote / rollback | `#/models` | `GET /v1/models`, `POST /v1/models/load`, `.../{id}/promote`, `.../rollback` |
| **Adaptive Healing** — approve / reject / rollback with what·why·who·outcome | `#/healing` | `GET /v1/healing/actions`, `POST .../{id}/{approve,reject,rollback}` |
| **Audit & Approvals** — immutable governance trail | `#/governance` | `GET /v1/policy/history` |
| **Human Feedback** — outcome loop + label delay | `#/feedback` | `GET /v1/feedback` |
| **Metrics** — latency, throughput, model comparison | `#/benchmarks` | `GET /v1/benchmarks` |

Promoting a model actually swaps the live scorer; every approve/promote/rollback
is recorded to policy history. Light/dark theming is system-aware with a manual
toggle. The control plane lives in `runtime/tenta_runtime/control_plane.py` and
its routes in `console_api.py`.

## Develop

```bash
cd dashboard
pnpm install
pnpm dev        # Vite dev server on http://localhost:5173, proxies /v1 → :8080
```

Run the runtime alongside it so API calls resolve:

```bash
PYTHONPATH=runtime python3 -m tenta_runtime --host 127.0.0.1 --port 8080 --audit-path audit/decisions.jsonl
```

## Build

The runtime serves the production build from `dashboard/dist` (see
`runtime/tenta_runtime/api.py::default_static_dir`). Assets are emitted under the
`/dashboard/` base path so the runtime's static handler resolves them.

```bash
cd dashboard
pnpm build      # outputs dashboard/dist
```

Then start the runtime and open the served dashboard:

```bash
PYTHONPATH=runtime python3 -m tenta_runtime --host 127.0.0.1 --port 8080 --audit-path audit/decisions.jsonl
# → http://127.0.0.1:8080/
```

> `dist/` and `node_modules/` are gitignored; run `pnpm build` after cloning
> before serving the dashboard from the runtime.
