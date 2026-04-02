# TITAN-NL v6 (Trader Policy Skeleton)

This repository now includes a v6 trading-policy skeleton at:

- `backend/models/titan_nl_v6.py`

## What it adds

The model emits a full policy tuple rather than a single directional scalar:

- `direction` in `[-1, 1]`
- `trade_gate` in `[0, 1]`
- `size` in `[0, 1]`
- `stop_mult` positive
- `target_mult` positive
- `hold_horizon` as bucket probabilities
- `uncertainty` in `[0, 1]`
- `regime_probs`
- `adapt_mode_probs` for:
  - `memory_only`
  - `tiny_weight_update`
  - `freeze`

A `RiskGovernor` then produces `final_policy` with a risk-scaled approved
position and an adaptation override when runtime risk telemetry is elevated.

## Runtime controls

The `LiveStats` dataclass supports immediate controls:

- drawdown-based throttling
- spread percentile veto
- regime instability freeze mode

## Important note

This is intentionally a scaffold:

- It preserves the API and head structure needed for v6 rollout.
- It uses lightweight placeholders for the full v5 memory/CMS graph stack.
- Replace placeholders with production v5 components to complete integration.
