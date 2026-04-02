"""
TITAN-NL v6 — single-cell Kaggle training script.
Copy/paste this file contents into one Kaggle cell and run.
"""

# =========================
# TITAN-NL v6 Kaggle Cell
# =========================
import os
import math
import json
import pickle
import numpy as np
import pandas as pd
import torch
import torch.nn as nn
import torch.nn.functional as F
import torch.optim as optim
from torch.utils.data import Dataset, DataLoader
from sklearn.preprocessing import RobustScaler
from dataclasses import dataclass
from typing import List, Optional, Dict, Tuple

# -------- CONFIG --------
PAIRS = ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD"]
NUM_NODES = len(PAIRS)
CHUNK_LEN = 16
D_MODEL = 128
EPOCHS = 20
PATIENCE = 6
LR = 2e-4
ONLINE_LR = 5e-6
NOISE_STD = 0.01

TRAIN_START = "2025-02-26"
TRAIN_END = "2025-10-31"
VAL_START = "2025-11-01"
VAL_END = "2025-12-31"
CALIB_START = "2026-01-01"
CALIB_END = "2026-01-31"
BACKTEST_START = "2026-02-01"
BACKTEST_END = "2026-02-25"

SPREAD_BPS = 1.0
LAMBDA_TC = 0.5
LAMBDA_CVAR = 0.1
TARGET_VOL = 0.001
CVAR_Q = 0.10
LAMBDA_L2 = 0.02

ATR_PERIOD = 14
K_TP = 2.0
K_SL = 1.5
MAX_HOLD = 6  # 30m bars

HOLD_BUCKETS = [1, 2, 4, 6, 12]
ADAPT_MODES = ["memory_only", "tiny_weight_update", "freeze"]
DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")

# -------- DATA --------
def _find_dataset() -> str:
    candidates = [
        "Titan30M_Dataset.csv",
        "Titan15M_Dataset.csv",
        "TitanForexDataset.csv",
        "Titan_Dataset.csv",
        "/kaggle/input/datasets/zackhlongwane/new30m/Titan30M_Dataset.csv",
        "/kaggle/input/titanfx/Titan30M_Dataset.csv",
        "/kaggle/input/titanfx/Titan15M_Dataset.csv",
        "/kaggle/input/titanfx/TitanForexDataset.csv",
    ]
    for p in candidates:
        if os.path.exists(p):
            return p
    for base in [".", "/kaggle/input"]:
        if os.path.exists(base):
            for root, _, files in os.walk(base):
                for f in files:
                    if f.endswith(".csv") and "Titan" in f:
                        return os.path.join(root, f)
    raise FileNotFoundError("No Titan dataset CSV found.")


def compute_triple_barrier_returns(close: np.ndarray) -> np.ndarray:
    t = len(close)
    if t < ATR_PERIOD + 2:
        return np.zeros(t, dtype=np.float32)

    px = close.astype(np.float64)
    tr = np.abs(np.diff(px, prepend=px[0]))
    atr = pd.Series(tr).ewm(span=ATR_PERIOD, adjust=False).mean().values
    atr = np.maximum(atr, 1e-8)

    out = np.zeros(t, dtype=np.float32)
    for i in range(t - 1):
        entry = px[i]
        tp = entry + K_TP * atr[i]
        sl = entry - K_SL * atr[i]
        end_i = min(i + MAX_HOLD, t - 1)

        realized = (px[end_i] - entry) / (entry + 1e-12)
        for j in range(i + 1, end_i + 1):
            if px[j] >= tp:
                realized = K_TP * atr[i] / (entry + 1e-12)
                break
            if px[j] <= sl:
                realized = -K_SL * atr[i] / (entry + 1e-12)
                break
        out[i] = realized
    return out


def _make_event_ctx(index: pd.DatetimeIndex, n_nodes: int) -> np.ndarray:
    h = index.hour.values
    d = index.dayofweek.values

    asia = ((h >= 0) & (h <= 7)).astype(np.float32)
    london = ((h >= 8) & (h <= 15)).astype(np.float32)
    ny = ((h >= 13) & (h <= 21)).astype(np.float32)
    overlap = (london * ny).astype(np.float32)
    rollover = ((h == 21) | (h == 22)).astype(np.float32)
    dow_sin = np.sin(2 * np.pi * d / 7.0).astype(np.float32)
    dow_cos = np.cos(2 * np.pi * d / 7.0).astype(np.float32)
    hod_sin = np.sin(2 * np.pi * h / 24.0).astype(np.float32)
    hod_cos = np.cos(2 * np.pi * h / 24.0).astype(np.float32)

    # event placeholders (0 if you do not have event feed yet)
    event_in_next_k = np.zeros_like(asia)
    event_importance = np.zeros_like(asia)
    risk_on_off_bucket = np.zeros_like(asia)
    geopolitical_bucket = np.zeros_like(asia)

    ctx = np.stack([
        hod_sin, hod_cos, dow_sin, dow_cos,
        asia, london, ny, overlap, rollover,
        event_in_next_k, event_importance,
        risk_on_off_bucket, geopolitical_bucket,
    ], axis=-1)
    return np.repeat(ctx[:, None, :], n_nodes, axis=1).astype(np.float32)


def load_titan_dataset(path: Optional[str] = None):
    path = path or _find_dataset()
    print(f"Loading dataset: {path}")
    df = pd.read_csv(path, index_col=0, parse_dates=True).sort_index().fillna(0)

    numeric_cols = set(df.select_dtypes(include=[np.number]).columns)
    shared_cols = [
        c for c in df.columns
        if c in numeric_cols
        and not any(c.startswith(p) for p in PAIRS)
        and not c.startswith("target_")
    ]

    node_arrays, future_rets = [], []
    for p in PAIRS:
        pcols = [
            c for c in df.columns
            if c in numeric_cols and c.startswith(p) and not c.startswith("target_")
        ]
        if not pcols:
            pcols = [
                c for c in df.columns
                if c in numeric_cols and c.startswith(p.lower()) and not c.startswith("target_")
            ]
        node_arrays.append(df[pcols + shared_cols].values)

        close_col = f"{p}_Close"
        target_col = f"target_{p}_ret_12"
        if close_col in df.columns:
            r = compute_triple_barrier_returns(df[close_col].ffill().bfill().values)
        elif target_col in df.columns:
            r = df[target_col].values.astype(np.float32)
        else:
            r = np.zeros(len(df), dtype=np.float32)
        future_rets.append(r)

    min_feats = min(a.shape[1] for a in node_arrays)
    node_arrays = [a[:, :min_feats] for a in node_arrays]

    master = np.stack(node_arrays, axis=1).astype(np.float32)      # [T,N,F]
    future = np.stack(future_rets, axis=1).astype(np.float32)      # [T,N]
    event_ctx = _make_event_ctx(df.index, NUM_NODES)               # [T,N,E]
    return master, future, event_ctx, min_feats, df.index


class SequentialForexDataset(Dataset):
    def __init__(self, x: np.ndarray, r: np.ndarray, e: np.ndarray, chunk_len: int):
        self.x = torch.tensor(x, dtype=torch.float32)
        self.r = torch.tensor(r, dtype=torch.float32)
        self.e = torch.tensor(e, dtype=torch.float32)
        self.chunk_len = chunk_len
        self.n = len(x) // chunk_len

    def __len__(self):
        return self.n

    def __getitem__(self, idx):
        s = idx * self.chunk_len
        t = s + self.chunk_len
        return self.x[s:t], self.r[s:t], self.e[s:t]

# -------- MODEL --------
class SelfModifyingDeltaMemory(nn.Module):
    def __init__(self, d_model: int):
        super().__init__()
        self.q = nn.Linear(d_model, d_model, bias=False)
        self.k = nn.Linear(d_model, d_model, bias=False)
        self.v = nn.Linear(d_model, d_model, bias=False)
        self.val = nn.Sequential(nn.Linear(d_model, d_model), nn.SiLU(), nn.Linear(d_model, d_model))
        self.eta = nn.Sequential(nn.Linear(d_model, d_model//4), nn.SiLU(), nn.Linear(d_model//4, 1), nn.Sigmoid())
        self.alpha = nn.Sequential(nn.Linear(d_model, d_model//4), nn.SiLU(), nn.Linear(d_model//4, 1), nn.Sigmoid())
        self.out = nn.Linear(d_model, d_model)
        self.norm = nn.LayerNorm(d_model)
        self.register_buffer("init_memory", torch.zeros(d_model, d_model))

    def forward(self, x: torch.Tensor, prev_m: Optional[torch.Tensor] = None):
        b, s, n, d = x.shape
        xf = x.view(b*n, s, d)
        q = self.q(xf)
        k = self.k(xf)
        v = self.val(self.v(xf))
        eta = self.eta(xf) * 0.1 + 0.01
        alpha = self.alpha(xf) * 0.5 + 0.5

        m = prev_m if prev_m is not None else self.init_memory.unsqueeze(0).expand(b*n, -1, -1).clone()
        outs = []
        for t in range(s):
            qt = q[:, t, :]
            kt = F.normalize(k[:, t, :], dim=-1)
            vt = v[:, t, :]
            et = eta[:, t, :].unsqueeze(-1)
            at = alpha[:, t, :].unsqueeze(-1)

            ot = torch.bmm(m, qt.unsqueeze(-1)).squeeze(-1)
            mk = torch.bmm(m, kt.unsqueeze(-1))
            m = at*m - et*torch.bmm(mk, kt.unsqueeze(-2)) + et*torch.bmm(vt.unsqueeze(-1), kt.unsqueeze(-2))
            outs.append(ot)

        y = torch.stack(outs, dim=1)
        y = self.norm(self.out(y) + xf)
        return y.view(b, s, n, d), m


class ContinuumMemoryMLP(nn.Module):
    def __init__(self, d_model: int, scales=(16, 64, 256)):
        super().__init__()
        self.mlps = nn.ModuleList([
            nn.Sequential(
                nn.Linear(d_model, d_model * 3), nn.SiLU(), nn.Dropout(0.1),
                nn.Linear(d_model * 3, d_model), nn.Dropout(0.1)
            ) for _ in scales
        ])
        self.w = nn.Parameter(torch.ones(len(scales)))
        self.norm = nn.LayerNorm(d_model)

    def forward(self, x: torch.Tensor):
        b, s, n, d = x.shape
        xf = x.view(b*s*n, d)
        ys = [m(xf) + xf for m in self.mlps]
        w = F.softmax(self.w, dim=0)
        y = sum(wi*yi for wi, yi in zip(w, ys))
        return self.norm(y).view(b, s, n, d)


class MarketRegimeMemory(nn.Module):
    def __init__(self, d_model: int):
        super().__init__()
        self.q = nn.Linear(d_model, d_model)
        self.k = nn.Linear(d_model, d_model)
        self.v = nn.Linear(d_model, d_model)
        self.regime = nn.Sequential(nn.Linear(d_model*2, d_model), nn.SiLU(), nn.Linear(d_model, 6), nn.Softmax(dim=-1))
        self.norm = nn.LayerNorm(d_model)

    def forward(self, x: torch.Tensor):
        s = x[:, -3:, :, :].mean(dim=1)  # [B,N,D]
        q, k, v = self.q(s), self.k(s), self.v(s)
        att = F.softmax(torch.matmul(q, k.transpose(-2, -1))/math.sqrt(s.size(-1)), dim=-1)
        out = self.norm(torch.matmul(att, v) + s)

        g = s.mean(dim=1, keepdim=True).expand_as(s)
        regime_probs = self.regime(torch.cat([s, g], dim=-1))
        return out, att, regime_probs


@dataclass
class LiveStats:
    drawdown: float = 0.0
    spread_percentile: float = 0.5
    regime_instability: float = 0.0


class RiskGovernor(nn.Module):
    def __init__(self, d_model: int):
        super().__init__()
        self.scale_head = nn.Sequential(nn.Linear(d_model + 3, 1), nn.Sigmoid())

    def forward(self, trunk, direction, gate, size, uncertainty, adapt_probs, live_stats: Optional[LiveStats] = None):
        b, n, d = trunk.shape
        if live_stats is None:
            ls = torch.zeros(b, n, 3, device=trunk.device)
        else:
            ls = torch.tensor([live_stats.drawdown, live_stats.spread_percentile, live_stats.regime_instability],
                              device=trunk.device, dtype=trunk.dtype).view(1, 1, 3).expand(b, n, 3)

        risk_scale = self.scale_head(torch.cat([trunk, ls], dim=-1))
        if live_stats is not None and (live_stats.drawdown > 0.08 or live_stats.spread_percentile > 0.95):
            risk_scale = torch.zeros_like(risk_scale)

        final_size = gate * size * risk_scale * (1.0 - uncertainty).clamp(0.0, 1.0)
        final_pos = direction * final_size

        final_adapt = adapt_probs
        if live_stats is not None and live_stats.regime_instability > 0.75:
            freeze = torch.zeros_like(adapt_probs)
            freeze[..., 2] = 1.0
            final_adapt = freeze
        return final_pos, final_size, risk_scale, final_adapt


class TitanNLv6(nn.Module):
    def __init__(self, feats_per_node: int, event_dim: int, d_model: int = D_MODEL, hold_bins: int = len(HOLD_BUCKETS)):
        super().__init__()
        self.embed = nn.Sequential(nn.Linear(feats_per_node, d_model), nn.SiLU(), nn.LayerNorm(d_model))
        self.event = nn.Sequential(nn.Linear(event_dim, d_model), nn.SiLU(), nn.LayerNorm(d_model))

        self.delta = nn.ModuleList([SelfModifyingDeltaMemory(d_model) for _ in range(2)])
        self.cms = ContinuumMemoryMLP(d_model)
        self.regime = MarketRegimeMemory(d_model)

        self.trunk = nn.Sequential(nn.Linear(d_model*2, d_model), nn.GELU(), nn.Dropout(0.2), nn.Linear(d_model, d_model), nn.GELU())

        self.direction_head = nn.Sequential(nn.Linear(d_model, 1), nn.Tanh())
        self.trade_gate_head = nn.Sequential(nn.Linear(d_model, 1), nn.Sigmoid())
        self.size_head = nn.Sequential(nn.Linear(d_model, 1), nn.Sigmoid())
        self.stop_head = nn.Sequential(nn.Linear(d_model, 1), nn.Softplus())
        self.target_head = nn.Sequential(nn.Linear(d_model, 1), nn.Softplus())
        self.hold_head = nn.Linear(d_model, hold_bins)
        self.uncertainty_head = nn.Sequential(nn.Linear(d_model, 1), nn.Sigmoid())
        self.adapt_head = nn.Sequential(nn.Linear(d_model, len(ADAPT_MODES)), nn.Softmax(dim=-1))

        self.risk_governor = RiskGovernor(d_model)

    def forward(self, x, event_ctx=None, prev_states=None, live_stats=None):
        b, s, n, _ = x.shape
        z = self.embed(x)

        states = []
        for i, layer in enumerate(self.delta):
            pm = prev_states[i] if prev_states is not None else None
            z, nm = layer(z, pm)
            states.append(nm)

        z = self.cms(z)
        graph, attn, regime_probs = self.regime(z)

        if event_ctx is None:
            event_ctx = torch.zeros(b, n, 13, device=x.device)
        e = self.event(event_ctx)
        trunk = self.trunk(torch.cat([graph, e], dim=-1))

        direction = self.direction_head(trunk)
        trade_gate = self.trade_gate_head(trunk)
        size = self.size_head(trunk)
        stop_mult = self.stop_head(trunk) + 0.1
        target_mult = self.target_head(trunk) + 0.2
        hold_horizon = F.softmax(self.hold_head(trunk), dim=-1)
        uncertainty = self.uncertainty_head(trunk)
        adapt_mode_probs = self.adapt_head(trunk)

        final_pos, final_size, risk_scale, final_adapt = self.risk_governor(
            trunk, direction, trade_gate, size, uncertainty, adapt_mode_probs, live_stats
        )

        return {
            "direction": direction,
            "trade_gate": trade_gate,
            "size": size,
            "stop_mult": stop_mult,
            "target_mult": target_mult,
            "hold_horizon": hold_horizon,
            "uncertainty": uncertainty,
            "regime_probs": regime_probs,
            "adapt_mode_probs": adapt_mode_probs,
            "final_policy": {
                "final_position": final_pos,
                "final_size": final_size,
                "risk_scale": risk_scale,
                "final_adapt_mode_probs": final_adapt,
            },
            "states": states,
            "attn": attn,
        }

# -------- LOSS --------
class TitanV6Loss(nn.Module):
    def __init__(self):
        super().__init__()

    def forward(self, out: Dict[str, torch.Tensor], ret: torch.Tensor, prev_pos: Optional[torch.Tensor] = None):
        pos = out["final_policy"]["final_position"].squeeze(-1)  # [B,N]
        r_net = ret.sum(dim=1)                                     # [B,N]

        rv = ret.std(dim=1).clamp(min=1e-8)
        vol_scale = (TARGET_VOL / rv).clamp(0.1, 3.0)
        pos_scaled = pos * vol_scale

        pnl = pos_scaled * r_net

        if prev_pos is None:
            turnover = pos.abs().mean()
        else:
            turnover = (pos - prev_pos).abs().mean()
        tc = LAMBDA_TC * turnover * (SPREAD_BPS * 1e-4)

        bar_pnl = (pos_scaled.unsqueeze(1).expand_as(ret) * ret).reshape(-1)
        k = max(1, int(CVAR_Q * bar_pnl.numel()))
        worst = torch.topk(bar_pnl, k, largest=False).values
        cvar = -worst.mean()

        # aux losses
        gate = out["trade_gate"].squeeze(-1)
        uncertainty = out["uncertainty"].squeeze(-1)
        no_trade_target = (ret.abs().mean(dim=1) < (SPREAD_BPS * 1e-4) * 2).float()
        gate_loss = F.binary_cross_entropy(gate, 1.0 - no_trade_target)

        l2_dir = (out["direction"].squeeze(-1) ** 2).mean()
        adapt_entropy = -(out["adapt_mode_probs"] * (out["adapt_mode_probs"] + 1e-8).log()).sum(dim=-1).mean()
        uncertainty_pen = ((uncertainty * gate) ** 2).mean()

        loss = -pnl.mean() + tc + (LAMBDA_CVAR * cvar) + (LAMBDA_L2 * l2_dir)
        loss = loss + 0.05 * gate_loss + 0.01 * uncertainty_pen - 0.005 * adapt_entropy
        return loss, pnl.mean().detach()


def calculate_sharpe(sig: np.ndarray, ret: np.ndarray, bpy: int = 11088):
    pnl = sig * ret
    mu, sd = pnl.mean(), pnl.std()
    return 0.0 if sd < 1e-8 else (mu / sd) * np.sqrt(bpy)


# -------- TRAIN / EVAL --------
def run_epoch(model, loader, optimizer, criterion, train=True, init_states=None):
    if train:
        model.train()
    else:
        model.eval()

    total_loss = 0.0
    total_pnl = 0.0
    prev_states = init_states
    prev_pos = None
    all_sig, all_ret = [], []

    for x, r, e in loader:
        x = x.to(DEVICE)
        r = r.to(DEVICE)
        e = e.to(DEVICE)

        if train:
            x = torch.clamp(x + torch.randn_like(x) * NOISE_STD, -10, 10)
            optimizer.zero_grad()
            out = model(x, event_ctx=e[:, -1], prev_states=prev_states)
            loss, mean_pnl = criterion(out, r, prev_pos)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()
        else:
            with torch.no_grad():
                x = torch.clamp(x, -10, 10)
                out = model(x, event_ctx=e[:, -1], prev_states=prev_states)
                loss, mean_pnl = criterion(out, r, prev_pos)

        prev_states = [s.detach() for s in out["states"]]
        prev_pos = out["final_policy"]["final_position"].squeeze(-1).detach()

        total_loss += loss.item()
        total_pnl += mean_pnl.item()

        with torch.no_grad():
            sig = out["final_policy"]["final_position"].squeeze(-1).cpu().numpy().reshape(-1, NUM_NODES)
            rr = r.sum(dim=1).cpu().numpy().reshape(-1, NUM_NODES)
            all_sig.append(sig)
            all_ret.append(rr)

    sig_arr = np.concatenate(all_sig, axis=0) if all_sig else np.zeros((0, NUM_NODES))
    ret_arr = np.concatenate(all_ret, axis=0) if all_ret else np.zeros((0, NUM_NODES))
    sharpe = calculate_sharpe(sig_arr.flatten(), ret_arr.flatten()) if len(sig_arr) else 0.0
    return total_loss / max(len(loader), 1), total_pnl / max(len(loader), 1), sharpe, prev_states


# -------- MAIN --------
print("TITAN-NL v6 single-cell trainer")
print("Device:", DEVICE)

master, future, event_ctx, feats_per_node, dates = load_titan_dataset()

train_mask = (dates >= TRAIN_START) & (dates <= TRAIN_END)
val_mask = (dates >= VAL_START) & (dates <= VAL_END)
calib_mask = (dates >= CALIB_START) & (dates <= CALIB_END)
backtest_mask = (dates >= BACKTEST_START) & (dates <= BACKTEST_END)

train_idx = np.where(train_mask)[0]
val_idx = np.where(val_mask)[0]
calib_idx = np.where(calib_mask)[0]
backtest_idx = np.where(backtest_mask)[0]

if len(train_idx) < CHUNK_LEN or len(val_idx) < CHUNK_LEN:
    raise ValueError("Not enough rows in train/val splits for CHUNK_LEN.")

n, nodes, feats = master.shape
scaler = RobustScaler().fit(master[train_idx].reshape(-1, feats))
scaled = scaler.transform(master.reshape(-1, feats)).reshape(n, nodes, feats).astype(np.float32)
scaled = np.nan_to_num(scaled, nan=0.0, posinf=5.0, neginf=-5.0)

train_ds = SequentialForexDataset(scaled[train_idx], future[train_idx], event_ctx[train_idx], CHUNK_LEN)
val_ds = SequentialForexDataset(scaled[val_idx], future[val_idx], event_ctx[val_idx], CHUNK_LEN)
calib_ds = SequentialForexDataset(scaled[calib_idx], future[calib_idx], event_ctx[calib_idx], CHUNK_LEN)
back_ds = SequentialForexDataset(scaled[backtest_idx], future[backtest_idx], event_ctx[backtest_idx], CHUNK_LEN)

train_loader = DataLoader(train_ds, batch_size=1, shuffle=False, drop_last=True)
val_loader = DataLoader(val_ds, batch_size=1, shuffle=False)
calib_loader = DataLoader(calib_ds, batch_size=1, shuffle=False)
back_loader = DataLoader(back_ds, batch_size=1, shuffle=False)

model = TitanNLv6(feats_per_node=feats_per_node, event_dim=13, d_model=D_MODEL).to(DEVICE)
criterion = TitanV6Loss()
optimizer = optim.AdamW(model.parameters(), lr=LR, weight_decay=1e-3)

best_loss = float("inf")
pat = 0
for ep in range(EPOCHS):
    tr_loss, tr_pnl, tr_sh, _ = run_epoch(model, train_loader, optimizer, criterion, train=True)
    va_loss, va_pnl, va_sh, _ = run_epoch(model, val_loader, optimizer, criterion, train=False)

    print(f"Epoch {ep+1:02d}/{EPOCHS} | train_loss={tr_loss:.5f} val_loss={va_loss:.5f} | train_sh={tr_sh:.3f} val_sh={va_sh:.3f}")

    if va_loss < best_loss:
        best_loss = va_loss
        pat = 0
        torch.save(model.state_dict(), "Best_TITAN_NL_V6.pth")
    else:
        pat += 1
        if pat >= PATIENCE:
            print("Early stop")
            break

model.load_state_dict(torch.load("Best_TITAN_NL_V6.pth", map_location=DEVICE))

# quick calibration phase (tiny head updates)
calib_opt = optim.AdamW(model.parameters(), lr=ONLINE_LR * 10, weight_decay=1e-4)
_, _, _, states = run_epoch(model, calib_loader, calib_opt, criterion, train=True)

# backtest
bt_loss, bt_pnl, bt_sh, _ = run_epoch(model, back_loader, calib_opt, criterion, train=False, init_states=states)
print(f"Backtest | loss={bt_loss:.5f} pnl={bt_pnl:.6f} sharpe={bt_sh:.3f}")

# save artifacts for live
torch.save(model.state_dict(), "TitanNLv6_complete.pth")
with open("titan_scaler.pkl", "wb") as f:
    pickle.dump(scaler, f)
with open("titan_v6_meta.json", "w") as f:
    json.dump({
        "pairs": PAIRS,
        "chunk_len": CHUNK_LEN,
        "d_model": D_MODEL,
        "hold_buckets": HOLD_BUCKETS,
        "adapt_modes": ADAPT_MODES,
        "feats_per_node": int(feats_per_node),
    }, f, indent=2)

print("Done. Files: Best_TITAN_NL_V6.pth, TitanNLv6_complete.pth, titan_scaler.pkl, titan_v6_meta.json")
