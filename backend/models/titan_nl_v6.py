"""TITAN-NL v6 trader architecture skeleton.

This module provides a production-oriented scaffold that upgrades a directional
signal model into a policy model suitable for execution and risk-gated online
adaptation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import torch
import torch.nn as nn
import torch.nn.functional as F


ADAPT_MODES: Tuple[str, str, str] = (
    "memory_only",
    "tiny_weight_update",
    "freeze",
)


@dataclass
class LiveStats:
    """Runtime telemetry injected into the risk governor."""

    drawdown: float = 0.0
    spread_percentile: float = 0.5
    regime_instability: float = 0.0


class EventSessionEncoder(nn.Module):
    """Encodes structured session/event context into model dimension."""

    def __init__(self, in_dim: int, out_dim: int, dropout: float = 0.1):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(in_dim, out_dim),
            nn.SiLU(),
            nn.Dropout(dropout),
            nn.Linear(out_dim, out_dim),
        )

    def forward(self, event_ctx: torch.Tensor) -> torch.Tensor:
        return self.net(event_ctx)


class RiskGovernor(nn.Module):
    """Risk layer that can veto, shrink, or pass through proposed policy."""

    def __init__(self, d_model: int):
        super().__init__()
        self.scale_head = nn.Sequential(nn.Linear(d_model, 1), nn.Sigmoid())

    def forward(
        self,
        trunk: torch.Tensor,
        direction: torch.Tensor,
        trade_gate: torch.Tensor,
        size: torch.Tensor,
        stop_mult: torch.Tensor,
        target_mult: torch.Tensor,
        hold_horizon: torch.Tensor,
        uncertainty: torch.Tensor,
        adapt_mode_probs: torch.Tensor,
        live_stats: Optional[LiveStats] = None,
    ) -> Dict[str, torch.Tensor]:
        risk_scale = self.scale_head(trunk)

        if live_stats is not None:
            if live_stats.drawdown > 0.08 or live_stats.spread_percentile > 0.95:
                risk_scale = risk_scale * 0.0

        uncertainty_scale = (1.0 - uncertainty).clamp(0.0, 1.0)
        approved_size = size * trade_gate * risk_scale * uncertainty_scale
        final_position = direction * approved_size

        final_adapt_mode_probs = adapt_mode_probs
        if live_stats is not None and live_stats.regime_instability > 0.75:
            freeze_mask = torch.zeros_like(final_adapt_mode_probs)
            freeze_mask[..., 2] = 1.0
            final_adapt_mode_probs = freeze_mask

        return {
            "final_position": final_position,
            "final_size": approved_size,
            "risk_scale": risk_scale,
            "stop_mult": stop_mult,
            "target_mult": target_mult,
            "hold_horizon": hold_horizon,
            "final_adapt_mode_probs": final_adapt_mode_probs,
        }


class TitanNLv6(nn.Module):
    """Trader-grade TITAN interface that outputs a full policy tuple.

    Notes:
    - This is an upgrade scaffold intended to wrap/replace the existing v5 trunk.
    - Memory/CMS/regime components are represented with placeholders here and
      should be swapped with production implementations.
    """

    def __init__(
        self,
        feats_per_node: int,
        d_model: int = 128,
        num_nodes: int = 4,
        event_ctx_dim: int = 24,
        hold_buckets: int = 5,
    ):
        super().__init__()
        self.num_nodes = num_nodes
        self.hold_buckets = hold_buckets

        self.feature_encoder = nn.Sequential(
            nn.Linear(feats_per_node, d_model),
            nn.SiLU(),
            nn.LayerNorm(d_model),
        )

        # Placeholders for v5 core blocks.
        self.delta_layers = nn.ModuleList([nn.Identity(), nn.Identity()])
        self.cms = nn.Identity()
        self.regime_graph = nn.Sequential(nn.Linear(d_model, d_model), nn.SiLU())

        self.event_encoder = EventSessionEncoder(event_ctx_dim, d_model)
        self.shared_trunk = nn.Sequential(
            nn.Linear(d_model * 2, d_model),
            nn.GELU(),
            nn.Dropout(0.1),
            nn.Linear(d_model, d_model),
            nn.GELU(),
        )

        # Policy heads
        self.direction_head = nn.Sequential(nn.Linear(d_model, 1), nn.Tanh())
        self.trade_gate_head = nn.Sequential(nn.Linear(d_model, 1), nn.Sigmoid())
        self.size_head = nn.Sequential(nn.Linear(d_model, 1), nn.Sigmoid())
        self.stop_head = nn.Sequential(nn.Linear(d_model, 1), nn.Softplus())
        self.target_head = nn.Sequential(nn.Linear(d_model, 1), nn.Softplus())
        self.hold_head = nn.Linear(d_model, hold_buckets)
        self.uncertainty_head = nn.Sequential(nn.Linear(d_model, 1), nn.Sigmoid())
        self.regime_transition_head = nn.Sequential(nn.Linear(d_model, 6), nn.Softmax(dim=-1))
        self.adapt_policy_head = nn.Sequential(nn.Linear(d_model, len(ADAPT_MODES)), nn.Softmax(dim=-1))

        self.risk_governor = RiskGovernor(d_model=d_model)

    def forward(
        self,
        x: torch.Tensor,
        event_ctx: Optional[torch.Tensor] = None,
        prev_states: Optional[List[torch.Tensor]] = None,
        live_stats: Optional[LiveStats] = None,
    ) -> Dict[str, torch.Tensor | List[torch.Tensor]]:
        """Forward pass.

        Args:
            x: [B, S, N, F]
            event_ctx: [B, N, E] structured event/session context
            prev_states: optional state carryover (reserved for v5 memory blocks)
            live_stats: runtime risk telemetry
        """
        del prev_states  # reserved for concrete memory implementation

        b, s, n, _ = x.shape
        encoded = self.feature_encoder(x)

        # Temporal aggregation placeholder. Replace with stateful stack in production.
        core = encoded.mean(dim=1)
        core = self.regime_graph(core)

        if event_ctx is None:
            event_ctx = torch.zeros(b, n, 24, device=x.device, dtype=x.dtype)
        event_state = self.event_encoder(event_ctx)

        trunk = self.shared_trunk(torch.cat([core, event_state], dim=-1))

        direction = self.direction_head(trunk)
        trade_gate = self.trade_gate_head(trunk)
        size = self.size_head(trunk)
        stop_mult = self.stop_head(trunk) + 0.1
        target_mult = self.target_head(trunk) + 0.2
        hold_logits = self.hold_head(trunk)
        hold_horizon = F.softmax(hold_logits, dim=-1)
        uncertainty = self.uncertainty_head(trunk)
        regime_probs = self.regime_transition_head(trunk)
        adapt_mode_probs = self.adapt_policy_head(trunk)

        final_policy = self.risk_governor(
            trunk=trunk,
            direction=direction,
            trade_gate=trade_gate,
            size=size,
            stop_mult=stop_mult,
            target_mult=target_mult,
            hold_horizon=hold_horizon,
            uncertainty=uncertainty,
            adapt_mode_probs=adapt_mode_probs,
            live_stats=live_stats,
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
            "final_policy": final_policy,
            "states": [],
        }
