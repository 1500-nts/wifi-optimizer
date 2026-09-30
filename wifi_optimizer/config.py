"""All tunable settings live here (weights are configurable, never hard-coded)."""
from dataclasses import dataclass, field


@dataclass
class EfficiencyWeights:
    """Network-level objective:
    score = w1*throughput - w2*latency - w3*loss - w4*interference - w5*congestion
    (every term is normalised to roughly 0..1 before weighting)."""
    throughput: float = 1.0
    latency: float = 0.5
    loss: float = 1.0
    interference: float = 0.3
    congestion: float = 0.5


@dataclass
class SelectionWeights:
    """Per-client AP scoring:
    score = w1*RSSI + w2*available capacity - w3*channel utilisation
            - w4*interference - w5*latency"""
    rssi: float = 0.8
    capacity: float = 1.0
    utilisation: float = 0.8
    interference: float = 0.4
    latency: float = 0.6


@dataclass
class SimConfig:
    # --- topology (version 1: 2 APs, 10 clients, 3 channels) ---
    area_m: float = 100.0
    n_aps: int = 2
    n_clients: int = 10
    channels: tuple = (1, 6, 11)          # non-overlapping 2.4 GHz channels
    seed: int = 1

    # --- radio model ---
    ap_tx_dbm: float = 20.0
    noise_dbm: float = -95.0
    cca_dbm: float = -82.0                # APs hear each other above this -> share airtime
    bandwidth_hz: float = 20e6
    shannon_eff: float = 0.75
    mac_eff: float = 0.60                 # protocol overhead (ACKs, backoff, headers)
    max_phy_mbps: float = 130.0
    pathloss_ref_db: float = 40.0
    pathloss_exp: float = 3.0
    shadow_sigma_db: float = 2.0

    # --- traffic ---
    demand_min_mbps: float = 4.0
    demand_max_mbps: float = 14.0
    neighbor_duty: float = 0.30           # a neighbouring Wi-Fi network on channel 6 (0 = none)
    base_loss: float = 0.005              # background loss floor (0.5 %)
    cluster_fraction: float = 0.6         # share of clients that start near AP-1 (creates imbalance)

    # --- thresholds used by the analyzer ---
    overload_util: float = 0.80
    congestion_util: float = 0.80
    poor_rssi_dbm: float = -75.0
    min_rssi_dbm: float = -80.0           # below this a client cannot associate to that AP

    # --- optimizer behaviour ---
    hysteresis: float = 0.05              # min score gain before moving a client (stops ping-pong)
    min_gain: float = 1e-3                # min global gain to accept any change
    max_rounds: int = 6
    power_levels: tuple = (1.0, 0.8, 0.6) # 100% / 80% / 60% transmit power
    enable_power_control: bool = True

    eff: EfficiencyWeights = field(default_factory=EfficiencyWeights)
    sel: SelectionWeights = field(default_factory=SelectionWeights)
