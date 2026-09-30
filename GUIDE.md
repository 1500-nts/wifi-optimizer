# Wi-Fi Network Optimizer: Complete Guide

Project from your video: **simulate a wireless network, monitor it, detect inefficiency
(channel interference, congestion, poor signal, overloaded APs), and dynamically change the
configuration to improve performance.**

    Monitor -> Analyze -> Optimize -> Measure

## 1. Quick start (5 minutes)

    cd wifi-optimizer
    python3 -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
    pip install -r requirements.txt
    python run.py all          # runs every experiment, writes results/
    python -m pytest -q        # 8 tests

Other modes: `python run.py static|dynamic|sweep`, options `--seed 3 --aps 3 --clients 20 --no-power`.

## 2. What the project does (mapped to your video)

| Video section | Where it is implemented |
|---|---|
| 1. Overloaded AP-1, spare capacity on AP-2, move U3 | `optimizer.optimize_associations` |
| 2-3. Efficiency defined mathematically, Monitor -> Analyze -> Optimize -> Measure | `NetState.score`, `Optimizer.monitor/analyze/optimize` |
| Metrics: throughput, latency, packet loss, channel utilisation, RSSI, interference | `Network.evaluate` |
| Efficiency Score = w1*tput - w2*latency - w3*loss - w4*interference - w5*congestion (weights configurable) | `config.EfficiencyWeights` |
| 4A. Dynamic channel selection | `optimize_channels` |
| 4B / 10. Load-aware AP selection (RSSI + capacity - utilisation - interference - latency) | `ap_scores`, `config.SelectionWeights` |
| 4C / 6. Transmit-power tuning (100% -> 80% -> 60%) | `optimize_power` |
| 9. Version 1: 2 APs, 10 clients, 3 channels, variable traffic/distance/interference | `SimConfig` defaults |
| 11. Dynamic behaviour (load spike -> detect -> move client -> re-measure) | `experiments.run_dynamic` |
| 12. Before vs after tables and graphs (numbers generated, not invented) | `run.py`, `plots.py`, `results/` |
| 14. Advanced version | section 7 below |

## 3. Architecture

    SimConfig ---> build_network()  ---> Network  (APs, clients, interferers, physics)
                                            |
        +-----------------------------------+
        v
    Optimizer:  monitor() -> analyze() -> optimize_channels()
                                          optimize_associations()
                                          optimize_power()   -> measure again
        v
    experiments.py (static A/B, dynamic run, sweeps)  ->  plots.py  ->  results/*.png|csv|json

Files:
- `wifi_optimizer/config.py` - every tunable number, including all weights
- `wifi_optimizer/model.py` - radio + MAC model and metrics
- `wifi_optimizer/optimizer.py` - the control loop and three mechanisms
- `wifi_optimizer/experiments.py` - before/after, dynamic, sweeps
- `wifi_optimizer/plots.py`, `run.py` - figures and CLI
- `tests/` - pytest suite

## 4. How the model works

1. **Signal.** `RSSI = TxPower - (40 dB + 30*log10(d)) + shadowing` (log-distance path loss).
2. **Interference.** Co-channel APs and external interferers add power in proportion to their duty cycle: `SINR = RSSI - (noise + interference)`.
3. **Rate.** Shannon capacity with an implementation-efficiency factor, capped at 130 Mbps, times a MAC efficiency of 0.6 (ACKs, backoff, headers).
4. **Airtime.** Each client needs `demand / rate` of airtime. An AP's *busy time* = its own load + load of same-channel APs it can hear + external interferer duty. If busy > 100 % everyone gets `1/busy` of what they asked for.
5. **Loss / latency.** Loss grows as SINR falls and with contention; latency uses a queueing term `rho/(1-rho)` plus a penalty when the channel is saturated.
6. **Network metrics.** Throughput, mean latency, loss, channel utilisation, interference (dB above noise), congestion index, Jain fairness.

This is a **flow-level analytical model**, deliberately simple so the optimizer can test
hundreds of what-if configurations instantly. Be upfront about this in your report (see section 8).

## 5. How the optimizer works

Each *round*:
1. **Monitor** - `net.evaluate()` returns per-client, per-AP and network metrics.
2. **Analyze** - threshold rules produce `Issue`s (overloaded AP, congestion, co-channel interference, poor signal, imbalance).
3. **Optimize**
   - *Channels:* for each AP, try every channel, keep the one with the best global score.
   - *Associations:* for each client score every reachable AP with
     `w1*RSSI + w2*capacity - w3*utilisation - w4*interference - w5*latency`.
     Move only if the gain exceeds a **hysteresis** margin (prevents ping-pong) **and** the global score improves.
   - *Power:* try 100/80/60 %, accept only if every attached client keeps RSSI above the poor-signal threshold.
4. **Measure** - re-evaluate and log the change. Loop until no change helps (max 6 rounds).

Safety property: every accepted change increases the global Efficiency Score, so the optimizer
cannot make the network worse (tested in `test_optimizer_improves_score_across_seeds`).

## 6. Results you get (default settings, 20 random topologies)

| Metric | Unoptimized | Optimized |
|---|---|---|
| Throughput | 40.0 Mbps | 88.4 Mbps |
| Latency | 228 ms | 9 ms |
| Packet loss | 20.4 % | 0.5 % |
| Channel utilisation | 100 % | 59 % |
| Interference | 17.9 dB | 0.0 dB |

Most of the gain is from moving APs off the shared default channel; the load-aware association
step then balances users. In the **dynamic** scenario (users move, traffic surges, an interferer
appears) the gain is smaller (latency 106 -> 62 ms) because the "static" network there already starts on separate channels.
Report both. That honesty makes the project more credible.

## 7. Extending it (your roadmap phases)

1. **More realism:** replace path loss with an indoor model (walls), add 5 GHz channels, 802.11 rate tables.
2. **Multi-objective:** add energy use as another term; sweep weights to draw a Pareto front.
3. **Better search:** replace the greedy loop in `optimize_channels` with simulated annealing or a genetic algorithm and compare.
4. **Machine learning:** log `(state, action, score gain)` rows from the optimizer, train a model to predict congestion a few steps ahead (`experiments.run_dynamic` gives you time series), and act *before* overload happens.
5. **NS-3 (packet-level):** keep `optimizer.py` unchanged. Write an NS-3 scenario (C++) that exports per-client RSSI, airtime and loss as JSON each second, and add a `Network` subclass that reads that instead of the analytical formulas. Apply the returned channel/association decisions back through NS-3 attributes.
6. **Dashboard:** wrap `run_static`/`run_dynamic` in a FastAPI (or Spring Boot) service returning `results.json`, and show it with React + Recharts. This matches the Java/React stack you mentioned.

## 8. Limitations to state in your report

- Analytical model, not a packet simulator; absolute numbers are indicative, trends are the point.
- Greedy search can miss global optima; try annealing to test this.
- The "static" baseline (all APs on channel 1, strongest-signal association) is a common unmanaged default, but a well-planned manual network would already do better. The dynamic experiment shows the smaller, more realistic gain.
- Parameters (weights, thresholds, path-loss exponent) are assumptions. Run sensitivity analysis and cite sources (IEEE 802.11 standard, Rappaport *Wireless Communications*).

## 9. Suggested report structure

1. Problem & motivation 2. Wi-Fi background (802.11, CSMA/CA, RSSI, SNR, hidden terminal)
3. Model 4. Efficiency metric 5. Algorithms 6. Experiments (static, robustness, dynamic, sweeps)
7. Results & discussion 8. Limitations & future work.
Use `results/*.png` directly as figures.

## 10. Suggested timeline

| Week | Goal |
|---|---|
| 1 | Learn Wi-Fi fundamentals; run and read `model.py` |
| 2 | Modify topology/config; reproduce results |
| 3 | Add one extension (e.g., annealing or 5 GHz) |
| 4 | Dynamic experiments, sweeps, sensitivity analysis |
| 5 | Dashboard or NS-3 integration (optional) |
| 6 | Write report, record demo |
