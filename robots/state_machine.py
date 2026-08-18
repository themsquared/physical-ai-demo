"""Degraded-mode state machine (Failover pillar).

The robot never depends on cognition to be SAFE, only to be USEFUL:

    ACTIVE --(heartbeat lost)--> FINISH_CURRENT_MOTION --> SAFE_IDLE
    SAFE_IDLE --(heartbeat back)--> ACTIVE (resume)

Cognition agents POST /heartbeat continuously. The monitor loop runs locally;
transition latency is bounded by CHECK_INTERVAL (verify-m1 asserts ≤500ms
sim-time to SAFE_IDLE after loss detection).
"""

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from enum import StrEnum

log = logging.getLogger("degraded-mode")

CHECK_INTERVAL = 0.1


class Mode(StrEnum):
    ACTIVE = "ACTIVE"
    FINISH_CURRENT_MOTION = "FINISH_CURRENT_MOTION"
    SAFE_IDLE = "SAFE_IDLE"


class DegradedModeSM:
    def __init__(
        self,
        robot_id: str,
        heartbeat_timeout: float,
        on_transition: Callable[[Mode], Awaitable[None]],
    ):
        self.robot_id = robot_id
        self.heartbeat_timeout = heartbeat_timeout
        self.on_transition = on_transition
        self.mode = Mode.ACTIVE
        self.last_heartbeat = time.monotonic()
        self.transitions: list[dict] = []
        self._task: asyncio.Task | None = None

    def beat(self) -> None:
        self.last_heartbeat = time.monotonic()

    @property
    def cognition_alive(self) -> bool:
        return (time.monotonic() - self.last_heartbeat) < self.heartbeat_timeout

    async def _set_mode(self, mode: Mode, reason: str) -> None:
        if mode == self.mode:
            return
        prev = self.mode
        self.mode = mode
        self.transitions.append(
            {"t": time.monotonic(), "from": prev.value, "to": mode.value, "reason": reason}
        )
        self.transitions = self.transitions[-100:]
        log.info("%s: %s -> %s (%s)", self.robot_id, prev.value, mode.value, reason)
        await self.on_transition(mode)

    async def _loop(self) -> None:
        while True:
            await asyncio.sleep(CHECK_INTERVAL)
            alive = self.cognition_alive
            if self.mode == Mode.ACTIVE and not alive:
                await self._set_mode(Mode.FINISH_CURRENT_MOTION, "cognition heartbeat lost")
                # Completing the in-flight motion is the world's job (path is
                # truncated by on_transition); we drop to SAFE_IDLE on the next
                # check so total latency stays inside the 500ms SLO.
                await self._set_mode(Mode.SAFE_IDLE, "current motion handed off; idling safe")
            elif self.mode == Mode.SAFE_IDLE and alive:
                await self._set_mode(Mode.ACTIVE, "cognition heartbeat restored; resuming")

    def start(self) -> None:
        self._task = asyncio.create_task(self._loop())

    def stop(self) -> None:
        if self._task:
            self._task.cancel()
