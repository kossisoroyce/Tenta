# 11 - Plugin SDK

The plugin SDK allows teams to add models, drift detectors, feature connectors, policy rules, and dashboard extensions.

## Plugin Types

- Model plugins.
- Drift detector plugins.
- Feature connector plugins.
- Policy rule plugins.
- Healing action plugins.
- Dashboard panel plugins.

## Manifest Sketch

```json
{
  "name": "psi-drift-detector",
  "version": "0.1.0",
  "type": "drift-detector",
  "entrypoint": "plugin:Detector",
  "permissions": ["read:feature_stats", "write:drift_events"]
}
```

## SDK Requirements

- Stable interfaces.
- Versioned contracts.
- Permission declarations.
- Test harnesses for plugin authors.
- Sandboxed execution for untrusted extensions where possible.

