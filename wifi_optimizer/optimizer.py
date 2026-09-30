"""Monitor -> Analyze -> Optimize -> Measure control loop.

Three optimisation mechanisms (from the project brief):
  A. Dynamic channel selection
  B. Load-aware AP selection
  C. Transmit-power tuning (optional / advanced)
Every change is applied only if it improves the global Efficiency Score.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .model import Network, NetState


@dataclass
class Issue:
    kind: str        # overloaded_ap | channel_congestion | co_channel_interference | poor_signal | imbalance
    where: str
    detail: str

    def __str__(self) -> str:
        return f"[{self.kind}] {self.where}: {self.detail}"


@dataclass
class Change:
    kind: str        # channel | association | power
    target: str
    old: str
    new: str
    gain: float

    def __str__(self) -> str:
        return f"{self.kind}: {self.target} {self.old} -> {self.new} (score +{self.gain:.3f})"


@dataclass
class Report:
    before: NetState
    after: NetState
    issues: list = field(default_factory=list)
    changes: list = field(default_factory=list)
    rounds: int = 0


class Optimizer:
    def __init__(self, net: Network):
        self.net = net
        self.cfg = net.cfg

    # ------------------------------------------------------------ 1. monitor
    def monitor(self) -> NetState:
        return self.net.evaluate()

    def _score(self) -> float:
        return self.net.evaluate().score(self.cfg.eff)

    # ----------------------------------------------------------- 2. analyze
    def analyze(self, st: NetState) -> list:
        cfg, issues = self.cfg, []
        for aid, a in st.aps.items():
            if a["users"] and a["load"] > cfg.overload_util:
                issues.append(Issue("overloaded_ap", f"AP-{aid + 1}",
                                    f"load {a['load']:.0%} with {a['users']} users"))
            if a["users"] and a["busy"] > cfg.congestion_util:
                issues.append(Issue("channel_congestion", f"AP-{aid + 1}",
                                    f"channel {a['channel']} busy {min(a['busy'], 9.99):.0%}"))
            if a["external"] > 0.05:
                issues.append(Issue("co_channel_interference", f"AP-{aid + 1}",
                                    f"external interferer occupies {a['external']:.0%} of channel {a['channel']}"))
        by_ch: dict = {}
        for aid, a in st.aps.items():
            if a["users"]:
                by_ch.setdefault(a["channel"], []).append(aid)
        for ch, ids in by_ch.items():
            if len(ids) > 1:
                names = ", ".join(f"AP-{i + 1}" for i in ids)
                issues.append(Issue("co_channel_interference", names, f"share channel {ch}"))
        for cid, m in st.clients.items():
            if m["rssi"] < cfg.poor_rssi_dbm:
                issues.append(Issue("poor_signal", f"U{cid + 1}", f"RSSI {m['rssi']:.0f} dBm"))
        loads = [a["load"] for a in st.aps.values() if a["users"]]
        if len(loads) > 1 and max(loads) - min(loads) > 0.4:
            issues.append(Issue("imbalance", "network", f"load spread {min(loads):.0%}..{max(loads):.0%}"))
        return issues

    # ------------------------------------------- 3a. dynamic channel selection
    def optimize_channels(self) -> list:
        changes = []
        order = sorted(self.net.aps, key=lambda a: -self.net.evaluate().aps[a.id]["load"])
        for ap in order:
            base = self._score()
            best_ch, best = ap.channel, base
            for ch in self.cfg.channels:
                if ch == ap.channel:
                    continue
                old, ap.channel = ap.channel, ch
                s = self._score()
                ap.channel = old
                if s > best + self.cfg.min_gain:
                    best_ch, best = ch, s
            if best_ch != ap.channel:
                changes.append(Change("channel", f"AP-{ap.id + 1}", str(ap.channel), str(best_ch), best - base))
                ap.channel = best_ch
        return changes

    # -------------------------------------------- 3b. load-aware AP selection
    def ap_scores(self, client) -> dict:
        """score = w1*RSSI + w2*capacity - w3*utilisation - w4*interference - w5*latency
        evaluated with a what-if association for each candidate AP."""
        w, original, out = self.cfg.sel, client.ap, {}
        for ap in self.net.candidate_aps(client):
            client.ap = ap.id
            st = self.net.evaluate()
            m, a = st.clients[client.id], st.aps[ap.id]
            rssi_n = min(max((m["rssi"] + 90.0) / 50.0, 0.0), 1.0)      # -90 dBm -> 0, -40 dBm -> 1
            capacity = max(0.0, 1.0 - a["load"])
            util = min(a["busy"], 1.5) / 1.5
            intf = min(max(m["inr_db"] / 20.0, 0.0), 1.0)
            lat = min(m["latency_ms"] / 100.0, 1.0)
            out[ap.id] = (w.rssi * rssi_n + w.capacity * capacity - w.utilisation * util
                          - w.interference * intf - w.latency * lat)
        client.ap = original
        return out

    def optimize_associations(self) -> list:
        changes = []
        for c in sorted(self.net.clients, key=lambda c: -c.demand_mbps):
            scores = self.ap_scores(c)
            best = max(scores, key=scores.get)
            if best == c.ap or scores[best] - scores.get(c.ap, -9) < self.cfg.hysteresis:
                continue                                   # hysteresis: avoid ping-pong
            base, old = self._score(), c.ap
            c.ap = best
            gain = self._score() - base
            if gain > self.cfg.min_gain:                   # global safety check
                changes.append(Change("association", f"U{c.id + 1}", f"AP-{old + 1}", f"AP-{best + 1}", gain))
            else:
                c.ap = old
        return changes

    # ------------------------------------------------ 3c. transmit-power tuning
    def optimize_power(self) -> list:
        changes = []
        for ap in self.net.aps:
            base, best_p, best = self._score(), ap.power_frac, None
            best = base
            for p in self.cfg.power_levels:
                if p == ap.power_frac:
                    continue
                old, ap.power_frac = ap.power_frac, p
                st = self.net.evaluate()
                covered = all(m["rssi"] >= self.cfg.poor_rssi_dbm
                              for m in st.clients.values() if m["ap"] == ap.id)
                s = st.score(self.cfg.eff)
                ap.power_frac = old
                if covered and s > best + self.cfg.min_gain:
                    best_p, best = p, s
            if best_p != ap.power_frac:
                changes.append(Change("power", f"AP-{ap.id + 1}", f"{ap.power_frac:.0%}", f"{best_p:.0%}", best - base))
                ap.power_frac = best_p
        return changes

    # --------------------------------------------------------- 4. full loop
    def optimize(self) -> Report:
        before = self.monitor()
        issues = self.analyze(before)
        all_changes, rounds = [], 0
        for _ in range(self.cfg.max_rounds):
            rounds += 1
            ch = (self.optimize_channels() + self.optimize_associations()
                  + (self.optimize_power() if self.cfg.enable_power_control else []))
            all_changes += ch
            if not ch:
                break
        return Report(before, self.monitor(), issues, all_changes, rounds)
