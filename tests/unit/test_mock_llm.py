"""mock-llm determinism tests: same conversation in, same tool calls out."""

import importlib.util
import sys
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "mock_llm_app", Path(__file__).parents[2] / "mock-llm" / "app.py"
)
mock_llm = importlib.util.module_from_spec(spec)
sys.modules["mock_llm_app"] = mock_llm
spec.loader.exec_module(mock_llm)


def test_navigate_task_sequence():
    task = "navigate to zone STAGING and dock"
    assert mock_llm.next_tool_call(task, []) == {"name": "navigate_to", "args": {"zone": "STAGING"}}
    assert mock_llm.next_tool_call(task, ["navigate_to"]) == {"name": "dock", "args": {}}
    assert mock_llm.next_tool_call(task, ["navigate_to", "dock"]) is None


def test_pick_place_sequence():
    task = "pick pallet P-42 and place onto amr-1"
    assert mock_llm.next_tool_call(task, []) == {"name": "pick", "args": {"pallet_id": "P-42"}}
    assert mock_llm.next_tool_call(task, ["pick"]) == {
        "name": "place",
        "args": {"location": "amr-1"},
    }
    assert mock_llm.next_tool_call(task, ["pick", "place"]) is None


def test_unknown_task_is_safe():
    assert mock_llm.next_tool_call("juggle chainsaws", [])["name"] == "get_pose"


def test_determinism():
    task = "navigate to zone A"
    calls = [mock_llm.next_tool_call(task, []) for _ in range(10)]
    assert all(c == calls[0] for c in calls)


def test_canned_plan_shape():
    plan = mock_llm.canned_plan("Move pallet P-42 from rack A3 to staging")
    import json

    steps = json.loads(plan["content"])["steps"]
    assert [s["robot"] for s in steps] == ["amr-1", "arm-1", "amr-1"]
