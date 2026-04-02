# TITAN-NL v6 (Kaggle-first training cell)

If you want a **single pasteable Kaggle training cell**, use:

- `kaggle_train_cell.py`

It contains one end-to-end script for:

1. dataset discovery (`Titan30M_Dataset.csv`/fallbacks)
2. triple-barrier return construction
3. v6 trader model heads (direction/gate/size/stop/target/hold/uncertainty/adapt)
4. risk-scaled position computation
5. train / validate / calibrate / backtest
6. model + scaler + memory-state artifact export
7. chunk-level Sharpe annualization (uses chunks/year, not bars/year)
8. leakage-safe supervision (current chunk predicts next chunk returns)
9. model checkpoint + early stop keyed to exposure-adjusted validation score

## How to use in Kaggle

- Open `kaggle_train_cell.py`
- Copy all content into **one notebook cell**
- Run it as-is

Outputs produced:

- `Best_TITAN_V6_KAGGLE.pth`
- `titan_final_memory_state.pt`
- `titan_v6_kaggle_complete.pth`
- `titan_scaler.pkl`
- `titan_feature_schema.json`
