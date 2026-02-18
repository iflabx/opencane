"""Adapter base contract for hardware protocol integrations."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator

from nanobot.hardware.protocol import CanonicalEnvelope


class GatewayAdapter(ABC):
    """Abstract adapter contract used by the hardware runtime."""

    name: str = "base"
    transport: str = "unknown"

    @abstractmethod
    async def start(self) -> None:
        """Start adapter resources and begin ingesting device traffic."""

    @abstractmethod
    async def stop(self) -> None:
        """Stop adapter resources."""

    @abstractmethod
    async def recv_events(self) -> AsyncIterator[CanonicalEnvelope]:
        """Yield canonical events from connected devices."""

    @abstractmethod
    async def send_command(self, cmd: CanonicalEnvelope) -> None:
        """Send a canonical command to the target device."""

    async def ack(self, device_id: str, session_id: str, seq: int) -> None:
        """Optional explicit ACK helper."""
        from nanobot.hardware.protocol import DeviceCommandType, make_command

        await self.send_command(
            make_command(
                DeviceCommandType.ACK,
                device_id=device_id,
                session_id=session_id,
                seq=seq,
                payload={"ack_seq": seq},
            )
        )

    async def close_session(self, device_id: str, session_id: str, reason: str) -> None:
        """Optional close helper."""
        from nanobot.hardware.protocol import DeviceCommandType, make_command

        await self.send_command(
            make_command(
                DeviceCommandType.CLOSE,
                device_id=device_id,
                session_id=session_id,
                payload={"reason": reason},
            )
        )

