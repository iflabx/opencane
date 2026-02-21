"""Memory providers for file memory and optional lifelog retrieval memory."""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Any

from opencane.utils.helpers import ensure_dir


def _shorten(text: str, max_chars: int) -> str:
    value = str(text or "").strip()
    if len(value) <= max_chars:
        return value
    return value[: max(0, max_chars - 3)].rstrip() + "..."


class MemoryStore:
    """Layered memory store on local filesystem."""

    def __init__(self, workspace: Path):
        self.memory_dir = ensure_dir(workspace / "memory")
        self.memory_file = self.memory_dir / "MEMORY.md"
        self.history_file = self.memory_dir / "HISTORY.md"
        self.profile_file = self.memory_dir / "PROFILE.json"
        self.semantic_file = self.memory_dir / "SEMANTIC.json"
        self.episodic_file = self.memory_dir / "EPISODIC.jsonl"

    def read_long_term(self) -> str:
        if self.memory_file.exists():
            return self.memory_file.read_text(encoding="utf-8")
        return ""

    def write_long_term(self, content: str) -> None:
        self.memory_file.write_text(content, encoding="utf-8")

    def append_history(self, entry: str) -> None:
        with open(self.history_file, "a", encoding="utf-8") as f:
            f.write(entry.rstrip() + "\n\n")

    def get_memory_context(self) -> str:
        long_term = self.read_long_term()
        return f"## Long-term Memory\n{long_term}" if long_term else ""

    def read_profile(self) -> dict[str, Any]:
        return self._read_json(self.profile_file, default={})

    def update_profile(
        self,
        *,
        channel: str,
        chat_id: str,
        session_key: str,
    ) -> None:
        data = self.read_profile()
        now_ms = _now_ms()
        data["updated_at_ms"] = now_ms

        channels = data.get("channels")
        channels_map = channels if isinstance(channels, dict) else {}
        channel_key = str(channel or "").strip() or "unknown"
        channel_count = int(channels_map.get(channel_key, 0)) + 1
        channels_map[channel_key] = channel_count
        data["channels"] = channels_map

        chats = data.get("chats")
        chats_map = chats if isinstance(chats, dict) else {}
        chat_key = str(chat_id or "").strip() or "unknown"
        chats_map[chat_key] = {
            "count": int((chats_map.get(chat_key) or {}).get("count", 0)) + 1
            if isinstance(chats_map.get(chat_key), dict)
            else 1,
            "last_session_key": str(session_key or ""),
            "updated_at_ms": now_ms,
        }
        data["chats"] = chats_map
        self._write_json(self.profile_file, data)

    def list_semantic_facts(self, *, limit: int = 200) -> list[dict[str, Any]]:
        data = self._read_json(self.semantic_file, default={})
        facts = data.get("facts")
        if not isinstance(facts, list):
            return []
        output = [item for item in facts if isinstance(item, dict)]
        output.sort(key=lambda item: int(item.get("updated_at_ms") or 0), reverse=True)
        return output[: max(1, int(limit))]

    def upsert_semantic_fact(
        self,
        *,
        value: str,
        fact_type: str,
        source: str,
        max_items: int,
    ) -> None:
        text = str(value or "").strip()
        if not text:
            return
        now_ms = _now_ms()
        facts = self.list_semantic_facts(limit=max(10, int(max_items) * 2))
        key = _normalize_fact_key(text)
        replaced = False
        for item in facts:
            if str(item.get("key") or "") == key:
                item["value"] = text
                item["type"] = str(fact_type or "fact")
                item["source"] = str(source or "user")
                item["updated_at_ms"] = now_ms
                replaced = True
                break
        if not replaced:
            facts.append(
                {
                    "key": key,
                    "value": text,
                    "type": str(fact_type or "fact"),
                    "source": str(source or "user"),
                    "updated_at_ms": now_ms,
                }
            )
        facts.sort(key=lambda item: int(item.get("updated_at_ms") or 0), reverse=True)
        facts = facts[: max(1, int(max_items))]
        self._write_json(self.semantic_file, {"facts": facts, "updated_at_ms": now_ms})

    def append_episodic(
        self,
        *,
        entry: dict[str, Any],
        max_items: int,
        ttl_days: int,
    ) -> None:
        items = self.list_episodic(limit=max(10, int(max_items) * 2))
        row = dict(entry or {})
        row["ts"] = int(row.get("ts") or _now_ms())
        items.append(row)

        cutoff_ms = 0
        if int(ttl_days) > 0:
            cutoff_ms = _now_ms() - int(ttl_days) * 24 * 60 * 60 * 1000
        if cutoff_ms > 0:
            items = [item for item in items if int(item.get("ts") or 0) >= cutoff_ms]
        items.sort(key=lambda item: int(item.get("ts") or 0))
        if len(items) > max(1, int(max_items)):
            items = items[-max(1, int(max_items)) :]

        lines = [json.dumps(item, ensure_ascii=False) for item in items if isinstance(item, dict)]
        self.episodic_file.write_text("\n".join(lines), encoding="utf-8")

    def list_episodic(self, *, limit: int = 500) -> list[dict[str, Any]]:
        if not self.episodic_file.exists():
            return []
        output: list[dict[str, Any]] = []
        for raw in self.episodic_file.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
            except Exception:
                continue
            if isinstance(item, dict):
                output.append(item)
        output.sort(key=lambda item: int(item.get("ts") or 0), reverse=True)
        return output[: max(1, int(limit))]

    @staticmethod
    def _read_json(path: Path, *, default: dict[str, Any]) -> dict[str, Any]:
        if not path.exists():
            return dict(default)
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return dict(default)
        return dict(raw) if isinstance(raw, dict) else dict(default)

    @staticmethod
    def _write_json(path: Path, data: dict[str, Any]) -> None:
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


class UnifiedMemoryProvider:
    """Unified memory provider with layered local memory + optional lifelog retrieval."""

    def __init__(
        self,
        workspace: Path,
        *,
        lifelog_service: Any | None = None,
        retrieval_top_k: int = 3,
        retrieval_timeout_s: float = 2.0,
        max_hit_chars: int = 220,
        local_semantic_top_k: int = 2,
        local_episodic_top_k: int = 2,
        episodic_max_items: int = 1500,
        episodic_ttl_days: int = 90,
        semantic_max_items: int = 500,
    ) -> None:
        self.file_store = MemoryStore(workspace)
        self.lifelog = lifelog_service
        self.retrieval_top_k = max(1, int(retrieval_top_k))
        self.retrieval_timeout_s = max(0.2, float(retrieval_timeout_s))
        self.max_hit_chars = max(80, int(max_hit_chars))
        self.local_semantic_top_k = max(1, int(local_semantic_top_k))
        self.local_episodic_top_k = max(1, int(local_episodic_top_k))
        self.episodic_max_items = max(20, int(episodic_max_items))
        self.episodic_ttl_days = max(1, int(episodic_ttl_days))
        self.semantic_max_items = max(20, int(semantic_max_items))

    def read_long_term(self) -> str:
        return self.file_store.read_long_term()

    def write_long_term(self, content: str) -> None:
        self.file_store.write_long_term(content)

    def append_history(self, entry: str) -> None:
        self.file_store.append_history(entry)

    def get_file_memory_context(self) -> str:
        return self.file_store.get_memory_context()

    def record_turn(
        self,
        *,
        session_key: str,
        channel: str,
        chat_id: str,
        user_text: str,
        assistant_text: str,
        tools_used: list[str] | None = None,
    ) -> None:
        self.file_store.update_profile(
            channel=channel,
            chat_id=chat_id,
            session_key=session_key,
        )
        self.file_store.append_episodic(
            entry={
                "ts": _now_ms(),
                "session_key": str(session_key or ""),
                "channel": str(channel or ""),
                "chat_id": str(chat_id or ""),
                "user": _shorten(str(user_text or ""), 500),
                "assistant": _shorten(str(assistant_text or ""), 500),
                "tools_used": [str(item) for item in (tools_used or []) if str(item).strip()],
            },
            max_items=self.episodic_max_items,
            ttl_days=self.episodic_ttl_days,
        )
        for fact_type, fact_value in _extract_semantic_facts(str(user_text or "")):
            self.file_store.upsert_semantic_fact(
                value=fact_value,
                fact_type=fact_type,
                source="user_text",
                max_items=self.semantic_max_items,
            )

    async def retrieve_context(
        self,
        *,
        query: str,
        session_key: str,
        channel: str,
        chat_id: str,
    ) -> str:
        query = str(query or "").strip()
        if not query:
            return ""

        candidates = self._candidate_session_ids(
            session_key=session_key,
            channel=channel,
            chat_id=chat_id,
        )
        sections: list[str] = []

        semantic = self._retrieve_local_semantic(query)
        if semantic:
            sections.append(semantic)

        episodic = self._retrieve_local_episodic(query, candidates=candidates)
        if episodic:
            sections.append(episodic)

        lifelog = await self._retrieve_lifelog_context(query, candidates=candidates)
        if lifelog:
            sections.append(lifelog)

        return "\n\n".join(section.strip() for section in sections if section.strip()).strip()

    def build_prompt_memory_context(
        self,
        *,
        file_memory_context: str,
        retrieval_context: str,
    ) -> str:
        parts = [x for x in [file_memory_context.strip(), retrieval_context.strip()] if x]
        return "\n\n".join(parts).strip()

    @staticmethod
    def _candidate_session_ids(
        *,
        session_key: str,
        channel: str,
        chat_id: str,
    ) -> list[str]:
        session_key = str(session_key or "").strip()
        channel = str(channel or "").strip().lower()
        chat_id = str(chat_id or "").strip()
        candidates: list[str] = []

        if channel == "hardware" and session_key.startswith("hardware:"):
            parts = session_key.split(":", 2)
            if len(parts) == 3 and parts[2].strip():
                candidates.append(parts[2].strip())

        if session_key:
            candidates.append(session_key)
        if chat_id:
            candidates.append(chat_id)

        output: list[str] = []
        seen: set[str] = set()
        for item in candidates:
            if item and item not in seen:
                seen.add(item)
                output.append(item)
        return output

    def _format_hits(self, hits: list[dict[str, Any]]) -> str:
        lines = ["## Retrieved Lifelog Memory"]
        count = 0
        for raw in hits:
            if not isinstance(raw, dict):
                continue
            count += 1
            summary = _shorten(str(raw.get("text") or raw.get("summary") or ""), self.max_hit_chars)
            metadata = raw.get("metadata")
            meta = metadata if isinstance(metadata, dict) else {}
            structured = raw.get("structured_context")
            structured_ctx = structured if isinstance(structured, dict) else {}
            session_id = str(meta.get("session_id") or "").strip()
            ts = str(meta.get("ts") or "").strip()
            score = raw.get("score")
            score_text = ""
            try:
                score_text = f"{float(score):.4f}"
            except (TypeError, ValueError):
                score_text = ""

            line = f"- [{count}] {_shorten(summary, self.max_hit_chars)}"
            lines.append(line)
            extras: list[str] = []
            if session_id:
                extras.append(f"session={session_id}")
            if ts:
                extras.append(f"ts={ts}")
            if score_text:
                extras.append(f"score={score_text}")
            if extras:
                lines.append(f"  ({', '.join(extras)})")

            actionable = str(structured_ctx.get("actionable_summary") or "").strip()
            if actionable:
                lines.append(f"  action: {_shorten(actionable, self.max_hit_chars)}")
            if count >= self.retrieval_top_k:
                break

        if count == 0:
            return ""
        return "\n".join(lines)

    async def _retrieve_lifelog_context(
        self,
        query: str,
        *,
        candidates: list[str],
    ) -> str:
        if self.lifelog is None or not hasattr(self.lifelog, "query"):
            return ""
        if not candidates:
            return ""

        for candidate in candidates:
            payload = {
                "session_id": candidate,
                "query": query,
                "top_k": self.retrieval_top_k,
                "include_context": True,
            }
            try:
                raw = await asyncio.wait_for(
                    self.lifelog.query(payload),  # type: ignore[attr-defined]
                    timeout=self.retrieval_timeout_s,
                )
            except Exception:
                continue
            if not isinstance(raw, dict) or not bool(raw.get("success")):
                continue
            hits = raw.get("hits")
            if not isinstance(hits, list) or not hits:
                continue
            formatted = self._format_hits(hits)
            if formatted:
                return formatted
        return ""

    def _retrieve_local_semantic(self, query: str) -> str:
        facts = self.file_store.list_semantic_facts(limit=max(20, self.semantic_max_items))
        if not facts:
            return ""
        scored: list[tuple[float, dict[str, Any]]] = []
        for fact in facts:
            value = str(fact.get("value") or "").strip()
            if not value:
                continue
            score = _score_text_match(query, value)
            if score <= 0:
                continue
            scored.append((score, fact))
        if not scored:
            return ""
        scored.sort(key=lambda item: item[0], reverse=True)

        lines = ["## Layered Memory (Semantic)"]
        for idx, (_, fact) in enumerate(scored[: self.local_semantic_top_k], start=1):
            value = _shorten(str(fact.get("value") or ""), self.max_hit_chars)
            fact_type = str(fact.get("type") or "fact")
            lines.append(f"- [{idx}] {value} ({fact_type})")
        return "\n".join(lines)

    def _retrieve_local_episodic(self, query: str, *, candidates: list[str]) -> str:
        records = self.file_store.list_episodic(limit=max(200, self.episodic_max_items))
        if not records:
            return ""
        candidate_set = {str(item) for item in candidates if str(item).strip()}
        scored: list[tuple[float, dict[str, Any]]] = []
        for item in records:
            session_key = str(item.get("session_key") or "")
            if candidate_set and session_key and session_key not in candidate_set:
                if not any(session_key.endswith(f":{sid}") for sid in candidate_set):
                    continue
            user = str(item.get("user") or "")
            assistant = str(item.get("assistant") or "")
            text = f"{user}\n{assistant}".strip()
            if not text:
                continue
            score = _score_text_match(query, text)
            if score <= 0:
                continue
            scored.append((score, item))
        if not scored:
            return ""
        scored.sort(key=lambda pair: pair[0], reverse=True)

        lines = ["## Layered Memory (Episodic)"]
        for idx, (_, item) in enumerate(scored[: self.local_episodic_top_k], start=1):
            user = _shorten(str(item.get("user") or ""), self.max_hit_chars // 2)
            assistant = _shorten(str(item.get("assistant") or ""), self.max_hit_chars // 2)
            ts = str(item.get("ts") or "")
            lines.append(f"- [{idx}] user={user}")
            lines.append(f"  assistant={assistant}")
            if ts:
                lines.append(f"  (ts={ts})")
        return "\n".join(lines)


def _normalize_fact_key(text: str) -> str:
    normalized = str(text or "").strip().lower()
    normalized = " ".join(normalized.split())
    return normalized[:160]


def _extract_semantic_facts(text: str) -> list[tuple[str, str]]:
    raw = str(text or "").strip()
    if not raw:
        return []
    output: list[tuple[str, str]] = []

    # Chinese patterns
    for marker, fact_type in (
        ("我喜欢", "preference_like"),
        ("我不喜欢", "preference_dislike"),
        ("我偏好", "preference_like"),
        ("叫我", "identity_name"),
        ("我是", "identity_self"),
    ):
        value = _extract_tail(raw, marker)
        if value:
            output.append((fact_type, value))

    # English patterns
    lower = raw.lower()
    for marker, fact_type in (
        ("i like ", "preference_like"),
        ("i dislike ", "preference_dislike"),
        ("i prefer ", "preference_like"),
        ("call me ", "identity_name"),
        ("my name is ", "identity_name"),
    ):
        value = _extract_tail(lower, marker)
        if value:
            output.append((fact_type, value))

    dedup: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for fact_type, value in output:
        key = (fact_type, _normalize_fact_key(value))
        if key in seen:
            continue
        seen.add(key)
        dedup.append((fact_type, value))
    return dedup[:6]


def _extract_tail(text: str, marker: str) -> str:
    if marker not in text:
        return ""
    tail = text.split(marker, 1)[1].strip()
    for token in ("。", ".", "!", "！", "?", "？", ",", "，", ";", "；", "\n"):
        if token in tail:
            tail = tail.split(token, 1)[0].strip()
    return _shorten(tail, 80)


def _score_text_match(query: str, text: str) -> float:
    q = str(query or "").strip().lower()
    t = str(text or "").strip().lower()
    if not q or not t:
        return 0.0
    score = 0.0
    if q in t:
        score += 20.0
    q_tokens = {token for token in q.split() if token}
    t_tokens = {token for token in t.split() if token}
    if q_tokens and t_tokens:
        score += float(len(q_tokens.intersection(t_tokens)) * 4)
    q_chars = {ch for ch in q if not ch.isspace()}
    t_chars = {ch for ch in t if not ch.isspace()}
    if q_chars and t_chars:
        score += float(len(q_chars.intersection(t_chars)))
    return score


def _now_ms() -> int:
    return int(time.time() * 1000)
