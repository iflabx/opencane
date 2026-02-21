"""Tool domain policy manager for channel-aware routing and recursion guard."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class ToolPolicy:
    """One tool policy entry."""

    domain: str
    allowed_channels: set[str]
    allow_system: bool
    max_calls_per_turn: int


class ToolDomainManager:
    """Manages tool domains and per-context execution constraints."""

    def __init__(self) -> None:
        self._policies: dict[str, ToolPolicy] = {}

    def register_tool(
        self,
        name: str,
        *,
        domain: str,
        allowed_channels: set[str] | None = None,
        allow_system: bool = False,
        max_calls_per_turn: int = 0,
    ) -> None:
        tool_name = str(name or "").strip()
        if not tool_name:
            return
        self._policies[tool_name] = ToolPolicy(
            domain=str(domain or "server_tools"),
            allowed_channels={str(x).strip() for x in (allowed_channels or {"cli"}) if str(x).strip()},
            allow_system=bool(allow_system),
            max_calls_per_turn=max(0, int(max_calls_per_turn)),
        )

    def register_mcp_tools(self, tool_names: list[str]) -> None:
        for name in tool_names:
            text = str(name or "").strip()
            if not text or not text.startswith("mcp_"):
                continue
            if text in self._policies:
                continue
            self.register_tool(
                text,
                domain="mcp_tools",
                allowed_channels={"cli", "hardware"},
                allow_system=False,
                max_calls_per_turn=0,
            )

    def allowed_tool_names(
        self,
        available_tools: list[str] | set[str],
        *,
        channel: str,
        is_system: bool,
        explicit_allowlist: set[str] | None = None,
    ) -> set[str]:
        available = {str(x).strip() for x in available_tools if str(x).strip()}
        if explicit_allowlist is not None:
            allow = {str(x).strip() for x in explicit_allowlist if str(x).strip()}
            allowed_explicit: set[str] = set()
            for name in available:
                if name not in allow:
                    continue
                ok, _ = self.can_execute(
                    name,
                    channel=channel,
                    is_system=is_system,
                    call_counts={},
                    enforce_channel_policy=True,
                )
                if ok:
                    allowed_explicit.add(name)
            return allowed_explicit

        allowed: set[str] = set()
        for name in available:
            ok, _ = self.can_execute(
                name,
                channel=channel,
                is_system=is_system,
                call_counts={},
                enforce_channel_policy=True,
            )
            if ok:
                allowed.add(name)
        return allowed

    def can_execute(
        self,
        name: str,
        *,
        channel: str,
        is_system: bool,
        call_counts: dict[str, int],
        enforce_channel_policy: bool = True,
    ) -> tuple[bool, str]:
        policy = self._policy_for(name)
        if enforce_channel_policy:
            if is_system and not policy.allow_system:
                return False, "system_not_allowed"
            if policy.allowed_channels and channel not in policy.allowed_channels:
                return False, f"channel_not_allowed:{channel}"
        limit = int(policy.max_calls_per_turn)
        if limit > 0 and int(call_counts.get(name, 0)) >= limit:
            return False, "call_limit_exceeded"
        return True, ""

    def policy_snapshot(self) -> dict[str, dict[str, object]]:
        output: dict[str, dict[str, object]] = {}
        for name, policy in self._policies.items():
            output[name] = {
                "domain": policy.domain,
                "allowed_channels": sorted(policy.allowed_channels),
                "allow_system": policy.allow_system,
                "max_calls_per_turn": policy.max_calls_per_turn,
            }
        return output

    def _policy_for(self, name: str) -> ToolPolicy:
        tool_name = str(name or "").strip()
        existing = self._policies.get(tool_name)
        if existing is not None:
            return existing
        if tool_name.startswith("mcp_"):
            return ToolPolicy(
                domain="mcp_tools",
                allowed_channels={"cli", "hardware"},
                allow_system=False,
                max_calls_per_turn=0,
            )
        return ToolPolicy(
            domain="server_tools",
            allowed_channels={"cli"},
            allow_system=False,
            max_calls_per_turn=0,
        )
