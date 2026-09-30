"""Wireless network model: propagation, interference, airtime sharing, and metrics.

This is an analytical (flow-level) model, not a packet-level simulator. It is fast
enough to evaluate thousands of "what-if" configurations, which is what the
optimizer needs. See GUIDE.md for how to swap in NS-3 later.
"""
from __future__ import annotations

import copy
import math
import zlib
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

from .config import EfficiencyWeights, SimConfig


def dbm_to_mw(dbm: float) -> float:
    return 10 ** (dbm / 10.0)


def mw_to_dbm(mw: float) -> float:
    return 10.0 * math.log10(max(mw, 1e-30))


@dataclass
class AP:
    id: int
    x: float
    y: float
    channel: int
    power_frac: float = 1.0          # 1.0 = 100 % transmit power


@dataclass
class Client:
    id: int
    x: float
    y: float
    demand_mbps: float
    ap: Optional[int] = None


@dataclass
class Interferer:
    """Non-cooperative noise source (microwave, neighbour's Wi-Fi, Bluetooth...)."""
    x: float
    y: float
    channel: int
    duty: float = 0.5                # fraction of time it transmits
    tx_dbm: float = 15.0


@dataclass
class NetState:
    """Snapshot produced by Network.evaluate() - the 'Monitor' output."""
    clients: dict = field(default_factory=dict)   # id -> dict of per-client metrics
    aps: dict = field(default_factory=dict)       # id -> dict of per-AP metrics
    summary: dict = field(default_factory=dict)   # network-wide metrics

    def score(self, w: EfficiencyWeights) -> float:
        """Efficiency Score = w1*tput - w2*latency - w3*loss - w4*interference - w5*congestion."""
        s = self.summary
        tput = s["throughput_mbps"] / max(s["offered_mbps"], 1e-9)
        lat = min(s["mean_latency_ms"] / 100.0, 1.0)
        loss = s["packet_loss_pct"] / 100.0
        intf = min(max(s["interference_db"] / 20.0, 0.0), 1.0)
        cong = s["congestion_index"]
        return (w.throughput * tput - w.latency * lat - w.loss * loss
                - w.interference * intf - w.congestion * cong)


class Network:
    def __init__(self, cfg: SimConfig, aps: list, clients: list, interferers: Optional[list] = None):
        self.cfg = cfg
        self.aps = aps
        self.clients = clients
        self.interferers = interferers or []
        self._shadow_cache: dict = {}

    # ------------------------------------------------------------------ copy
    def clone(self) -> "Network":
        return copy.deepcopy(self)

    # ------------------------------------------------------------ propagation
    def _shadow(self, cid: int, aid: int) -> float:
        key = (cid, aid)
        if key not in self._shadow_cache:
            rng = np.random.default_rng(zlib.crc32(f"{self.cfg.seed}-{cid}-{aid}".encode()))
            self._shadow_cache[key] = float(rng.normal(0.0, self.cfg.shadow_sigma_db))
        return self._shadow_cache[key]

    def _pathloss(self, d: float) -> float:
        return self.cfg.pathloss_ref_db + 10 * self.cfg.pathloss_exp * math.log10(max(d, 1.0))

    def ap_tx_dbm(self, ap: AP) -> float:
        return self.cfg.ap_tx_dbm + 10 * math.log10(ap.power_frac)

    def rssi(self, c: Client, ap: AP) -> float:
        d = math.hypot(c.x - ap.x, c.y - ap.y)
        return self.ap_tx_dbm(ap) - self._pathloss(d) + self._shadow(c.id, ap.id)

    def ap_to_ap_rssi(self, a: AP, b: AP) -> float:
        return self.ap_tx_dbm(a) - self._pathloss(math.hypot(a.x - b.x, a.y - b.y))

    def _intf_rssi(self, i: Interferer, x: float, y: float) -> float:
        return i.tx_dbm - self._pathloss(math.hypot(i.x - x, i.y - y))

    # ---------------------------------------------------------------- PHY/MAC
    def _rate(self, sinr_db: float) -> float:
        """Usable Mbps for a link at the given SINR (rate adaptation + MAC overhead)."""
        c = self.cfg
        sinr = 10 ** (sinr_db / 10.0)
        phy = c.shannon_eff * (c.bandwidth_hz / 1e6) * math.log2(1 + sinr)
        phy = min(max(phy, 1.0), c.max_phy_mbps)
        return phy * c.mac_eff

    @staticmethod
    def _per(sinr_db: float) -> float:
        return 1.0 / (1.0 + math.exp((sinr_db - 3.0) / 1.5))

    # ------------------------------------------------------------- association
    def associate_strongest(self) -> None:
        """Default client behaviour: join the AP with the best RSSI."""
        for c in self.clients:
            c.ap = max(self.aps, key=lambda a: self.rssi(c, a)).id

    def candidate_aps(self, c: Client) -> list:
        ok = [a for a in self.aps if self.rssi(c, a) >= self.cfg.min_rssi_dbm]
        return ok or [max(self.aps, key=lambda a: self.rssi(c, a))]

    # ---------------------------------------------------------------- monitor
    def evaluate(self) -> NetState:
        cfg = self.cfg
        noise_mw = dbm_to_mw(cfg.noise_dbm)
        aps = {a.id: a for a in self.aps}
        assoc = [c for c in self.clients if c.ap is not None]
        rssi = {c.id: self.rssi(c, aps[c.ap]) for c in assoc}

        # Pass 1: noise-limited rates -> estimate each AP's duty cycle.
        duty = {a.id: 0.0 for a in self.aps}
        for c in assoc:
            duty[c.ap] += c.demand_mbps / self._rate(rssi[c.id] - cfg.noise_dbm)
        duty = {k: min(v, 1.0) for k, v in duty.items()}

        # Pass 2: real SINR including co-channel interference weighted by duty cycle.
        cl, load = {}, {a.id: 0.0 for a in self.aps}
        for c in assoc:
            ch = aps[c.ap].channel
            i_mw = 0.0
            for j in self.aps:
                if j.id != c.ap and j.channel == ch:
                    i_mw += duty[j.id] * dbm_to_mw(self.rssi(c, j))
            for x in self.interferers:
                if x.channel == ch:
                    i_mw += x.duty * dbm_to_mw(self._intf_rssi(x, c.x, c.y))
            sinr_db = rssi[c.id] - mw_to_dbm(noise_mw + i_mw)
            inr_db = mw_to_dbm(noise_mw + i_mw) - cfg.noise_dbm
            rate = self._rate(sinr_db)
            airtime = c.demand_mbps / rate
            load[c.ap] += airtime
            cl[c.id] = dict(ap=c.ap, rssi=rssi[c.id], sinr_db=sinr_db, inr_db=inr_db,
                            rate_mbps=rate, airtime=airtime, demand=c.demand_mbps)

        # Channel contention: APs on the same channel that hear each other share airtime.
        ap_stats = {}
        for a in self.aps:
            busy = load[a.id]
            for b in self.aps:
                if b.id != a.id and b.channel == a.channel:
                    if max(self.ap_to_ap_rssi(a, b), self.ap_to_ap_rssi(b, a)) > cfg.cca_dbm:
                        busy += min(load[b.id], 1.0)
            ext = 0.0
            for x in self.interferers:
                if x.channel == a.channel and self._intf_rssi(x, a.x, a.y) > cfg.cca_dbm:
                    ext += x.duty
            busy += ext
            users = sum(1 for c in assoc if c.ap == a.id)
            ap_stats[a.id] = dict(channel=a.channel, users=users, load=load[a.id], busy=busy,
                                  external=ext, power_frac=a.power_frac,
                                  served=1.0 if busy <= 1.0 else 1.0 / busy)

        # Per-client throughput / latency / loss.
        cfg = self.cfg
        for cid, m in cl.items():
            st = ap_stats[m["ap"]]
            busy, neigh = st["busy"], st["busy"] - st["load"]
            loss = cfg.base_loss + self._per(m["sinr_db"]) + 0.10 * min(neigh, 1.0) + 0.12 * max(0.0, busy - 1.0)
            loss = min(max(loss, 0.0), 0.6)
            rho = min(busy, 0.98)
            lat = (4.0 + 12.0 / m["rate_mbps"] + 3.0 * rho / (1 - rho)
                   + 80.0 * max(0.0, busy - 1.0) + 25.0 * loss)
            m.update(loss=loss, latency_ms=min(lat, 300.0),
                     throughput=m["demand"] * st["served"] * (1 - loss))

        return NetState(clients=cl, aps=ap_stats, summary=self._summarise(cl, ap_stats))

    def _summarise(self, cl: dict, ap_stats: dict) -> dict:
        cfg = self.cfg
        offered = sum(m["demand"] for m in cl.values())
        tput = sum(m["throughput"] for m in cl.values())
        lat = float(np.mean([m["latency_ms"] for m in cl.values()]))
        loss = sum(m["loss"] * m["demand"] for m in cl.values()) / max(offered, 1e-9) * 100
        inr = float(np.mean([m["inr_db"] for m in cl.values()]))
        used = [s for s in ap_stats.values() if s["users"] > 0]
        util = float(np.mean([min(s["busy"], 1.0) for s in used]))
        cong = float(np.mean([min(max((s["busy"] - 0.5) / 1.0, 0.0), 1.0) for s in used]))
        ratios = np.array([m["throughput"] / m["demand"] for m in cl.values()])
        jain = float(ratios.sum() ** 2 / (len(ratios) * (ratios ** 2).sum() + 1e-12))
        return dict(
            throughput_mbps=tput, offered_mbps=offered, mean_latency_ms=lat,
            packet_loss_pct=loss, channel_util_pct=util * 100,
            max_channel_util_pct=min(max(s["busy"] for s in used), 1.0) * 100,
            interference_db=inr,
            interference_level="Low" if inr < 3 else "Medium" if inr < 10 else "High",
            congestion_index=cong, fairness=jain,
            poor_signal_clients=sum(1 for m in cl.values() if m["rssi"] < cfg.poor_rssi_dbm),
            overloaded_aps=sum(1 for s in used if s["load"] > cfg.overload_util),
        )


# ---------------------------------------------------------------- scenarios
def build_network(cfg: SimConfig, rng: Optional[np.random.Generator] = None,
                  channels: Optional[list] = None) -> Network:
    """Create APs + clients. By default every AP sits on channel 1 (the typical
    unmanaged default) and every client joins the strongest AP."""
    rng = rng or np.random.default_rng(cfg.seed)
    n, side = cfg.n_aps, cfg.area_m
    if channels is None:
        channels = [cfg.channels[0]] * n
    aps = [AP(i, side * (i + 0.5) / n, side / 2, channels[i]) for i in range(n)]
    clients = []
    for k in range(cfg.n_clients):
        if rng.random() < cfg.cluster_fraction:          # crowd around AP-1 -> imbalance
            r, th = 22 * math.sqrt(rng.random()), rng.uniform(0, 2 * math.pi)
            x, y = aps[0].x + r * math.cos(th), aps[0].y + r * math.sin(th)
        else:
            x, y = rng.uniform(0, side), rng.uniform(0, side)
        x, y = min(max(x, 0), side), min(max(y, 0), side)
        clients.append(Client(k, x, y, float(rng.uniform(cfg.demand_min_mbps, cfg.demand_max_mbps))))
    interferers = []
    if cfg.neighbor_duty > 0:                              # neighbour's Wi-Fi on channel 6
        interferers.append(Interferer(side * 0.85, side * 0.2, 6, cfg.neighbor_duty, 18.0))
    net = Network(cfg, aps, clients, interferers)
    net.associate_strongest()
    return net
