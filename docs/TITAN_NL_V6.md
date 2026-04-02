# TITAN-NL v6 Kaggle Trainer (Single-Cell Ready)

If you want a **single code cell you can paste into Kaggle and run**, use:

- `backend/models/titan_nl_v6_kaggle_train.py`

That file is intentionally self-contained and includes:

- dataset auto-discovery for common Titan CSV paths
- triple-barrier target generation fallback
- v6 policy model heads (direction, gate, size, stop, target, hold, uncertainty, adapt)
- risk governor
- sequential chunk training/evaluation loops
- calibration + backtest pass
- artifact saves (`.pth`, scaler, metadata json)

## Quick usage in Kaggle

1. Open the file.
2. Copy everything.
3. Paste into **one notebook cell**.
4. Run.

## Outputs

- `Best_TITAN_NL_V6.pth`
- `TitanNLv6_complete.pth`
- `titan_scaler.pkl`
- `titan_v6_meta.json`

## Note

This is optimized for practical execution in Kaggle notebook environments and avoids external project wiring.
