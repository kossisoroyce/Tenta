# Runtime

Low-latency transaction scoring service.

The runtime loads Timber-compiled fraud models as native shared libraries and invokes them through the model wrapper. Because scoring is a direct C function call into a signed, dependency-free artifact rather than a Python service hop, the runtime can hold tight p99 budgets under high transaction volume.

Planned responsibilities:

- Receive scoring requests.
- Fetch online features.
- Verify the signature of the loaded Timber artifact on load.
- Call model wrappers (which dispatch to Timber-compiled native inference).
- Apply policy decisions.
- Emit structured decision events.
- Maintain safe fallback behavior, including hot-swap to a previous signed artifact.
