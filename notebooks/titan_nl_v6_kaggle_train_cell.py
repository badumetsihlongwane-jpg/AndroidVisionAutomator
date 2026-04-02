# TITAN-NL v6 — Single-Cell Kaggle Training Script
# Copy/paste this whole file into one Kaggle notebook cell and run.

import os
import math
import json
import random
import pickle
from dataclasses import dataclass
from typing import Optional, Tuple, List, Dict

import numpy as np
import pandas as pd
import torch
import torch.nn as nn
import torch.nn.functional as F
import torch.optim as optim
from sklearn.preprocessing import RobustScaler
from torch.utils.data import Dataset, DataLoader

# -----------------------------
# Config
# -----------------------------
@dataclass
class CFG:
    seed: int = 42
    pairs: Tuple[str, ...] = ("EURUSD", "GBPUSD", "USDJPY", "AUDUSD")
    chunk_len: int = 16
    d_model: int = 128
    layers: int = 3
    epochs: int = 40
    patience: int = 10
    lr: float = 1.5e-4
    batch_size: int = 1
    noise_std: float = 0.01

    # Loss / risk
    spread_bps: float = 1.0
    lambda_tc: float = 0.5
    lambda_cvar: float = 0.1
    lambda_l2: float = 0.02
    target_vol: float = 0.001
    cvar_q: float = 0.10

    # Triple barrier
    atr_period: int = 14
    k_tp: float = 2.0
    k_sl: float = 1.5
    max_hold_30m: int = 6

    # Dates (30m dataset expected)
    train_start: str = "2025-02-26"
    train_end: str = "2025-10-31"
    val_start: str = "2025-11-01"
    val_end: str = "2025-12-31"

    # v6 heads
    hold_buckets: Tuple[int, ...] = (1, 2, 4, 6, 12)

CFG = CFG()


def seed_everything(seed: int = 42):
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)

seed_everything(CFG.seed)
DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")
print("Device:", DEVICE)

# -----------------------------
# Data helpers
# -----------------------------
def find_dataset() -> str:
    candidates = [
        "./Titan30M_Dataset.csv",
        "./Titan15M_Dataset.csv",
        "./TitanForexDataset.csv",
        "/kaggle/input/titanfx/Titan30M_Dataset.csv",
        "/kaggle/input/titanfx/Titan15M_Dataset.csv",
        "/kaggle/input/titanfx/TitanForexDataset.csv",
        "/kaggle/input/datasets/zackhlongwane/new30m/Titan30M_Dataset.csv",
        "/kaggle/input/datasets/zackhlongwane/titanv2/Titan15M_Dataset.csv",
    ]
    for p in candidates:
        if os.path.exists(p):
            return p
    raise FileNotFoundError("No Titan dataset found. Add dataset path to find_dataset().")


def compute_triple_barrier_returns(close: np.ndarray, k_tp: float, k_sl: float, max_hold: int, atr_period: int):
    T = len(close)
    if T < atr_period + 2:
        return np.zeros(T, dtype=np.float32)

    tr = np.abs(np.diff(close, prepend=close[0]))
    atr = pd.Series(tr).ewm(span=atr_period, adjust=False).mean().values
    atr = np.maximum(atr, 1e-8)

    out = np.zeros(T, dtype=np.float32)
    close = close.astype(np.float64)
    for t in range(T - 1):
        entry = close[t]
        tp = entry + k_tp * atr[t]
        sl = entry - k_sl * atr[t]
        end_t = min(t + max_hold, T - 1)

        realized = (close[end_t] - entry) / (entry + 1e-12)
        for j in range(t + 1, end_t + 1):
            px = close[j]
            if px >= tp:
                realized = k_tp * atr[t] / (entry + 1e-12)
                break
            if px <= sl:
                realized = -k_sl * atr[t] / (entry + 1e-12)
                break
        out[t] = realized
    return out


def load_dataset(cfg: CFG):
    path = find_dataset()
    print("Loading:", path)
    df = pd.read_csv(path, index_col=0, parse_dates=True).sort_index().fillna(0)

    numeric_cols = set(df.select_dtypes(include=[np.number]).columns)
    shared = [
        c for c in df.columns
        if c in numeric_cols and not any(c.startswith(p) for p in cfg.pairs) and not c.startswith("target_")
    ]

    node_arrays = []
    for p in cfg.pairs:
        cols = [c for c in df.columns if c in numeric_cols and c.startswith(p) and not c.startswith("target_")]
        if not cols:
            cols = [c for c in df.columns if c in numeric_cols and c.startswith(p.lower()) and not c.startswith("target_")]
        if not cols:
            raise ValueError(f"No numeric features found for pair={p}")
        node_arrays.append(df[cols + shared].values)

    min_feats = min(a.shape[1] for a in node_arrays)
    node_arrays = [a[:, :min_feats] for a in node_arrays]
    X = np.stack(node_arrays, axis=1).astype(np.float32)  # [T, N, F]

    y = []
    max_hold = cfg.max_hold_30m
    for p in cfg.pairs:
        close_col = f"{p}_Close"
        target_col = f"target_{p}_ret_12"
        if close_col in df.columns:
            rets = compute_triple_barrier_returns(df[close_col].ffill().bfill().values, cfg.k_tp, cfg.k_sl, max_hold, cfg.atr_period)
        elif target_col in df.columns:
            rets = df[target_col].fillna(0).values.astype(np.float32)
        else:
            rets = np.zeros(len(df), dtype=np.float32)
        y.append(rets)
    y = np.stack(y, axis=1).astype(np.float32)  # [T, N]

    schema = {
        "pairs": list(cfg.pairs),
        "feats_per_node": int(min_feats),
        "shared_cols": shared,
    }
    with open("titan_feature_schema.json", "w") as f:
        json.dump(schema, f)

    print("Data:", X.shape, y.shape, "date:", df.index.min(), "->", df.index.max())
    return X, y, df.index, min_feats


class SequentialForexDataset(Dataset):
    def __init__(self, X: np.ndarray, y: np.ndarray, chunk_len: int):
        self.X = torch.tensor(X, dtype=torch.float32)
        self.y = torch.tensor(y, dtype=torch.float32)
        self.chunk_len = chunk_len
        self.n = len(X) // chunk_len

    def __len__(self):
        return self.n

    def __getitem__(self, idx):
        s = idx * self.chunk_len
        e = s + self.chunk_len
        return self.X[s:e], self.y[s:e]


# -----------------------------
# Model blocks (v5 core + v6 heads)
# -----------------------------
class SelfModifyingDeltaMemory(nn.Module):
    def __init__(self, d_model=128, dropout=0.1):
        super().__init__()
        self.q = nn.Linear(d_model, d_model, bias=False)
        self.k = nn.Linear(d_model, d_model, bias=False)
        self.v = nn.Linear(d_model, d_model, bias=False)
        self.vhat = nn.Sequential(nn.Linear(d_model, d_model), nn.SiLU(), nn.Linear(d_model, d_model))
        self.eta = nn.Sequential(nn.Linear(d_model, d_model // 4), nn.SiLU(), nn.Linear(d_model // 4, 1), nn.Sigmoid())
        self.alpha = nn.Sequential(nn.Linear(d_model, d_model // 4), nn.SiLU(), nn.Linear(d_model // 4, 1), nn.Sigmoid())
        self.out = nn.Linear(d_model, d_model)
        self.norm = nn.LayerNorm(d_model)
        self.drop = nn.Dropout(dropout)
        self.register_buffer("init_M", torch.zeros(d_model, d_model))

    def forward(self, x, prev_M=None):
        # x: [B,S,N,D]
        b, s, n, d = x.shape
        xflat = x.view(b * n, s, d)
        q, k, v = self.q(xflat), self.k(xflat), self.v(xflat)
        vhat = self.vhat(v)
        eta = self.eta(xflat) * 0.1 + 0.01
        alpha = self.alpha(xflat) * 0.5 + 0.5

        M = prev_M if prev_M is not None else self.init_M.unsqueeze(0).expand(b * n, -1, -1).clone()
        outs = []
        for t in range(s):
            qt = q[:, t]
            kt = F.normalize(k[:, t], dim=-1)
            vt = vhat[:, t]
            et = eta[:, t].unsqueeze(-1)
            at = alpha[:, t].unsqueeze(-1)

            yt = torch.bmm(M, qt.unsqueeze(-1)).squeeze(-1)
            Mk = torch.bmm(M, kt.unsqueeze(-1))
            M = at * M - et * torch.bmm(Mk, kt.unsqueeze(-2)) + et * torch.bmm(vt.unsqueeze(-1), kt.unsqueeze(-2))
            outs.append(yt)

        y = torch.stack(outs, dim=1)
        y = self.norm(self.drop(self.out(y)) + xflat)
        return y.view(b, s, n, d), M


class ContinuumMemoryMLP(nn.Module):
    def __init__(self, d_model=128, chunk_sizes=(16, 64, 256), expansion=3, dropout=0.1):
        super().__init__()
        self.mlps = nn.ModuleList([
            nn.Sequential(
                nn.Linear(d_model, d_model * expansion),
                nn.SiLU(),
                nn.Dropout(dropout),
                nn.Linear(d_model * expansion, d_model),
                nn.Dropout(dropout),
            ) for _ in chunk_sizes
        ])
        self.w = nn.Parameter(torch.ones(len(chunk_sizes)))
        self.norms = nn.ModuleList([nn.LayerNorm(d_model) for _ in chunk_sizes])
        self.final = nn.LayerNorm(d_model)

    def forward(self, x):
        b, s, n, d = x.shape
        xf = x.view(b * s * n, d)
        outs = []
        for i, (mlp, norm) in enumerate(zip(self.mlps, self.norms)):
            o = mlp(xf)
            if self.training:
                o = F.dropout(o, p=max(0.0, 0.3 * (1 - i / max(len(self.mlps)-1, 1))), training=True)
            outs.append(norm(o + xf))
        ww = F.softmax(self.w, dim=0)
        y = sum(w * o for w, o in zip(ww, outs))
        return self.final(y).view(b, s, n, d)


class MarketRegimeMemory(nn.Module):
    def __init__(self, d_model=128, dropout=0.2):
        super().__init__()
        self.regime = nn.Sequential(nn.Linear(d_model * 2, d_model), nn.SiLU(), nn.Linear(d_model, 3), nn.Softmax(dim=-1))
        self.q = nn.Linear(d_model, d_model)
        self.k = nn.Linear(d_model, d_model)
        self.v = nn.Linear(d_model, d_model)
        self.gate = nn.Sequential(nn.LayerNorm(d_model * 3 + 3), nn.Linear(d_model * 3 + 3, 64), nn.ReLU(), nn.Linear(64, 1), nn.Sigmoid())
        self.norm = nn.LayerNorm(d_model)
        self.drop = nn.Dropout(dropout)

    def forward(self, x):
        state = x[:, -3:].mean(dim=1)  # [B,N,D]
        b, n, d = state.shape
        gm = state.mean(dim=1, keepdim=True)
        gs = state.std(dim=1, keepdim=True)
        regime_probs = self.regime(torch.cat([state, gm.expand(-1, n, -1)], dim=-1))

        alpha = self.gate(torch.cat([state, gm.expand(-1, n, -1), gs.expand(-1, n, -1), regime_probs], dim=-1))
        Q, K, V = self.q(state), self.k(state), self.v(state)
        attn = F.softmax(torch.matmul(Q, K.transpose(-2, -1)) / math.sqrt(d), dim=-1)
        I = torch.eye(n, device=x.device).unsqueeze(0).expand(b, -1, -1)
        mixed = alpha * I + (1 - alpha) * attn
        out = self.norm(self.drop(torch.matmul(mixed, V)) + state)
        return out, regime_probs


class RiskGovernor(nn.Module):
    def __init__(self, d_model=128):
        super().__init__()
        self.risk = nn.Sequential(nn.Linear(d_model + 2, 64), nn.SiLU(), nn.Linear(64, 1), nn.Sigmoid())

    def forward(self, trunk, direction, gate, size, uncertainty, spread_z, dd):
        # spread_z, dd: [B,N,1]
        risk_scale = self.risk(torch.cat([trunk, spread_z, dd], dim=-1))
        approved_size = size * gate * (1 - uncertainty) * risk_scale
        final_position = direction * approved_size
        return final_position, approved_size, risk_scale


class TitanNLv6(nn.Module):
    def __init__(self, feats_per_node, num_nodes=4, d_model=128, layers=3, hold_buckets=5):
        super().__init__()
        self.embed = nn.Sequential(nn.Linear(feats_per_node, d_model), nn.SiLU(), nn.LayerNorm(d_model))
        self.delta = nn.ModuleList([SelfModifyingDeltaMemory(d_model, 0.1) for _ in range(layers)])
        self.cms = ContinuumMemoryMLP(d_model, chunk_sizes=(16,64,256), expansion=3, dropout=0.1)
        self.graph = MarketRegimeMemory(d_model=d_model)
        self.trunk = nn.Sequential(nn.Linear(d_model, d_model//2), nn.GELU(), nn.Dropout(0.2))

        self.direction = nn.Sequential(nn.Linear(d_model//2, 1), nn.Tanh())
        self.trade_gate = nn.Sequential(nn.Linear(d_model//2, 1), nn.Sigmoid())
        self.size = nn.Sequential(nn.Linear(d_model//2, 1), nn.Sigmoid())
        self.stop = nn.Sequential(nn.Linear(d_model//2, 1), nn.Softplus())
        self.target = nn.Sequential(nn.Linear(d_model//2, 1), nn.Softplus())
        self.hold = nn.Linear(d_model//2, hold_buckets)
        self.uncertainty = nn.Sequential(nn.Linear(d_model//2, 1), nn.Sigmoid())
        self.adapt = nn.Sequential(nn.Linear(d_model//2, 3), nn.Softmax(dim=-1))

        self.risk_governor = RiskGovernor(d_model=d_model//2)

    def forward(self, x, prev_states=None, spread_z=None, drawdown=None):
        # x: [B,S,N,F]
        b, s, n, _ = x.shape
        x = self.embed(x)

        states = []
        for i, layer in enumerate(self.delta):
            p = prev_states[i] if prev_states is not None else None
            x, m = layer(x, p)
            states.append(m)

        x = self.cms(x)
        g, regime_probs = self.graph(x)  # [B,N,D]
        trunk = self.trunk(g)

        direction = self.direction(trunk)
        gate = self.trade_gate(trunk)
        size = self.size(trunk)
        stop_mult = self.stop(trunk) + 0.1
        target_mult = self.target(trunk) + 0.2
        hold_probs = F.softmax(self.hold(trunk), dim=-1)
        uncertainty = self.uncertainty(trunk)
        adapt_mode_probs = self.adapt(trunk)

        if spread_z is None:
            spread_z = torch.zeros(b, n, 1, device=x.device)
        if drawdown is None:
            drawdown = torch.zeros(b, n, 1, device=x.device)

        final_pos, final_size, risk_scale = self.risk_governor(
            trunk, direction, gate, size, uncertainty, spread_z, drawdown
        )

        return {
            "direction": direction,
            "trade_gate": gate,
            "size": size,
            "stop_mult": stop_mult,
            "target_mult": target_mult,
            "hold_horizon": hold_probs,
            "uncertainty": uncertainty,
            "regime_probs": regime_probs,
            "adapt_mode_probs": adapt_mode_probs,
            "position": final_pos,
            "final_size": final_size,
            "risk_scale": risk_scale,
            "states": states,
        }


# -----------------------------
# Loss + metrics
# -----------------------------
class RealPnLV6Loss(nn.Module):
    def __init__(self, cfg: CFG):
        super().__init__()
        self.cfg = cfg
        self.spread = cfg.spread_bps * 1e-4

    def forward(self, out: Dict[str, torch.Tensor], targets: torch.Tensor, prev_pos: Optional[torch.Tensor] = None):
        # targets: [B,S,N]
        pos = out["position"].squeeze(-1)           # [B,N]
        r_net = targets.sum(dim=1)                  # [B,N]

        rv = targets.std(dim=1).clamp(min=1e-8)
        vol_scale = (self.cfg.target_vol / rv).clamp(0.1, 3.0)
        pos = pos * vol_scale
        pnl = pos * r_net

        if prev_pos is None:
            turnover = pos.abs().mean()
        else:
            turnover = (pos - prev_pos).abs().mean()
        tc = self.cfg.lambda_tc * turnover * self.spread

        bar_pnl = (pos.unsqueeze(1).expand_as(targets) * targets).reshape(-1)
        k = max(1, int(self.cfg.cvar_q * bar_pnl.numel()))
        cvar = -torch.topk(bar_pnl, k=k, largest=False).values.mean()
        cvar_pen = self.cfg.lambda_cvar * cvar

        l2 = self.cfg.lambda_l2 * (out["direction"].squeeze(-1) ** 2).mean()

        abstain_pen = (out["trade_gate"].mean() * out["uncertainty"].mean()) * 0.01
        return -pnl.mean() + tc + cvar_pen + l2 + abstain_pen


def sharpe(sig: np.ndarray, ret: np.ndarray, bars_per_year=11088):
    pnl = sig * ret
    mu, sd = pnl.mean(), pnl.std()
    if sd < 1e-8:
        return 0.0
    return float((mu / sd) * np.sqrt(bars_per_year))


# -----------------------------
# Train / eval
# -----------------------------
def run_epoch(model, loader, criterion, optimizer=None):
    train = optimizer is not None
    model.train() if train else model.eval()

    total = 0.0
    prev_states, prev_pos = None, None
    all_sig, all_ret = [], []

    for xb, yb in loader:
        xb, yb = xb.to(DEVICE), yb.to(DEVICE)
        if train:
            xb = torch.clamp(xb + torch.randn_like(xb) * CFG.noise_std, -10, 10)
            optimizer.zero_grad(set_to_none=True)
        else:
            xb = torch.clamp(xb, -10, 10)

        out = model(xb, prev_states=prev_states)
        loss = criterion(out, yb, prev_pos=prev_pos)

        if train:
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()

        prev_states = [s.detach() for s in out["states"]]
        prev_pos = out["position"].squeeze(-1).detach()
        total += float(loss.item())

        all_sig.append(out["position"].squeeze(-1).detach().cpu().numpy())
        all_ret.append(yb.sum(dim=1).detach().cpu().numpy())

    sig = np.concatenate(all_sig, axis=0).reshape(-1)
    ret = np.concatenate(all_ret, axis=0).reshape(-1)
    return total / max(1, len(loader)), sharpe(sig, ret)


# -----------------------------
# Main
# -----------------------------
X, y, dates, feats = load_dataset(CFG)

train_mask = (dates >= CFG.train_start) & (dates <= CFG.train_end)
val_mask = (dates >= CFG.val_start) & (dates <= CFG.val_end)
train_idx = np.where(train_mask)[0]
val_idx = np.where(val_mask)[0]

if len(train_idx) < CFG.chunk_len * 4:
    raise ValueError(f"Train range too short: {len(train_idx)} bars for chunk_len={CFG.chunk_len}")
if len(val_idx) < CFG.chunk_len:
    raise ValueError(f"Val range too short: {len(val_idx)} bars for chunk_len={CFG.chunk_len}")

scaler = RobustScaler().fit(X[train_idx].reshape(-1, feats))
X_scaled = scaler.transform(X.reshape(-1, feats)).reshape(X.shape)
X_scaled = np.nan_to_num(X_scaled, nan=0.0, posinf=5.0, neginf=-5.0).astype(np.float32)
with open("titan_scaler.pkl", "wb") as f:
    pickle.dump(scaler, f)

train_ds = SequentialForexDataset(X_scaled[train_idx], y[train_idx], CFG.chunk_len)
val_ds = SequentialForexDataset(X_scaled[val_idx], y[val_idx], CFG.chunk_len)
train_loader = DataLoader(train_ds, batch_size=CFG.batch_size, shuffle=False, drop_last=True)
val_loader = DataLoader(val_ds, batch_size=CFG.batch_size, shuffle=False)

model = TitanNLv6(feats_per_node=feats, num_nodes=len(CFG.pairs), d_model=CFG.d_model, layers=CFG.layers, hold_buckets=len(CFG.hold_buckets)).to(DEVICE)
criterion = RealPnLV6Loss(CFG)
optimizer = optim.AdamW(model.parameters(), lr=CFG.lr, weight_decay=1e-4)

best = float("inf")
pat = 0
for ep in range(1, CFG.epochs + 1):
    tr_loss, tr_sh = run_epoch(model, train_loader, criterion, optimizer)
    with torch.no_grad():
        va_loss, va_sh = run_epoch(model, val_loader, criterion, optimizer=None)

    print(f"Epoch {ep:02d}/{CFG.epochs} | train_loss={tr_loss:.6f} val_loss={va_loss:.6f} | train_sh={tr_sh:.3f} val_sh={va_sh:.3f}")

    if va_loss < best:
        best = va_loss
        pat = 0
        torch.save(model.state_dict(), "Best_TITAN_NL_v6.pth")
    else:
        pat += 1
        if pat >= CFG.patience:
            print("Early stopping.")
            break

print("Done. Saved: Best_TITAN_NL_v6.pth, titan_scaler.pkl, titan_feature_schema.json")
