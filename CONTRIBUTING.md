# Contributing

Thanks for helping build Tenta. The project is a pre-release Decision Runtime,
so contributions should prioritize correctness, auditability, and operator
trust over novelty.

## Useful First Areas

- Runtime tests for decision, workload, audit, storage, and governance behavior.
- Workload packs and replay fixtures for new high-stakes decision domains.
- Dashboard polish that maps directly to runtime/control-plane API capabilities.
- Packaging, installation, and deployment improvements.
- Documentation that makes the engine easier to run, extend, and operate.

## Local Development

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
python3 -m unittest discover -s tests
```

Dashboard:

```bash
cd dashboard
pnpm install
pnpm build
```

Run both together:

```bash
tenta serve --host 127.0.0.1 --port 8080
```

## Contribution Principles

- Keep decision safety, auditability, and operational reliability ahead of
  feature breadth.
- Do not commit real customer, patient, account, card, claim, security,
  identity, or production model data.
- Prefer synthetic, anonymized, or tokenized datasets for examples and tests.
- Document behavior that changes decisions, thresholds, healing actions,
  workload validation, storage, or policy enforcement.
- Make failure modes visible through API responses, audit events, metrics, and
  tests.
- Keep model adaptation paths observable, reversible, and role-gated.

## Pull Request Checklist

- Add or update tests for runtime behavior touched by the change.
- Update docs when changing public APIs, CLI commands, storage behavior,
  workload specs, dashboard routes, or safety controls.
- Include migration notes for schema or persisted-state changes.
- Keep generated local state out of Git: `data/`, `audit/`, `dashboard/dist/`,
  and `node_modules/` are intentionally ignored.
- For dashboard work, run `pnpm build` and verify the UI against the runtime API.

## Security And Misuse

Do not include exploit instructions, bypass logic, secrets, production
credentials, or real decision records in issues, examples, tests, or pull
requests. Report sensitive concerns privately according to [SECURITY.md](SECURITY.md).
