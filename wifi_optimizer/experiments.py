"""Experiments that produce the 'before vs after' evidence the project needs.

Nothing here is hard-coded: every number comes from the simulator."""
from __future__ import annotations

import copy
import math

import numpy as np

from .config import SimConfig
from .model import Interferer, Network, build_network
from .optimizer import Optimizer

METRICS = ["throughput_mbps", "mean_latency_ms", "packet_loss_pct",
           "channel_util_pct", "interference_db"]


# ------------------------------------------------------------ 1. static A/B
def run_static(cfg: SimConfig):
    """One network, optimised once. Returns (network_before, network_after, report)."""
    net = build_network(cfg)
    before = net.clone()
    report = Optimizer(net).optimize()
    return before, net, report


def robustness(cfg: SimConfig, seeds: int = 20) -> dict:
    """Repeat the static experiment over many random topologies (mean +/- std)."""
    rows = {m: [] for m in METRICS}
    rows_after = {m: [] for m in METRICS}
    wins = 0
    for s in range(1, seeds + 1):
        c = copy.deepcopy(cfg)
        c.seed = s
        _, _, r = run_static(c)
        for m in METRICS:
            rows[m].append(r.before.summary[m])
            rows_after[m].append(r.after.summary[m])
        wins += r.after.score(c.eff) >= r.before.score(c.eff)
    return {"seeds": seeds, "improved_or_equal": wins,
            "before": {m: (float(np.mean(v)), float(np.std(v))) for m, v in rows.items()},
            "after": {m: (float(np.mean(v)), float(np.std(v))) for m, v in rows_after.items()}}


# ------------------------------------------------------------- 2. dynamic run
def _sticky_roam(net: Network, margin_db: float = 8.0) -> None:
    """Unmanaged clients only roam if the signal is lost or another AP is much stronger."""
    for c in net.clients:
        cur = net.aps[c.ap]
        best = max(net.aps, key=lambda a: net.rssi(c, a))
        if net.rssi(c, cur) < net.cfg.min_rssi_dbm or net.rssi(c, best) > net.rssi(c, cur) + margin_db:
            c.ap = best.id


def make_script(cfg: SimConfig, steps: int, surge_at: int, interferer_at: int):
    """Pre-compute user movement + traffic so both runs see the identical world."""
    rng = np.random.default_rng(cfg.seed)
    quiet = copy.deepcopy(cfg)
    quiet.neighbor_duty = 0.0
    net = build_network(quiet, rng, channels=[cfg.channels[0], cfg.channels[1]] + [cfg.channels[2]] * max(0, cfg.n_aps - 2))
    base = [c.demand_mbps * 0.5 for c in net.clients]
    left = [c.x < cfg.area_m / 2 for c in net.clients]
    pos = np.zeros((steps, len(net.clients), 2))
    p = np.array([[c.x, c.y] for c in net.clients])
    for t in range(steps):
        p = np.clip(p + rng.normal(0, 1.6, p.shape), 0, cfg.area_m)
        pos[t] = p
    return net, base, left, pos, surge_at, interferer_at


def run_dynamic(cfg: SimConfig, steps: int = 60, surge_at: int = 15, interferer_at: int = 35,
                interval: int = 5) -> dict:
    """Same changing world, with and without the optimizer."""
    net0, base, left, pos, s_at, i_at = make_script(cfg, steps, surge_at, interferer_at)
    runs = {}
    for name in ("static", "optimized"):
        net = net0.clone()
        net.associate_strongest()
        series = {m: [] for m in METRICS + ["changes"]}
        for t in range(steps):
            # --- the world changes ---
            ramp = min(max((t - s_at) / 5.0, 0.0), 1.0)
            for k, c in enumerate(net.clients):
                c.x, c.y = pos[t, k]
                surge = (1 + 1.6 * ramp) if left[k] else (1 + 0.3 * ramp)
                c.demand_mbps = base[k] * surge
            if t == i_at:
                ap2 = net.aps[1]
                net.interferers.append(Interferer(ap2.x + 8, ap2.y + 10, ap2.channel, 0.65, 18.0))
            # --- (optionally) the control loop reacts ---
            _sticky_roam(net)
            n_changes = 0
            if name == "optimized" and t % interval == 0:
                n_changes = len(Optimizer(net).optimize().changes)
            s = net.evaluate().summary
            for m in METRICS:
                series[m].append(s[m])
            series["changes"].append(n_changes)
        runs[name] = series
    runs["events"] = {"traffic surge": s_at, "interference appears": i_at}
    runs["steps"] = steps
    return runs


# ----------------------------------------------------------------- 3. sweeps
def _avg_final(cfg: SimConfig, seeds: int, mutate) -> dict:
    out = {"static": {m: [] for m in METRICS}, "optimized": {m: [] for m in METRICS}}
    for s in range(1, seeds + 1):
        c = copy.deepcopy(cfg)
        c.seed = s
        mutate(c)
        _, _, r = run_static(c)
        for m in METRICS:
            out["static"][m].append(r.before.summary[m])
            out["optimized"][m].append(r.after.summary[m])
    return {k: {m: float(np.mean(v)) for m, v in d.items()} for k, d in out.items()}


def sweep_load(cfg: SimConfig, factors=(0.4, 0.7, 1.0, 1.3, 1.6, 2.0), seeds: int = 8) -> dict:
    """Traffic load vs throughput."""
    res = []
    for f in factors:
        def mut(c, f=f):
            c.demand_min_mbps *= f
            c.demand_max_mbps *= f
        res.append(_avg_final(cfg, seeds, mut))
    return {"x": [f * (cfg.demand_min_mbps + cfg.demand_max_mbps) / 2 * cfg.n_clients for f in factors],
            "results": res}


def sweep_users(cfg: SimConfig, counts=(4, 8, 12, 16, 20, 26), seeds: int = 8) -> dict:
    """Number of users vs latency (per-user demand kept constant)."""
    res = []
    for n in counts:
        def mut(c, n=n):
            c.n_clients = n
        res.append(_avg_final(cfg, seeds, mut))
    return {"x": list(counts), "results": res}
