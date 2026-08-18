"""World sim unit tests: determinism and physics (Repeatability/Safety)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[2]))

import world.app as world_app  # noqa: E402
from world.app import ZONES, advance_tick, initial_state, path_between  # noqa: E402


def test_path_between_forward():
    assert path_between("A", "STAGING") == ["B", "C", "D", "STAGING"]


def test_path_between_backward():
    assert path_between("D", "A") == ["C", "B", "A"]


def test_path_between_same():
    assert path_between("C", "C") == []


def test_seeded_state_is_deterministic():
    assert initial_state(42) == initial_state(42)
    assert initial_state(42) != initial_state(7)


def test_human_blocks_motion():
    state = initial_state(42)
    world_app.STATE = state
    r = state["robots"]["amr-1"]
    r["path"] = ["B", "C"]
    state["humans"]["B"] = True
    advance_tick()
    assert r["zone"] == "A"  # physically blocked
    assert "blocked" in r["status"]
    state["humans"]["B"] = False
    advance_tick()
    assert r["zone"] == "B"


def test_non_active_mode_takes_no_new_motion():
    state = initial_state(42)
    world_app.STATE = state
    r = state["robots"]["amr-1"]
    r["path"] = ["B"]
    r["mode"] = "SAFE_IDLE"
    advance_tick()
    assert r["zone"] == "A"
    assert r["path"] == ["B"]  # path preserved for auto-resume
    r["mode"] = "ACTIVE"
    advance_tick()
    assert r["zone"] == "B"


def test_zone_topology():
    assert ZONES == ["A", "B", "C", "D", "STAGING"]
