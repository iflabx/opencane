from types import SimpleNamespace

from opencane.bus.events import OutboundMessage
from opencane.bus.queue import MessageBus
from opencane.channels.base import BaseChannel


class _DummyChannel(BaseChannel):
    name = "dummy"

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None

    async def send(self, msg: OutboundMessage) -> None:
        del msg
        return None


def test_is_allowed_requires_exact_match_without_token_splitting() -> None:
    channel = _DummyChannel(SimpleNamespace(allow_from=["allow@email.com"]), MessageBus())

    assert channel.is_allowed("allow@email.com") is True
    assert channel.is_allowed("attacker|allow@email.com") is False


def test_is_allowed_wildcard_allows_all_senders() -> None:
    channel = _DummyChannel(SimpleNamespace(allow_from=["*"]), MessageBus())
    assert channel.is_allowed("anyone") is True


def test_is_allowed_empty_allowlist_keeps_backward_compatible_open_access() -> None:
    channel = _DummyChannel(SimpleNamespace(allow_from=[]), MessageBus())
    assert channel.is_allowed("someone") is True
