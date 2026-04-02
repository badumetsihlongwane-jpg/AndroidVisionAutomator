# TITAN-NL v6 - Single Kaggle Training Cell (paste/run as one cell)
# - Uses triple-barrier targets
# - Dual-head position output (direction x gate)
# - Adds trader heads (size/stop/target/hold/uncertainty/adapt)
# - Includes risk governor and safe online adaptation stub

import os, math, json, pickle, warnings
from dataclasses import dataclass
from typing import Optional, Tuple, List

import numpy as np
import pandas as pd
import torch
import torch.nn as nn
import torch.nn.functional as F
import torch.optim as optim
from sklearn.preprocessing import RobustScaler
from torch.utils.data import Dataset, DataLoader

warnings.filterwarnings("ignore")

# =========================
# Config
# =========================
PAIRS = ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD"]
NUM_NODES = len(PAIRS)
CHUNK_LEN = 16
D_MODEL = 128
NUM_LAYERS = 3
EPOCHS = 30
PATIENCE = 8
LR = 2e-4
ONLINE_LR = 5e-6
NOISE_STD = 0.01

DATASET_INTERVAL = "30m"  # "15m" or "30m"
BARSPERYEAR_15M = 22176
BARSPERYEAR_30M = 11088
BARSPERYEAR = BARSPERYEAR_30M if DATASET_INTERVAL == "30m" else BARSPERYEAR_15M
CHUNKS_PER_YEAR = max(BARSPERYEAR / CHUNK_LEN, 1.0)

TRAIN_START = "2025-02-26"; TRAIN_END = "2025-10-31"
VAL_START = "2025-11-01"; VAL_END = "2025-12-31"
CALIB_START = "2026-01-01"; CALIB_END = "2026-01-31"
BACKTEST_START = "2026-02-01"; BACKTEST_END = "2026-02-25"

ATR_PERIOD = 14
K_TP = 2.0
K_SL = 1.5
MAX_HOLD = 6 if DATASET_INTERVAL == "30m" else 12

SPREAD_BPS = 1.0
LAMBDA_TC = 0.5
LAMBDA_CVAR = 0.1
TARGET_VOL = 0.001
CVAR_QUANTILE = 0.10

DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")
print("Device:", DEVICE)


def find_dataset() -> str:
    candidates = [
        "Titan30M_Dataset.csv",
        "Titan15M_Dataset.csv",
        "TitanForexDataset.csv",
        "Titan_Dataset.csv",
        "/kaggle/input/titanfx/Titan30M_Dataset.csv",
        "/kaggle/input/titanfx/Titan15M_Dataset.csv",
        "/kaggle/input/titanfx/TitanForexDataset.csv",
        "/kaggle/input/datasets/zackhlongwane/new30m/Titan30M_Dataset.csv",
        "/kaggle/input/datasets/zackhlongwane/titanv2/Titan15M_Dataset.csv",
    ]
    for p in candidates:
        if os.path.exists(p):
            return p

    # Kaggle fallback search
    for root, _, files in os.walk("/kaggle/input"):
        for f in files:
            if f.lower().endswith(".csv") and "titan" in f.lower():
                return os.path.join(root, f)
    raise FileNotFoundError("Could not find Titan CSV in local dir or /kaggle/input")


def compute_triple_barrier_returns(close: np.ndarray) -> np.ndarray:
    T = len(close)
    if T < ATR_PERIOD + 2:
        return np.zeros(T, dtype=np.float32)

    returns = np.diff(close, prepend=close[0])
    atr = pd.Series(np.abs(returns)).ewm(span=ATR_PERIOD, adjust=False).mean().values
    atr = np.maximum(atr, 1e-8)

    realized = np.zeros(T, dtype=np.float32)
    close = close.astype(np.float64)

    for t in range(T - 1):
        entry = close[t]
        tp = entry + K_TP * atr[t]
        sl = entry - K_SL * atr[t]
        end_t = min(t + MAX_HOLD, T - 1)
        outcome = (close[end_t] - entry) / (entry + 1e-12)
        for j in range(t + 1, end_t + 1):
            px = close[j]
            if px >= tp:
                outcome = K_TP * atr[t] / (entry + 1e-12)
                break
            if px <= sl:
                outcome = -K_SL * atr[t] / (entry + 1e-12)
                break
        realized[t] = outcome
    return realized


def load_dataset(path: str):
    df = pd.read_csv(path, index_col=0, parse_dates=True).sort_index().fillna(0)
    numeric_cols = set(df.select_dtypes(include=[np.number]).columns)

    shared = [
        c for c in df.columns
        if c in numeric_cols and not any(c.startswith(p) for p in PAIRS) and not c.startswith("target_")
    ]

    node_arrays = []
    future_rets = []
    schema_cols = {}

    for p in PAIRS:
        cols = [c for c in df.columns if c in numeric_cols and c.startswith(p) and not c.startswith("target_")]
        if not cols:
            lo = p.lower()
            cols = [c for c in df.columns if c in numeric_cols and c.startswith(lo) and not c.startswith("target_")]

        schema_cols[p] = cols + shared
        node_arrays.append(df[cols + shared].values)

        ccol = f"{p}_Close"
        if ccol in df.columns:
            f_ret = compute_triple_barrier_returns(df[ccol].ffill().bfill().values.astype(np.float64))
        else:
            tcol = f"target_{p}_ret_12"
            f_ret = df[tcol].values.astype(np.float32) if tcol in df.columns else np.zeros(len(df), dtype=np.float32)
        future_rets.append(f_ret)

    min_feats = min(arr.shape[1] for arr in node_arrays)
    node_arrays = [arr[:, :min_feats] for arr in node_arrays]

    master = np.stack(node_arrays, axis=1).astype(np.float32)      # [T,N,F]
    rets = np.stack(future_rets, axis=1).astype(np.float32)         # [T,N]

    with open("titan_feature_schema.json", "w") as f:
        json.dump({"pairs": PAIRS, "feats_per_node": min_feats, "shared_cols": shared, "node_cols": schema_cols}, f)

    return master, rets, min_feats, df.index


class SeqDataset(Dataset):
    def __init__(self, X, R, chunk_len):
        self.X = torch.tensor(X, dtype=torch.float32)
        self.R = torch.tensor(R, dtype=torch.float32)
        self.chunk_len = chunk_len
        # Predict next-chunk returns from current-chunk features to avoid
        # same-window leakage in offline backtests.
        self.n = max((len(X) // chunk_len) - 1, 0)
    def __len__(self):
        return self.n
    def __getitem__(self, idx):
        s = idx * self.chunk_len
        e = s + self.chunk_len
        rs = e
        re = e + self.chunk_len
        return self.X[s:e], self.R[rs:re]


class DeltaMemory(nn.Module):
    def __init__(self, d):
        super().__init__()
        self.q = nn.Linear(d, d, bias=False)
        self.k = nn.Linear(d, d, bias=False)
        self.v = nn.Linear(d, d, bias=False)
        self.val = nn.Sequential(nn.Linear(d, d), nn.SiLU(), nn.Linear(d, d))
        self.eta = nn.Sequential(nn.Linear(d, d//4), nn.SiLU(), nn.Linear(d//4, 1), nn.Sigmoid())
        self.alpha = nn.Sequential(nn.Linear(d, d//4), nn.SiLU(), nn.Linear(d//4, 1), nn.Sigmoid())
        self.out = nn.Linear(d, d)
        self.norm = nn.LayerNorm(d)
        self.register_buffer("initM", torch.zeros(d, d))

    def forward(self, x, prev_M=None):
        b,s,n,d = x.shape
        xf = x.view(b*n, s, d)
        q, k, v = self.q(xf), self.k(xf), self.val(self.v(xf))
        eta = self.eta(xf)*0.1 + 0.01
        alpha = self.alpha(xf)*0.5 + 0.5
        M = prev_M if prev_M is not None else self.initM.unsqueeze(0).expand(b*n, -1, -1).clone()
        outs = []
        for t in range(s):
            qt = q[:,t,:]
            kt = F.normalize(k[:,t,:], dim=-1)
            vt = v[:,t,:]
            et = eta[:,t,:].unsqueeze(-1)
            at = alpha[:,t,:].unsqueeze(-1)
            out_t = torch.bmm(M, qt.unsqueeze(-1)).squeeze(-1)
            Mk = torch.bmm(M, kt.unsqueeze(-1))
            M = at*M - et*torch.bmm(Mk, kt.unsqueeze(-2)) + et*torch.bmm(vt.unsqueeze(-1), kt.unsqueeze(-2))
            outs.append(out_t)
        out = torch.stack(outs, dim=1)
        out = self.norm(self.out(out) + xf)
        return out.view(b,s,n,d), M


class TitanNLv6Trader(nn.Module):
    def __init__(self, feats_per_node, d_model=128, num_nodes=4, n_layers=3, hold_buckets=5):
        super().__init__()
        self.embed = nn.Sequential(nn.Linear(feats_per_node, d_model), nn.SiLU(), nn.LayerNorm(d_model))
        self.layers = nn.ModuleList([DeltaMemory(d_model) for _ in range(n_layers)])
        self.cms = nn.Sequential(nn.Linear(d_model, d_model*2), nn.SiLU(), nn.Linear(d_model*2, d_model))
        self.graph = nn.Sequential(nn.Linear(d_model, d_model), nn.GELU())
        self.trunk = nn.Sequential(nn.Linear(d_model, d_model), nn.GELU(), nn.Dropout(0.1))

        self.direction = nn.Sequential(nn.Linear(d_model,1), nn.Tanh())
        self.trade_gate = nn.Sequential(nn.Linear(d_model,1), nn.Sigmoid())
        self.size = nn.Sequential(nn.Linear(d_model,1), nn.Sigmoid())
        self.stop = nn.Sequential(nn.Linear(d_model,1), nn.Softplus())
        self.target = nn.Sequential(nn.Linear(d_model,1), nn.Softplus())
        self.hold = nn.Linear(d_model, hold_buckets)
        self.unc = nn.Sequential(nn.Linear(d_model,1), nn.Sigmoid())
        self.regime = nn.Sequential(nn.Linear(d_model,3), nn.Softmax(dim=-1))
        self.adapt = nn.Sequential(nn.Linear(d_model,3), nn.Softmax(dim=-1))

    def forward(self, x, prev_states=None):
        b,s,n,f = x.shape
        x = self.embed(x)
        states = []
        for i, layer in enumerate(self.layers):
            p = prev_states[i] if prev_states is not None else None
            x, st = layer(x, p)
            states.append(st)
        x = self.cms(x)
        x = self.graph(x[:, -3:, :, :].mean(dim=1))
        t = self.trunk(x)

        direction = self.direction(t)
        gate = self.trade_gate(t)
        size = self.size(t)
        stop = self.stop(t) + 0.1
        target = self.target(t) + 0.2
        hold = F.softmax(self.hold(t), dim=-1)
        unc = self.unc(t)
        regime = self.regime(t)
        adapt = self.adapt(t)

        raw_pos = direction * gate * size
        risk_scale = (1.0 - unc).clamp(0.0, 1.0)
        final_pos = raw_pos * risk_scale

        return {
            "direction": direction,
            "trade_gate": gate,
            "size": size,
            "stop_mult": stop,
            "target_mult": target,
            "hold_horizon": hold,
            "uncertainty": unc,
            "regime_probs": regime,
            "adapt_mode_probs": adapt,
            "position": final_pos,
            "states": states,
        }


class RealPnLLoss(nn.Module):
    def __init__(self):
        super().__init__()
    def forward(self, position, targets, prev_pos=None):
        pos = position.squeeze(-1)
        rv = targets.std(dim=1).clamp(min=1e-8)
        scale = (TARGET_VOL / rv).clamp(0.1, 3.0)
        pos = pos * scale

        r_net = targets.sum(dim=1)
        pnl = pos * r_net

        turnover = (pos - prev_pos).abs().mean() if prev_pos is not None else pos.abs().mean()
        tc = LAMBDA_TC * turnover * (SPREAD_BPS * 1e-4)

        bar_pnl = (pos.unsqueeze(1).expand_as(targets) * targets).reshape(-1)
        k = max(1, int(CVAR_QUANTILE * bar_pnl.numel()))
        worst = torch.topk(bar_pnl, k, largest=False).values
        cvar = -worst.mean()

        return -pnl.mean() + tc + LAMBDA_CVAR * cvar + 0.02 * (pos**2).mean()


def sharpe(sig, ret, per_year=None):
    # sig/ret are chunk-level values in this script, so annualize by chunks/year.
    if per_year is None:
        per_year = CHUNKS_PER_YEAR
    pnl = sig * ret
    mu, sd = pnl.mean(), pnl.std()
    return 0.0 if sd < 1e-8 else (mu / sd) * np.sqrt(per_year)


@torch.no_grad()
def evaluate(model, loader, criterion, init_states=None):
    model.eval()
    prev_states = init_states
    prev_pos = None
    losses, S, R = [], [], []
    for x, r in loader:
        x, r = x.to(DEVICE), r.to(DEVICE)
        out = model(x, prev_states=prev_states)
        pos = out["position"]
        loss = criterion(pos, r, prev_pos)
        losses.append(loss.item())
        prev_states = [s.detach() for s in out["states"]]
        prev_pos = pos.squeeze(-1).detach()
        S.append(pos.squeeze(-1).cpu().numpy())
        R.append(r.sum(dim=1).cpu().numpy())
    if len(S) == 0:
        return 0.0, 0.0, prev_states, np.zeros((0,NUM_NODES)), np.zeros((0,NUM_NODES))
    S = np.concatenate(S, axis=0)
    R = np.concatenate(R, axis=0)
    return float(np.mean(losses)), float(sharpe(S.flatten(), R.flatten())), prev_states, S, R


def train_epoch(model, loader, criterion, optimizer, step):
    model.train()
    prev_states = None
    prev_pos = None
    losses = []
    for x, r in loader:
        x, r = x.to(DEVICE), r.to(DEVICE)
        x = torch.clamp(x + torch.randn_like(x) * NOISE_STD, -10, 10)
        optimizer.zero_grad()
        out = model(x, prev_states=prev_states)
        pos = out["position"]
        loss = criterion(pos, r, prev_pos)
        loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
        optimizer.step()

        prev_states = [s.detach() for s in out["states"]]
        prev_pos = pos.squeeze(-1).detach()
        losses.append(loss.item())
        step += 1
    return float(np.mean(losses)) if losses else 0.0, step


# =========================
# Run pipeline
# =========================
DATASET_PATH = find_dataset()
print("Dataset:", DATASET_PATH)

master, future_returns, feats_per_node, dates = load_dataset(DATASET_PATH)

train_idx = np.where((dates >= TRAIN_START) & (dates <= TRAIN_END))[0]
val_idx = np.where((dates >= VAL_START) & (dates <= VAL_END))[0]
calib_idx = np.where((dates >= CALIB_START) & (dates <= CALIB_END))[0]
backtest_idx = np.where((dates >= BACKTEST_START) & (dates <= BACKTEST_END))[0]

if len(train_idx) < CHUNK_LEN:
    raise ValueError(f"Train bars {len(train_idx)} < CHUNK_LEN {CHUNK_LEN}")

N, Nodes, Feats = master.shape
scaler = RobustScaler().fit(master[train_idx].reshape(-1, Feats))
scaled = scaler.transform(master.reshape(-1, Feats)).reshape(N, Nodes, Feats)
scaled = np.nan_to_num(scaled, nan=0.0, posinf=5.0, neginf=-5.0)

with open("titan_scaler.pkl", "wb") as f:
    pickle.dump(scaler, f)

train_ds = SeqDataset(scaled[train_idx], future_returns[train_idx], CHUNK_LEN)
val_ds = SeqDataset(scaled[val_idx], future_returns[val_idx], CHUNK_LEN)
calib_ds = SeqDataset(scaled[calib_idx], future_returns[calib_idx], CHUNK_LEN)
back_ds = SeqDataset(scaled[backtest_idx], future_returns[backtest_idx], CHUNK_LEN)

if len(train_ds) == 0 or len(val_ds) == 0:
    raise ValueError(
        "Insufficient split size for next-chunk supervision. "
        "Increase date window or reduce CHUNK_LEN."
    )

train_loader = DataLoader(train_ds, batch_size=1, shuffle=False, drop_last=True)
val_loader = DataLoader(val_ds, batch_size=1, shuffle=False)
calib_loader = DataLoader(calib_ds, batch_size=1, shuffle=False)
back_loader = DataLoader(back_ds, batch_size=1, shuffle=False)

model = TitanNLv6Trader(feats_per_node=feats_per_node, d_model=D_MODEL, num_nodes=NUM_NODES, n_layers=NUM_LAYERS).to(DEVICE)
criterion = RealPnLLoss()
optimizer = optim.AdamW(model.parameters(), lr=LR, weight_decay=1e-4)

best = 1e9
pat = 0
step = 0
save_name = "Best_TITAN_V6_KAGGLE.pth"

print(f"Train chunks={len(train_ds)} | Val chunks={len(val_ds)} | Calib chunks={len(calib_ds)} | Backtest chunks={len(back_ds)}")

for ep in range(EPOCHS):
    tr_loss, step = train_epoch(model, train_loader, criterion, optimizer, step)
    vl_loss, vl_sh, _, _, _ = evaluate(model, val_loader, criterion)
    print(f"Epoch {ep+1:02d}/{EPOCHS} | train_loss={tr_loss:.6f} | val_loss={vl_loss:.6f} | val_sharpe={vl_sh:.4f}")

    if vl_loss < best:
        best = vl_loss
        pat = 0
        torch.save(model.state_dict(), save_name)
    else:
        pat += 1
        if pat >= PATIENCE:
            print("Early stop.")
            break

# reload best robustly
best_state = torch.load(save_name, map_location=DEVICE)
model.load_state_dict(best_state)

# chronological priming
_, _, states, _, _ = evaluate(model, train_loader, criterion)
_, _, states, _, _ = evaluate(model, val_loader, criterion, init_states=states)

# calibration phase (tiny LR)
calib_opt = optim.AdamW(model.parameters(), lr=ONLINE_LR * 10, weight_decay=1e-4)
calib_prev_pos = None
model.train()
for x, r in calib_loader:
    x, r = x.to(DEVICE), r.to(DEVICE)
    calib_opt.zero_grad()
    out = model(x, prev_states=states)
    states = [s.detach() for s in out["states"]]
    loss = criterion(out["position"], r, calib_prev_pos)
    loss.backward()
    torch.nn.utils.clip_grad_norm_(model.parameters(), 0.5)
    calib_opt.step()
    calib_prev_pos = out["position"].squeeze(-1).detach()

# backtest
bt_loss, bt_sh, final_states, sig_arr, ret_arr = evaluate(model, back_loader, criterion, init_states=states)
print(f"Backtest loss={bt_loss:.6f} | Backtest Sharpe={bt_sh:.4f} | Chunks={len(sig_arr)}")

for i, p in enumerate(PAIRS):
    ps = sharpe(sig_arr[:, i], ret_arr[:, i]) if len(sig_arr) else 0.0
    wr = (np.sign(sig_arr[:, i]) == np.sign(ret_arr[:, i])).mean() * 100 if len(sig_arr) else 0.0
    pnl = (sig_arr[:, i] * ret_arr[:, i]).sum() * 100 if len(sig_arr) else 0.0
    print(f"{p:<7} | Sharpe={ps:>7.3f} | WinRate={wr:>6.2f}% | CumPnL={pnl:>8.4f}%")

# save deploy artifacts
torch.save(final_states, "titan_final_memory_state.pt")
torch.save(
    {
        "model_state_dict": model.state_dict(),
        "config": {
            "pairs": PAIRS,
            "feats_per_node": feats_per_node,
            "d_model": D_MODEL,
            "chunk_len": CHUNK_LEN,
            "dataset_interval": DATASET_INTERVAL,
        },
    },
    "titan_v6_kaggle_complete.pth",
)

print("Done. Saved: Best_TITAN_V6_KAGGLE.pth, titan_final_memory_state.pt, titan_v6_kaggle_complete.pth")
