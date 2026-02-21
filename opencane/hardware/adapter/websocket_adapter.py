"""WebSocket adapter for device event ingress."""

from __future__ import annotations

import asyncio
import base64
import json
from urllib.parse import parse_qs, urlparse

from loguru import logger
from websockets.exceptions import ConnectionClosed
from websockets.legacy.server import (
    WebSocketServer,
    WebSocketServerProtocol,
    serve,
)

from opencane.hardware.adapter.base import GatewayAdapter
from opencane.hardware.protocol import CanonicalEnvelope, DeviceEventType, make_event

_SENTINEL = object()


class WebSocketAdapter(GatewayAdapter):
    """Raw WebSocket ingress mapped to canonical envelopes."""

    name = "websocket"
    transport = "ws"

    def __init__(
        self,
        *,
        host: str = "0.0.0.0",
        port: int = 18791,
        require_token: bool = False,
        token: str = "",
        packet_magic: int = 0xA1,
    ) -> None:
        self.host = host
        self.port = port
        self.require_token = require_token
        self.token = token
        self.packet_magic = packet_magic
        self._running = False
        self._queue: asyncio.Queue[CanonicalEnvelope | object] = asyncio.Queue()
        self._server: WebSocketServer | None = None
        self._device_sockets: dict[str, WebSocketServerProtocol] = {}
        self._session_sockets: dict[tuple[str, str], WebSocketServerProtocol] = {}

    async def start(self) -> None:
        self._running = True
        self._server = await serve(self._handle_connection, self.host, self.port)
        logger.info(f"Hardware WS adapter listening on ws://{self.host}:{self.port}")

    async def stop(self) -> None:
        self._running = False
        for ws in list(self._device_sockets.values()):
            try:
                await ws.close()
            except Exception:
                pass
        self._device_sockets.clear()
        self._session_sockets.clear()
        if self._server:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
        await self._queue.put(_SENTINEL)

    async def recv_events(self):
        while self._running:
            item = await self._queue.get()
            if item is _SENTINEL:
                break
            yield item

    async def send_command(self, cmd: CanonicalEnvelope) -> None:
        ws = self._session_sockets.get((cmd.device_id, cmd.session_id))
        if ws is None:
            ws = self._device_sockets.get(cmd.device_id)
        if ws is None:
            logger.warning(
                f"WS adapter cannot find socket for {cmd.device_id}/{cmd.session_id}"
            )
            return
        try:
            await ws.send(json.dumps(cmd.to_dict(), ensure_ascii=False))
        except Exception as e:
            logger.warning(f"WS adapter failed to send command: {e}")

    async def _handle_connection(self, websocket: WebSocketServerProtocol, path: str) -> None:
        query = parse_qs(urlparse(path).query)
        default_device_id = (query.get("device_id") or query.get("device-id") or [""])[0]
        default_session_id = (query.get("session_id") or query.get("session-id") or [""])[0]
        token = (query.get("token") or query.get("authorization") or [""])[0]
        if token.startswith("Bearer "):
            token = token[7:]

        if self.require_token and self.token and token != self.token:
            await websocket.close(code=4401, reason="unauthorized")
            return

        device_id = default_device_id
        session_id = default_session_id
        if device_id:
            self._device_sockets[device_id] = websocket
        if device_id and session_id:
            self._session_sockets[(device_id, session_id)] = websocket

        try:
            async for message in websocket:
                if isinstance(message, bytes):
                    if not device_id:
                        continue
                    event = self._parse_binary_audio(message, device_id, session_id)
                    await self._queue.put(event)
                    continue

                data = json.loads(message)
                env = CanonicalEnvelope.from_dict(
                    data,
                    default_device_id=device_id,
                    default_session_id=session_id,
                )
                if env.type == DeviceEventType.HELLO:
                    device_id = env.device_id
                    session_id = env.session_id
                    self._device_sockets[device_id] = websocket
                    self._session_sockets[(device_id, session_id)] = websocket
                await self._queue.put(env)
        except ConnectionClosed:
            pass
        except Exception as e:
            logger.warning(f"WS adapter connection error: {e}")
        finally:
            if device_id and self._device_sockets.get(device_id) is websocket:
                self._device_sockets.pop(device_id, None)
            if device_id and session_id:
                if self._session_sockets.get((device_id, session_id)) is websocket:
                    self._session_sockets.pop((device_id, session_id), None)

    def _parse_binary_audio(
        self,
        packet: bytes,
        device_id: str,
        session_id: str,
    ) -> CanonicalEnvelope:
        if len(packet) >= 16 and packet[0] == self.packet_magic:
            seq = int.from_bytes(packet[4:8], "big")
            ts = int.from_bytes(packet[8:12], "big")
            payload_len = int.from_bytes(packet[12:16], "big")
            audio = packet[16 : 16 + payload_len] if payload_len > 0 else packet[16:]
            return make_event(
                DeviceEventType.AUDIO_CHUNK,
                device_id=device_id,
                session_id=session_id or f"{device_id}-default",
                seq=seq,
                payload={
                    "audio_b64": base64.b64encode(audio).decode("ascii"),
                    "encoding": "opus",
                    "timestamp": ts,
                },
            )

        return make_event(
            DeviceEventType.AUDIO_CHUNK,
            device_id=device_id,
            session_id=session_id or f"{device_id}-default",
            payload={
                "audio_b64": base64.b64encode(packet).decode("ascii"),
                "encoding": "binary",
            },
        )
