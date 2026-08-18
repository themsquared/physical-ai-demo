"""Reflex tier unit tests: in-process, fast, network-free (Safety/Speed)."""

import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[2]))

from robots.reflex import ReflexTier  # noqa: E402


def make_reflex(**snapshot) -> ReflexTier:
    r = ReflexTier("amr-test")
    r.snapshot = {"zone": "A", "humans": {z: False for z in "ABCD"}, **snapshot}
    return r


def test_clear_path_allowed():
    assert make_reflex().check_motion("B").allowed


def test_human_in_target_zone_refused():
    r = make_reflex(humans={"A": False, "B": False, "C": True, "D": False})
    d = r.check_motion("C")
    assert not d.allowed and "human" in d.reason


def test_human_in_current_zone_refused():
    r = make_reflex(humans={"A": True, "B": False, "C": False, "D": False})
    assert not r.check_motion("B").allowed


def test_estop_blocks_everything():
    r = make_reflex()
    r.emergency_stop()
    assert not r.check_motion("B").allowed


def test_disabled_safety_stop_allows_motion():
    # the dangerous path exists on purpose; the gateway keeps it gated
    r = make_reflex(humans={"A": False, "B": True, "C": False, "D": False})
    r.safety_stop_enabled = False
    assert r.check_motion("B").allowed


def test_decision_latency_slo():
    """Reflex decisions must be far under the 10ms e-stop SLO."""
    r = make_reflex()
    for _ in range(1000):
        r.check_motion("B")
    p99_us = statistics.quantiles(r.timings_us, n=100)[98]
    assert p99_us < 10_000, f"reflex p99 {p99_us:.0f}us breaches 10ms SLO"
