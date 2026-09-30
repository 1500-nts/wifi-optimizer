#!/usr/bin/env python3
"""Command-line entry point.

  python run.py all              # everything (recommended first run)
  python run.py static           # one before/after experiment + topology + change log
  python run.py dynamic          # time-varying scenario
  python run.py sweep            # load-vs-throughput and users-vs-latency curves
Options: --seed N  --random  --steps N  --aps N  --clients N  --no-power  --out DIR
  --random  new random seed every run (different users, traffic, interference, event times)
"""
import argparse
import csv
import json
import os
import random

from wifi_optimizer import plots
from wifi_optimizer.config import SimConfig
from wifi_optimizer.experiments import (METRICS, robustness, run_dynamic, run_static,
                                        sweep_load, sweep_users)

LABELS = {"throughput_mbps": "Throughput (Mbps)", "mean_latency_ms": "Latency (ms)",
          "packet_loss_pct": "Packet loss (%)", "channel_util_pct": "Channel utilisation (%)",
          "interference_db": "Interference (dB over noise)"}


def do_static(cfg, out, results):
    before, after, rep = run_static(cfg)
    b, a = rep.before.summary, rep.after.summary
    print("\n=== ISSUES DETECTED (Analyze) ===")
    for i in rep.issues:
        print(" ", i)
    print("\n=== CHANGES APPLIED (Optimize) ===")
    for c in rep.changes:
        print(" ", c)
    print(f"\n=== BEFORE vs AFTER (seed {cfg.seed}, {rep.rounds} optimisation rounds) ===")
    print(f"{'Metric':<32}{'Before':>10}{'After':>10}")
    for m in METRICS:
        print(f"{LABELS[m]:<32}{b[m]:>10.1f}{a[m]:>10.1f}")
    print(f"{'Interference level':<32}{b['interference_level']:>10}{a['interference_level']:>10}")
    print(f"{'Efficiency score':<32}{rep.before.score(cfg.eff):>10.2f}{rep.after.score(cfg.eff):>10.2f}")
    with open(os.path.join(out, "before_after.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["metric", "before", "after"])
        for m in METRICS:
            w.writerow([LABELS[m], round(b[m], 2), round(a[m], 2)])
    plots.topology(before, after, os.path.join(out, "topology.png"))
    plots.before_after(b, a, os.path.join(out, "before_after.png"))
    rob = robustness(cfg)
    print(f"\n=== ROBUSTNESS over {rob['seeds']} random topologies (mean) ===")
    for m in METRICS:
        print(f"{LABELS[m]:<32}{rob['before'][m][0]:>10.1f}{rob['after'][m][0]:>10.1f}")
    print(f"Optimizer never made the network worse in {rob['improved_or_equal']}/{rob['seeds']} runs.")
    results["static"] = {"seed": cfg.seed, "before": b, "after": a,
                         "issues": [str(i) for i in rep.issues], "changes": [str(c) for c in rep.changes]}
    results["robustness"] = rob


def do_dynamic(cfg, out, results, steps=60, randomize=False):
    surge_at, interferer_at = 15, 35
    if randomize:                                   # events happen at random times
        rng = random.Random(cfg.seed)
        surge_at = rng.randint(8, max(9, steps // 2 - 5))
        interferer_at = rng.randint(steps // 2, steps - 10)
    print(f"Dynamic run: seed={cfg.seed}, steps={steps}, traffic surge at t={surge_at}, "
          f"interferer appears at t={interferer_at}")
    run = run_dynamic(cfg, steps=steps, surge_at=surge_at, interferer_at=interferer_at)
    plots.timeseries(run, os.path.join(out, "dynamic_timeseries.png"))
    import numpy as np
    print("\n=== DYNAMIC SCENARIO (mean over all time steps) ===")
    for m in METRICS:
        print(f"{LABELS[m]:<32}{np.mean(run['static'][m]):>10.1f}{np.mean(run['optimized'][m]):>10.1f}")
    print("  columns: static | with optimizer;  reconfigurations:", sum(run["optimized"]["changes"]))
    results["dynamic"] = run


def do_sweep(cfg, out, results):
    sl, su = sweep_load(cfg), sweep_users(cfg)
    plots.sweep(sl, "throughput_mbps", "Offered traffic load (Mbps)", "Delivered throughput (Mbps)",
                "Traffic load vs throughput", os.path.join(out, "load_vs_throughput.png"))
    plots.sweep(su, "mean_latency_ms", "Number of users", "Mean latency (ms)",
                "Number of users vs latency", os.path.join(out, "users_vs_latency.png"))
    print("\n=== SWEEPS saved: load_vs_throughput.png, users_vs_latency.png ===")
    results["sweep_load"], results["sweep_users"] = sl, su


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("mode", choices=["all", "static", "dynamic", "sweep"])
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--random", action="store_true", help="use a new random seed every run")
    ap.add_argument("--steps", type=int, default=60, help="time steps in the dynamic scenario")
    ap.add_argument("--aps", type=int, default=2)
    ap.add_argument("--clients", type=int, default=10)
    ap.add_argument("--no-power", action="store_true", help="disable transmit-power tuning")
    ap.add_argument("--out", default="results")
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)
    if args.random:
        args.seed = random.randint(1, 10_000_000)
    print(f"Random seed = {args.seed}  (rerun with --seed {args.seed} to reproduce this exact result)")
    cfg = SimConfig(seed=args.seed, n_aps=args.aps, n_clients=args.clients,
                    enable_power_control=not args.no_power)
    results = {}
    if args.mode in ("all", "static"):
        do_static(cfg, args.out, results)
    if args.mode in ("all", "dynamic"):
        do_dynamic(cfg, args.out, results, args.steps, args.random)
    if args.mode in ("all", "sweep"):
        do_sweep(cfg, args.out, results)
    with open(os.path.join(args.out, "results.json"), "w") as f:
        json.dump(results, f, indent=2, default=float)
    print(f"\nAll outputs written to ./{args.out}/")


if __name__ == "__main__":
    main()