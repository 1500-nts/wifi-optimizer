import copy
from wifi_optimizer.config import SimConfig
from wifi_optimizer.model import build_network, dbm_to_mw, mw_to_dbm
from wifi_optimizer.optimizer import Optimizer


def test_dbm_roundtrip():
    assert abs(mw_to_dbm(dbm_to_mw(-42.0)) + 42.0) < 1e-9


def test_rssi_decreases_with_distance():
    net = build_network(SimConfig())
    c, ap = net.clients[0], net.aps[0]
    near = net.rssi(c, ap)
    c.x, c.y = ap.x + 90, ap.y
    assert net.rssi(c, ap) < near


def test_same_channel_is_worse_than_separate_channels():
    cfg = SimConfig()
    a = build_network(cfg, channels=[1, 1]).evaluate().summary
    b = build_network(cfg, channels=[1, 11]).evaluate().summary
    assert b["throughput_mbps"] > a["throughput_mbps"]
    assert b["mean_latency_ms"] < a["mean_latency_ms"]


def test_analyzer_detects_problems():
    net = build_network(SimConfig())
    kinds = {i.kind for i in Optimizer(net).analyze(net.evaluate())}
    assert "co_channel_interference" in kinds and "channel_congestion" in kinds


def test_optimizer_improves_score_across_seeds():
    for seed in range(1, 11):
        cfg = SimConfig(seed=seed)
        rep = Optimizer(build_network(cfg)).optimize()
        assert rep.after.score(cfg.eff) >= rep.before.score(cfg.eff)


def test_optimizer_is_idempotent_when_converged():
    net = build_network(SimConfig())
    opt = Optimizer(net)
    opt.optimize()
    assert opt.optimize().changes == []       # no ping-pong


def test_every_client_stays_associated():
    net = build_network(SimConfig())
    Optimizer(net).optimize()
    assert all(c.ap is not None for c in net.clients)


def test_weights_are_configurable():
    cfg = SimConfig()
    net = build_network(cfg)
    st = net.evaluate()
    hi = copy.deepcopy(cfg.eff); hi.latency = 5.0
    assert st.score(hi) < st.score(cfg.eff)
