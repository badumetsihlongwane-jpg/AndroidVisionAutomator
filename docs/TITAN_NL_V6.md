# TITAN-NL v6 Kaggle Training (Single-Cell)

You asked for a single paste-and-run Kaggle training cell.

Use:

- `notebooks/titan_nl_v6_kaggle_train_cell.py`

This file is intentionally self-contained so you can paste it into one Kaggle
notebook cell and train directly.

## What is included in that single cell

- Dataset auto-discovery for common Kaggle Titan paths.
- Triple-barrier target computation with fallback to `target_{PAIR}_ret_12`.
- Sequential chunk dataset for chronological TBPTT-style training.
- TITAN v5-style memory core blocks:
  - `SelfModifyingDeltaMemory`
  - `ContinuumMemoryMLP`
  - `MarketRegimeMemory`
- TITAN v6 policy heads:
  - direction, trade_gate, size
  - stop_mult, target_mult, hold_horizon
  - uncertainty, regime_probs, adapt_mode_probs
- Risk governor producing final position/size/risk scale.
- Real-PnL loss (transaction cost + CVaR + regularization + abstention shaping).
- Full train/validation loop with early stopping and checkpoint saving.

## Outputs

Running the cell writes:

- `Best_TITAN_NL_v6.pth`
- `titan_scaler.pkl`
- `titan_feature_schema.json`
