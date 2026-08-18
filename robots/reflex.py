"""Reflex tier: in-process safety interlocks. NEVER touches the network.

Decisions are made against the locally-cached sensor snapshot (refreshed by a
background sensor loop — the sim equivalent of onboard lidar/safety PLC).
The gateway enforces the same rules as policy (belt + suspenders); this layer
exists so the machine is safe even if every network cable is cut.

Every decision is timed; verify-m1 asserts the p99 stays under 10ms.
"""

import time
from dataclasses import dataclass, field


@dataclass
class ReflexDecision:
    allowed: bool
    reason: str
    decision_us: float  # microseconds spent deciding — the Speed pillar receipt


@dataclass
class ReflexTier:
    robot_id: str
    estopped: bool = False
    safety_stop_enabled: bool = True
    snapshot: dict = field(default_factory=dict)  # last sensor read (humans, zone, ...)
    timings_us: list[float] = field(default_factory=list)

    def _decide(self, allowed: bool, reason: str, t0: float) -> ReflexDecision:
        us = (time.perf_counter() - t0) * 1e6
        self.timings_us.append(us)
        self.timings_us = self.timings_us[-1000:]
        return ReflexDecision(allowed, reason, us)

    def check_motion(self, target_zone: str | None = None) -> ReflexDecision:
        """Gate ANY motion command. Pure in-process logic on cached sensors."""
        t0 = time.perf_counter()
        if self.estopped:
            return self._decide(False, "EMERGENCY_STOP engaged", t0)
        humans = self.snapshot.get("humans", {})
        if target_zone is not None and self.safety_stop_enabled and humans.get(target_zone):
            return self._decide(False, f"reflex refusal: human present in zone {target_zone}", t0)
        current = self.snapshot.get("zone")
        if self.safety_stop_enabled and current and humans.get(current):
            return self._decide(
                False, f"reflex refusal: human present in current zone {current}", t0
            )
        return self._decide(True, "clear", t0)

    def emergency_stop(self) -> ReflexDecision:
        """E-stop is a local flag write — no I/O on the decision path."""
        t0 = time.perf_counter()
        self.estopped = True
        return self._decide(True, "EMERGENCY_STOP engaged (in-process)", t0)

    def clear_estop(self) -> None:
        self.estopped = False
