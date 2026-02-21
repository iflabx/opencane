"""Digital task service for async execution, persistence and hardware push."""

from __future__ import annotations

import asyncio
import time
import uuid
from pathlib import Path
from typing import Any, Awaitable, Callable

from loguru import logger

from opencane.config.schema import Config
from opencane.storage import SQLiteDigitalTaskStore

TaskExecutor = Callable[[str, str], Awaitable[Any]]
TaskStatusCallback = Callable[[dict[str, Any]], Awaitable[bool | None]]

_FINAL_STATUSES = {"success", "failed", "timeout", "canceled"}
_RUNNABLE_STATUSES = {"pending", "running"}
_NO_TOOL_USED = "NO_TOOL_USED"
_MCP_FALLBACK_TOKEN = "MCP_FALLBACK_REQUIRED"


class DigitalTaskService:
    """Application service for long-running digital tasks."""

    def __init__(
        self,
        *,
        store: SQLiteDigitalTaskStore,
        executor: TaskExecutor,
        default_timeout_seconds: int = 120,
        max_concurrent_tasks: int = 2,
        status_callback: TaskStatusCallback | None = None,
        status_retry_count: int = 2,
        status_retry_backoff_ms: int = 300,
    ) -> None:
        self.store = store
        self.executor = executor
        self.default_timeout_seconds = max(1, int(default_timeout_seconds))
        self.max_concurrent_tasks = max(1, int(max_concurrent_tasks))
        self.status_callback = status_callback
        self.status_retry_count = max(0, int(status_retry_count))
        self.status_retry_backoff_ms = max(0, int(status_retry_backoff_ms))
        self._running_tasks: dict[str, asyncio.Task[None]] = {}
        self._cancel_reasons: dict[str, str] = {}
        self._semaphore = asyncio.Semaphore(self.max_concurrent_tasks)
        self._push_contexts: dict[str, dict[str, Any]] = {}
        self._active_task_by_device: dict[str, str] = {}

    @classmethod
    def from_config(
        cls,
        config: Config,
        *,
        agent_loop: Any,
    ) -> "DigitalTaskService":
        sqlite_path = Path(config.digital_task.sqlite_path).expanduser()
        store = SQLiteDigitalTaskStore(sqlite_path)

        async def _executor(goal: str, session_id: str) -> dict[str, Any]:
            tool_names = await agent_loop.list_registered_tools(connect_mcp=True)
            mcp_tools = sorted(name for name in tool_names if name.startswith("mcp_"))
            fallback_tools = set(mcp_tools) | {"web_search", "web_fetch", "exec"}

            # Stage 1: explicit MCP-only execution.
            if mcp_tools:
                mcp_prompt = _build_mcp_prompt(goal)
                mcp_output = await agent_loop.process_direct(
                    mcp_prompt,
                    session_key=f"hardware:{session_id}:digital",
                    channel="hardware",
                    chat_id=session_id,
                    allowed_tool_names=set(mcp_tools),
                    require_tool_use=True,
                )
                if not _should_fallback_from_mcp(mcp_output):
                    return {
                        "text": str(mcp_output or "").strip(),
                        "execution_path": "mcp",
                        "allowed_tools": mcp_tools,
                    }

            # Stage 2: explicit web/exec fallback with MCP still available.
            fallback_prompt = _build_fallback_prompt(goal)
            fallback_output = await agent_loop.process_direct(
                fallback_prompt,
                session_key=f"hardware:{session_id}:digital",
                channel="hardware",
                chat_id=session_id,
                allowed_tool_names=fallback_tools,
                require_tool_use=True,
            )
            if str(fallback_output or "").strip() == _NO_TOOL_USED:
                fallback_output = await agent_loop.process_direct(
                    goal,
                    session_key=f"hardware:{session_id}:digital",
                    channel="hardware",
                    chat_id=session_id,
                    allowed_tool_names=fallback_tools,
                    require_tool_use=False,
                )
            return {
                "text": str(fallback_output or "").strip(),
                "execution_path": "web_exec_fallback",
                "allowed_tools": sorted(fallback_tools),
            }

        logger.info(
            "Digital task service ready "
            f"sqlite={sqlite_path} timeout={config.digital_task.default_timeout_seconds}s "
            f"concurrency={config.digital_task.max_concurrent_tasks}"
        )
        return cls(
            store=store,
            executor=_executor,
            default_timeout_seconds=config.digital_task.default_timeout_seconds,
            max_concurrent_tasks=config.digital_task.max_concurrent_tasks,
            status_retry_count=config.digital_task.status_retry_count,
            status_retry_backoff_ms=config.digital_task.status_retry_backoff_ms,
        )

    def set_status_callback(self, callback: TaskStatusCallback | None) -> None:
        self.status_callback = callback

    def stats_snapshot(self, *, session_id: str | None = None) -> dict[str, Any]:
        return self.store.task_stats(session_id=session_id)

    async def stats(self, payload: dict[str, Any]) -> dict[str, Any]:
        session_id = str(payload.get("session_id") or payload.get("sessionId") or "").strip() or None
        stats = self.stats_snapshot(session_id=session_id)
        return {"success": True, "session_id": session_id, "stats": stats}

    async def shutdown(self) -> None:
        pending = [task for task in self._running_tasks.values() if not task.done()]
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        self._running_tasks.clear()
        self._cancel_reasons.clear()
        self._push_contexts.clear()
        self._active_task_by_device.clear()
        self.store.close()

    async def recover_unfinished_tasks(self, *, limit: int = 200) -> int:
        """Recover pending/running tasks after process restart."""
        tasks = self.store.list_unfinished_tasks(limit=max(1, int(limit)))
        recovered = 0
        for item in tasks:
            task_id = str(item.get("task_id") or "")
            if not task_id or task_id in self._running_tasks:
                continue
            status = str(item.get("status") or "")
            if status == "running":
                self.store.update_task_if_status(
                    task_id,
                    expected_statuses={"running"},
                    status="pending",
                    error="recovered_after_restart",
                )
                item = self.store.get_task(task_id) or item
            if str(item.get("status") or "") != "pending":
                continue
            push_context = self._recover_push_context(item, task_id=task_id, session_id=str(item.get("session_id") or ""))
            if push_context:
                self._push_contexts[task_id] = push_context
                if device_id := str(push_context.get("device_id") or "").strip():
                    self._active_task_by_device[device_id] = task_id
            self._append_step(task_id, stage="recovered", status="ok", message="task recovered after restart")
            timeout_seconds = _to_int(item.get("timeout_seconds"), self.default_timeout_seconds)
            self._running_tasks[task_id] = asyncio.create_task(
                self._run_task(
                    task_id=task_id,
                    session_id=str(item.get("session_id") or ""),
                    goal=str(item.get("goal") or ""),
                    timeout_seconds=max(1, timeout_seconds),
                )
            )
            recovered += 1
        return recovered

    async def execute(self, payload: dict[str, Any]) -> dict[str, Any]:
        goal = str(payload.get("goal") or payload.get("prompt") or "").strip()
        if not goal:
            return {"success": False, "error": "goal is required", "error_code": "bad_request"}

        task_id = str(payload.get("task_id") or payload.get("taskId") or "").strip() or _new_task_id()
        session_id = str(payload.get("session_id") or payload.get("sessionId") or "").strip()
        if not session_id:
            session_id = f"digital-{task_id}"
        timeout_seconds = _to_int(
            payload.get("timeout_seconds") or payload.get("timeout"),
            self.default_timeout_seconds,
        )
        timeout_seconds = max(1, timeout_seconds)

        existing = self.store.get_task(task_id)
        if existing:
            return {"success": False, "error": "task already exists", "error_code": "conflict", "task": existing}

        steps = payload.get("steps")
        if not isinstance(steps, list):
            steps = []
        push_context = self._build_push_context(payload, task_id=task_id, session_id=session_id)
        if push_context:
            self._push_contexts[task_id] = push_context
            if push_context.get("interrupt_previous"):
                await self._interrupt_previous_for_device(push_context, current_task_id=task_id)
            if device_id := str(push_context.get("device_id") or "").strip():
                self._active_task_by_device[device_id] = task_id

        self.store.create_task(
            task_id=task_id,
            session_id=session_id,
            goal=goal,
            status="pending",
            steps=steps,
            result={},
            error="",
            timeout_seconds=timeout_seconds,
            push_context=push_context,
        )
        self._append_step(task_id, stage="accepted", status="ok", message="task accepted")
        self._running_tasks[task_id] = asyncio.create_task(
            self._run_task(
                task_id=task_id,
                session_id=session_id,
                goal=goal,
                timeout_seconds=timeout_seconds,
            )
        )
        task = self.store.get_task(task_id) or {"task_id": task_id, "status": "pending"}
        await self._emit_status_update(
            task_id,
            status="pending",
            message="任务已创建，开始处理。",
            event="accepted",
            task=task,
        )
        return {"success": True, "accepted": True, "task": task}

    async def get_task(self, task_id: str) -> dict[str, Any]:
        task_id = str(task_id or "").strip()
        if not task_id:
            return {"success": False, "error": "task_id is required", "error_code": "bad_request"}
        task = self.store.get_task(task_id)
        if not task:
            return {"success": False, "error": "task not found", "error_code": "not_found"}
        return {"success": True, "task": task}

    async def list_tasks(self, payload: dict[str, Any]) -> dict[str, Any]:
        session_id = str(payload.get("session_id") or payload.get("sessionId") or "").strip() or None
        status = str(payload.get("status") or "").strip() or None
        limit = _to_int(payload.get("limit"), 20)
        offset = _to_int(payload.get("offset"), 0)
        items = self.store.list_tasks(
            session_id=session_id,
            status=status,
            limit=max(1, limit),
            offset=max(0, offset),
        )
        return {
            "success": True,
            "session_id": session_id,
            "status": status,
            "count": len(items),
            "items": items,
            "limit": max(1, limit),
            "offset": max(0, offset),
        }

    async def cancel(self, task_id: str, reason: str = "manual_cancel") -> dict[str, Any]:
        task_id = str(task_id or "").strip()
        if not task_id:
            return {"success": False, "error": "task_id is required", "error_code": "bad_request"}
        reason = str(reason or "manual_cancel")
        changed = self.store.update_task_if_status(
            task_id,
            expected_statuses={"pending", "running"},
            status="canceled",
            error=reason,
        )
        if not changed:
            task = self.store.get_task(task_id)
            if not task:
                return {"success": False, "error": "task not found", "error_code": "not_found"}
            status = str(task.get("status") or "")
            if status in _FINAL_STATUSES:
                return {
                    "success": False,
                    "error": f"task already {status}",
                    "error_code": "already_final",
                    "task": task,
                }
            return {"success": False, "error": "task status conflict", "error_code": "conflict", "task": task}

        self._cancel_reasons[task_id] = reason
        self._append_step(task_id, stage="canceled", status="ok", message=reason)
        task_data = self.store.get_task(task_id)
        await self._emit_status_update(
            task_id,
            status="canceled",
            message="任务已取消。",
            event="canceled",
            task=task_data,
        )
        task = self._running_tasks.get(task_id)
        if task and not task.done():
            task.cancel()
        return {"success": True, "task": task_data}

    async def flush_pending_updates(
        self,
        *,
        device_id: str,
        session_id: str = "",
        limit: int = 20,
    ) -> dict[str, Any]:
        device_id = str(device_id or "").strip()
        if not device_id:
            return {"success": False, "error": "device_id is required"}
        callback = self.status_callback
        if callback is None:
            return {"success": False, "error": "status callback unavailable"}
        items = self.store.list_pending_push_updates(device_id=device_id, limit=max(1, int(limit)))
        sent = 0
        retry = 0
        for item in items:
            queue_id = int(item["id"])
            payload = dict(item.get("payload") or {})
            if session_id:
                payload["session_id"] = session_id
            try:
                pushed = await callback(payload)
                if pushed is False:
                    raise RuntimeError("status callback reported push failure")
                self.store.mark_push_update_sent(queue_id)
                sent += 1
            except Exception as e:
                delay_ms = self.status_retry_backoff_ms * max(1, int(item.get("attempts", 0)) + 1)
                self.store.mark_push_update_retry(
                    queue_id,
                    error=str(e),
                    retry_delay_ms=delay_ms,
                )
                retry += 1
        return {
            "success": True,
            "device_id": device_id,
            "processed": len(items),
            "sent": sent,
            "retry": retry,
        }

    async def _run_task(
        self,
        *,
        task_id: str,
        session_id: str,
        goal: str,
        timeout_seconds: int,
    ) -> None:
        running_ok = self.store.update_task_if_status(
            task_id,
            expected_statuses={"pending"},
            status="running",
            error="",
        )
        if not running_ok:
            self._running_tasks.pop(task_id, None)
            return
        self._append_step(task_id, stage="running", status="ok", message="task running")
        running_task = self.store.get_task(task_id)
        await self._emit_status_update(
            task_id,
            status="running",
            message="任务处理中，请稍候。",
            event="running",
            task=running_task,
        )
        try:
            async with self._semaphore:
                executor_result = await asyncio.wait_for(
                    self.executor(goal, session_id),
                    timeout=float(timeout_seconds),
                )
            result_text, result_meta = _normalize_executor_result(executor_result)
            success_ok = self.store.update_task_if_status(
                task_id,
                expected_statuses={"running"},
                status="success",
                result={"text": result_text, **result_meta},
                error="",
            )
            if success_ok:
                self._append_step(
                    task_id,
                    stage="success",
                    status="ok",
                    message=result_meta.get("execution_path", "completed"),
                )
                final_task = self.store.get_task(task_id)
                preview = _shorten(result_text.strip(), 120)
                message = f"任务完成。{preview}" if preview else "任务完成。"
                await self._emit_status_update(
                    task_id,
                    status="success",
                    message=message,
                    event="success",
                    task=final_task,
                )
        except asyncio.CancelledError:
            reason = self._cancel_reasons.get(task_id, "canceled")
            canceled_ok = self.store.update_task_if_status(
                task_id,
                expected_statuses={"pending", "running"},
                status="canceled",
                error=reason,
            )
            if canceled_ok:
                self._append_step(task_id, stage="canceled", status="ok", message=reason)
                final_task = self.store.get_task(task_id)
                await self._emit_status_update(
                    task_id,
                    status="canceled",
                    message="任务已取消。",
                    event="canceled",
                    task=final_task,
                )
            raise
        except asyncio.TimeoutError:
            timeout_ok = self.store.update_task_if_status(
                task_id,
                expected_statuses={"running"},
                status="timeout",
                error=f"timeout after {timeout_seconds}s",
            )
            if timeout_ok:
                self._append_step(
                    task_id,
                    stage="timeout",
                    status="error",
                    message=f"timeout after {timeout_seconds}s",
                )
                final_task = self.store.get_task(task_id)
                await self._emit_status_update(
                    task_id,
                    status="timeout",
                    message="任务超时，请稍后重试。",
                    event="timeout",
                    task=final_task,
                )
        except Exception as e:
            failed_ok = self.store.update_task_if_status(
                task_id,
                expected_statuses={"running"},
                status="failed",
                error=str(e),
            )
            if failed_ok:
                self._append_step(task_id, stage="failed", status="error", message=str(e))
                final_task = self.store.get_task(task_id)
                await self._emit_status_update(
                    task_id,
                    status="failed",
                    message="任务执行失败。",
                    event="failed",
                    task=final_task,
                )
        finally:
            self._running_tasks.pop(task_id, None)
            self._cancel_reasons.pop(task_id, None)
            context = self._push_contexts.pop(task_id, None)
            if context:
                device_id = str(context.get("device_id") or "").strip()
                if device_id and self._active_task_by_device.get(device_id) == task_id:
                    self._active_task_by_device.pop(device_id, None)

    def _build_push_context(
        self,
        payload: dict[str, Any],
        *,
        task_id: str,
        session_id: str,
    ) -> dict[str, Any] | None:
        device_id = str(payload.get("device_id") or payload.get("deviceId") or "").strip()
        notify = _to_bool(payload.get("notify"), default=True)
        speak = _to_bool(payload.get("speak"), default=True)
        interrupt_previous = _to_bool(payload.get("interrupt_previous"), default=False)
        context = {
            "task_id": task_id,
            "device_id": device_id,
            "session_id": str(payload.get("target_session_id") or payload.get("targetSessionId") or session_id),
            "notify": notify,
            "speak": speak,
            "interrupt_previous": interrupt_previous,
        }
        return context if device_id else None

    def _recover_push_context(
        self,
        task: dict[str, Any],
        *,
        task_id: str,
        session_id: str,
    ) -> dict[str, Any] | None:
        raw = task.get("push_context")
        context = raw if isinstance(raw, dict) else {}
        device_id = str(task.get("device_id") or context.get("device_id") or "").strip()
        if not device_id:
            return None
        return {
            "task_id": task_id,
            "device_id": device_id,
            "session_id": str(context.get("session_id") or session_id).strip() or session_id,
            "notify": _to_bool(context.get("notify"), default=True),
            "speak": _to_bool(context.get("speak"), default=True),
            "interrupt_previous": _to_bool(context.get("interrupt_previous"), default=False),
        }

    async def _interrupt_previous_for_device(self, context: dict[str, Any], *, current_task_id: str) -> None:
        device_id = str(context.get("device_id") or "").strip()
        if not device_id:
            return
        previous_task_id = self._active_task_by_device.get(device_id)
        if not previous_task_id or previous_task_id == current_task_id:
            return
        previous = self.store.get_task(previous_task_id)
        if previous and str(previous.get("status")) in _RUNNABLE_STATUSES:
            await self.cancel(previous_task_id, reason="interrupted_by_new_task")

    async def _emit_status_update(
        self,
        task_id: str,
        *,
        status: str,
        message: str,
        event: str,
        task: dict[str, Any] | None,
    ) -> None:
        callback = self.status_callback
        context = self._push_contexts.get(task_id)
        if callback is None or not context:
            return
        if not bool(context.get("notify", True)):
            return
        payload = {
            "event": event,
            "task_id": task_id,
            "status": status,
            "message": message,
            "device_id": context.get("device_id"),
            "session_id": context.get("session_id"),
            "speak": bool(context.get("speak", True)),
            "task": task or {},
        }
        max_attempts = self.status_retry_count + 1
        for attempt in range(max_attempts):
            try:
                pushed = await callback(payload)
                if pushed is False:
                    raise RuntimeError("status callback reported push failure")
                return
            except Exception as e:
                if attempt >= max_attempts - 1:
                    self.store.enqueue_push_update(
                        task_id=task_id,
                        device_id=str(context.get("device_id") or ""),
                        session_id=str(context.get("session_id") or ""),
                        payload=payload,
                    )
                    logger.debug(
                        f"digital task status push queued task_id={task_id} status={status} attempts={max_attempts}: {e}"
                    )
                    return
                await asyncio.sleep((self.status_retry_backoff_ms / 1000.0) * (attempt + 1))

    def _append_step(self, task_id: str, *, stage: str, status: str, message: str) -> None:
        task = self.store.get_task(task_id)
        if not task:
            return
        steps = task.get("steps")
        if not isinstance(steps, list):
            steps = []
        steps.append(
            {
                "ts": int(task.get("updated_at") or _now_ms()),
                "stage": str(stage),
                "status": str(status),
                "message": str(message),
            }
        )
        self.store.update_task(task_id, steps=steps)


def _new_task_id() -> str:
    return uuid.uuid4().hex[:12]


def _to_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def _to_bool(value: Any, *, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return default


def _shorten(text: str, max_len: int) -> str:
    text = text.strip()
    if len(text) <= max_len:
        return text
    return text[: max_len - 3].rstrip() + "..."


def _normalize_executor_result(result: Any) -> tuple[str, dict[str, Any]]:
    if isinstance(result, dict):
        text = str(result.get("text") or "")
        meta = {k: v for k, v in result.items() if k != "text"}
        return text, meta
    return str(result or ""), {}


def _build_mcp_prompt(goal: str) -> str:
    return (
        "你在执行一个数字盲道代操作任务。要求：\n"
        "1) 必须调用至少一个 MCP 工具完成实际操作。\n"
        "2) 若 MCP 工具无法完成，输出完全一致的标记：MCP_FALLBACK_REQUIRED\n"
        "3) 不要输出无根据结论。\n\n"
        f"任务目标：{goal}"
    )


def _build_fallback_prompt(goal: str) -> str:
    return (
        "你在执行一个数字盲道代操作任务。要求：\n"
        "1) 优先使用 web_search / web_fetch / exec 等工具完成。\n"
        "2) 给出可执行结果与简要结论。\n"
        "3) 若信息不足，明确缺口并给出下一步。\n\n"
        f"任务目标：{goal}"
    )


def _should_fallback_from_mcp(output: str) -> bool:
    text = str(output or "").strip()
    if not text:
        return True
    if text == _NO_TOOL_USED:
        return True
    if _MCP_FALLBACK_TOKEN in text:
        return True
    return False


def _now_ms() -> int:
    return int(time.time() * 1000)
