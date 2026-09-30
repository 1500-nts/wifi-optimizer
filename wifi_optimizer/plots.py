"""Matplotlib figures for the report."""
from __future__ import annotations

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from .model import Network

C_BEFORE, C_AFTER = "#c0504d", "#2e8b57"
CH_COLOR = {1: "#1f77b4", 6: "#ff7f0e", 11: "#2ca02c"}


def _style():
    plt.rcParams.update({"axes.spines.top": False, "axes.spines.right": False,
                         "axes.grid": True, "grid.alpha": .25, "font.size": 10})


def topology(before: Network, after: Network, path: str) -> None:
    _style()
    fig, axes = plt.subplots(1, 2, figsize=(12, 5.4))
    for ax, net, title in ((axes[0], before, "BEFORE"), (axes[1], after, "AFTER")):
        st = net.evaluate()
        for c in net.clients:
            ap = net.aps[c.ap]
            ax.plot([c.x, ap.x], [c.y, ap.y], color=CH_COLOR.get(ap.channel, "gray"), alpha=.35, lw=1)
            ax.scatter(c.x, c.y, s=35 + 6 * c.demand_mbps, color=CH_COLOR.get(ap.channel, "gray"),
                       edgecolor="k", zorder=3)
            ax.annotate(f"U{c.id + 1}", (c.x, c.y), xytext=(4, 4), textcoords="offset points", fontsize=7)
        for ap in net.aps:
            a = st.aps[ap.id]
            ax.scatter(ap.x, ap.y, marker="s", s=200, color=CH_COLOR.get(ap.channel, "gray"),
                       edgecolor="k", linewidth=2, zorder=4)
            ax.annotate(f"AP-{ap.id + 1}\nch {ap.channel} | {a['users']} users\nairtime {min(a['busy'], 9.99):.0%}",
                        (ap.x, ap.y), xytext=(0, -62), textcoords="offset points",
                        ha="center", fontsize=8, fontweight="bold")
        for i in net.interferers:
            ax.scatter(i.x, i.y, marker="X", s=140, color="crimson", zorder=4)
            ax.annotate(f"neighbour net\nch {i.channel}", (i.x, i.y), xytext=(0, 9),
                        textcoords="offset points", ha="center", fontsize=7, color="crimson")
        s = st.summary
        ax.set_title(f"{title}: {s['throughput_mbps']:.0f}/{s['offered_mbps']:.0f} Mbps delivered, "
                     f"{s['mean_latency_ms']:.0f} ms latency", fontsize=10)
        ax.set_xlim(-5, net.cfg.area_m + 5)
        ax.set_ylim(-5, net.cfg.area_m + 5)
        ax.set_aspect("equal")
        ax.set_xlabel("x (m)")
    fig.suptitle("Topology (colour = channel, marker size = demand)", fontsize=12)
    fig.tight_layout()
    fig.savefig(path, dpi=140)
    plt.close(fig)


def before_after(b: dict, a: dict, path: str) -> None:
    _style()
    items = [("throughput_mbps", "Throughput (Mbps)", "higher is better"),
             ("mean_latency_ms", "Latency (ms)", "lower is better"),
             ("packet_loss_pct", "Packet loss (%)", "lower is better"),
             ("channel_util_pct", "Channel utilisation (%)", "lower is better"),
             ("interference_db", "Interference (dB over noise)", "lower is better")]
    fig, axes = plt.subplots(1, 5, figsize=(14, 3.6))
    for ax, (k, label, note) in zip(axes, items):
        bars = ax.bar(["Before", "After"], [b[k], a[k]], color=[C_BEFORE, C_AFTER], width=.6)
        for r in bars:
            ax.annotate(f"{r.get_height():.1f}", (r.get_x() + r.get_width() / 2, r.get_height()),
                        ha="center", va="bottom", fontsize=9)
        ax.set_title(label, fontsize=10)
        ax.set_xlabel(note, fontsize=8, color="gray")
        ax.margins(y=.15)
    fig.tight_layout()
    fig.savefig(path, dpi=140)
    plt.close(fig)


def timeseries(run: dict, path: str) -> None:
    _style()
    items = [("throughput_mbps", "Throughput (Mbps)"), ("mean_latency_ms", "Latency (ms)"),
             ("packet_loss_pct", "Packet loss (%)"), ("channel_util_pct", "Channel utilisation (%)")]
    fig, axes = plt.subplots(2, 2, figsize=(12, 6.5), sharex=True)
    t = range(run["steps"])
    for ax, (k, label) in zip(axes.flat, items):
        ax.plot(t, run["static"][k], color=C_BEFORE, label="static (no optimizer)", lw=2)
        ax.plot(t, run["optimized"][k], color=C_AFTER, label="with optimizer", lw=2)
        for name, at in run["events"].items():
            ax.axvline(at, color="gray", ls="--", lw=1)
            ax.annotate(name, (at, ax.get_ylim()[1]), xytext=(3, -12), textcoords="offset points",
                        fontsize=7, color="gray")
        ax.set_title(label, fontsize=10)
    axes[0, 0].legend(fontsize=8)
    for ax in axes[1]:
        ax.set_xlabel("time step")
    fig.suptitle("Dynamic scenario: users move, traffic surges, an interferer appears", fontsize=12)
    fig.tight_layout()
    fig.savefig(path, dpi=140)
    plt.close(fig)


def sweep(res: dict, metric: str, xlabel: str, ylabel: str, title: str, path: str) -> None:
    _style()
    fig, ax = plt.subplots(figsize=(6.4, 4.2))
    ax.plot(res["x"], [r["static"][metric] for r in res["results"]], "o-", color=C_BEFORE, label="static (no optimizer)")
    ax.plot(res["x"], [r["optimized"][metric] for r in res["results"]], "o-", color=C_AFTER, label="with optimizer")
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    ax.set_title(title)
    ax.legend()
    fig.tight_layout()
    fig.savefig(path, dpi=140)
    plt.close(fig)
