"""Driver interface: the seam between robot logic and actuation.

SimDriver actuates the warehouse-world sim. LeRobotDriver (M10) will actuate a
real SO-101 arm through the same interface — the point of the demo is that
nothing above this line changes when the actuator becomes real.
"""

from abc import ABC, abstractmethod
from typing import Any

import httpx


class Driver(ABC):
    @abstractmethod
    async def read_state(self) -> dict[str, Any]:
        """Sensor read: robot's own state + locally-sensed environment."""

    @abstractmethod
    async def navigate(self, zone: str) -> dict[str, Any]: ...

    @abstractmethod
    async def dock(self) -> dict[str, Any]: ...

    @abstractmethod
    async def pick(self, pallet_id: str) -> dict[str, Any]: ...

    @abstractmethod
    async def place(self, location: str) -> dict[str, Any]: ...

    @abstractmethod
    async def set_field(self, **fields: Any) -> dict[str, Any]:
        """Low-level parameter write (estop flag, limits, mode)."""


class SimDriver(Driver):
    def __init__(self, robot_id: str, world_url: str):
        self.robot_id = robot_id
        self.world_url = world_url.rstrip("/")
        self._client = httpx.AsyncClient(timeout=5.0)

    async def read_state(self) -> dict[str, Any]:
        r = await self._client.get(f"{self.world_url}/robots/{self.robot_id}")
        r.raise_for_status()
        return r.json()

    async def _post(self, action: str, body: dict | None = None) -> dict[str, Any]:
        r = await self._client.post(
            f"{self.world_url}/robots/{self.robot_id}/{action}", json=body or {}
        )
        if r.status_code >= 400:
            return {"ok": False, "error": r.json().get("detail", r.text)}
        return r.json()

    async def navigate(self, zone: str) -> dict[str, Any]:
        return await self._post("navigate", {"zone": zone})

    async def dock(self) -> dict[str, Any]:
        return await self._post("dock")

    async def pick(self, pallet_id: str) -> dict[str, Any]:
        return await self._post("pick", {"pallet_id": pallet_id})

    async def place(self, location: str) -> dict[str, Any]:
        return await self._post("place", {"location": location})

    async def set_field(self, **fields: Any) -> dict[str, Any]:
        r = await self._client.patch(f"{self.world_url}/robots/{self.robot_id}", json=fields)
        r.raise_for_status()
        return r.json()
