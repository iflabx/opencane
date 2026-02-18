import asyncio

import pytest

from nanobot.api.digital_task_service import DigitalTaskService
from nanobot.config.schema import Config
from nanobot.storage import SQLiteDigitalTaskStore

_FINAL = {"success", "failed", "timeout", "canceled"}


async def _wait_task(service: DigitalTaskService, task_id: str, timeout_s: float = 2.0) -> dict:
    deadline = asyncio.get_running_loop().time() + timeout_s
    while asyncio.get_running_loop().time() < deadline:
        result = await service.get_task(task_id)
        assert result["success"] is True
        task = result["task"]
        if task.get("status") in _FINAL:
            return task
        await asyncio.sleep(0.02)
    raise AssertionError(f"task did not finish before timeout: {task_id}")


class _FakePolicyAgentLoop:
    def __init__(self, tools: list[str], outputs: list[str]) -> None:
        self._tools = list(tools)
        self._outputs = list(outputs)
        self.calls: list[dict] = []

    async def list_registered_tools(self, *, connect_mcp: bool = True) -> list[str]:
        self.calls.append({"method": "list_registered_tools", "connect_mcp": connect_mcp})
        return list(self._tools)

    async def process_direct(self, content: str, **kwargs):  # type: ignore[no-untyped-def]
        self.calls.append({"method": "process_direct", "content": content, **kwargs})
        if self._outputs:
            return self._outputs.pop(0)
        return ""


@pytest.mark.asyncio
async def test_digital_task_service_success(tmp_path) -> None:  # type: ignore[no-untyped-def]
    async def _executor(goal: str, session_id: str) -> str:
        return f"ok:{session_id}:{goal}"

    service = DigitalTaskService(
        store=SQLiteDigitalTaskStore(tmp_path / "tasks.db"),
        executor=_executor,
        default_timeout_seconds=2,
    )
    try:
        result = await service.execute({"session_id": "sess-1", "goal": "导航到超市"})
        assert result["success"] is True
        task_id = result["task"]["task_id"]

        task = await _wait_task(service, task_id)
        assert task["status"] == "success"
        assert "导航到超市" in task["result"].get("text", "")
    finally:
        await service.shutdown()


@pytest.mark.asyncio
async def test_digital_task_service_timeout(tmp_path) -> None:  # type: ignore[no-untyped-def]
    async def _executor(goal: str, session_id: str) -> str:
        del goal, session_id
        await asyncio.sleep(1.4)
        return "done"

    service = DigitalTaskService(
        store=SQLiteDigitalTaskStore(tmp_path / "tasks.db"),
        executor=_executor,
        default_timeout_seconds=1,
    )
    try:
        result = await service.execute(
            {"session_id": "sess-2", "goal": "slow task", "timeout_seconds": 1}
        )
        assert result["success"] is True
        task_id = result["task"]["task_id"]

        task = await _wait_task(service, task_id)
        assert task["status"] == "timeout"
        assert "timeout after" in task["error"]
    finally:
        await service.shutdown()


@pytest.mark.asyncio
async def test_digital_task_service_failed(tmp_path) -> None:  # type: ignore[no-untyped-def]
    async def _executor(goal: str, session_id: str) -> str:
        del goal, session_id
        raise RuntimeError("boom")

    service = DigitalTaskService(
        store=SQLiteDigitalTaskStore(tmp_path / "tasks.db"),
        executor=_executor,
        default_timeout_seconds=2,
    )
    try:
        result = await service.execute({"session_id": "sess-3", "goal": "raise error"})
        assert result["success"] is True
        task_id = result["task"]["task_id"]

        task = await _wait_task(service, task_id)
        assert task["status"] == "failed"
        assert "boom" in task["error"]
    finally:
        await service.shutdown()


@pytest.mark.asyncio
async def test_digital_task_service_cancel(tmp_path) -> None:  # type: ignore[no-untyped-def]
    async def _executor(goal: str, session_id: str) -> str:
        del goal, session_id
        await asyncio.sleep(5)
        return "done"

    service = DigitalTaskService(
        store=SQLiteDigitalTaskStore(tmp_path / "tasks.db"),
        executor=_executor,
        default_timeout_seconds=10,
    )
    try:
        result = await service.execute({"session_id": "sess-4", "goal": "cancel me"})
        assert result["success"] is True
        task_id = result["task"]["task_id"]

        cancel = await service.cancel(task_id, reason="user_cancel")
        assert cancel["success"] is True

        task = await _wait_task(service, task_id)
        assert task["status"] == "canceled"
        assert task["error"] == "user_cancel"
    finally:
        await service.shutdown()


@pytest.mark.asyncio
async def test_digital_task_service_validation_and_not_found(tmp_path) -> None:  # type: ignore[no-untyped-def]
    async def _executor(goal: str, session_id: str) -> str:
        return f"{session_id}:{goal}"

    service = DigitalTaskService(
        store=SQLiteDigitalTaskStore(tmp_path / "tasks.db"),
        executor=_executor,
        default_timeout_seconds=2,
    )
    try:
        invalid = await service.execute({"session_id": "sess-5"})
        assert invalid["success"] is False
        assert invalid["error_code"] == "bad_request"

        missing_get = await service.get_task("not-found")
        assert missing_get["success"] is False
        assert missing_get["error_code"] == "not_found"

        missing_cancel = await service.cancel("not-found")
        assert missing_cancel["success"] is False
        assert missing_cancel["error_code"] == "not_found"
    finally:
        await service.shutdown()


@pytest.mark.asyncio
async def test_digital_task_service_push_callback_receives_status_updates(tmp_path) -> None:  # type: ignore[no-untyped-def]
    updates: list[dict] = []

    async def _executor(goal: str, session_id: str) -> str:
        await asyncio.sleep(0.05)
        return f"{session_id}:{goal}"

    async def _callback(payload):  # type: ignore[no-untyped-def]
        updates.append(dict(payload))
        return True

    service = DigitalTaskService(
        store=SQLiteDigitalTaskStore(tmp_path / "tasks.db"),
        executor=_executor,
        default_timeout_seconds=2,
        status_callback=_callback,
    )
    try:
        result = await service.execute(
            {
                "session_id": "sess-push",
                "device_id": "dev-1",
                "goal": "navigate",
                "notify": True,
                "speak": False,
            }
        )
        assert result["success"] is True
        task_id = result["task"]["task_id"]
        task = await _wait_task(service, task_id)
        assert task["status"] == "success"

        statuses = [str(item.get("status")) for item in updates]
        assert "pending" in statuses
        assert "running" in statuses
        assert "success" in statuses
        assert all(str(item.get("device_id")) == "dev-1" for item in updates)
    finally:
        await service.shutdown()


@pytest.mark.asyncio
async def test_digital_task_service_push_retry_and_interrupt_previous(tmp_path) -> None:  # type: ignore[no-untyped-def]
    attempts = {"count": 0}

    async def _executor(goal: str, session_id: str) -> str:
        if "long" in goal:
            await asyncio.sleep(3)
        return f"{session_id}:{goal}"

    async def _callback(payload):  # type: ignore[no-untyped-def]
        attempts["count"] += 1
        if attempts["count"] == 1 and payload.get("event") == "accepted":
            raise RuntimeError("first push failed")
        return True

    service = DigitalTaskService(
        store=SQLiteDigitalTaskStore(tmp_path / "tasks.db"),
        executor=_executor,
        default_timeout_seconds=5,
        status_callback=_callback,
        status_retry_count=1,
        status_retry_backoff_ms=10,
    )
    try:
        first = await service.execute(
            {
                "session_id": "sess-i1",
                "device_id": "dev-interrupt",
                "goal": "long task",
                "notify": True,
                "speak": False,
            }
        )
        assert first["success"] is True
        first_id = first["task"]["task_id"]

        second = await service.execute(
            {
                "session_id": "sess-i2",
                "device_id": "dev-interrupt",
                "goal": "short task",
                "notify": True,
                "speak": False,
                "interrupt_previous": True,
            }
        )
        assert second["success"] is True
        second_id = second["task"]["task_id"]

        first_task = await _wait_task(service, first_id, timeout_s=3.0)
        second_task = await _wait_task(service, second_id, timeout_s=3.0)
        assert first_task["status"] == "canceled"
        assert first_task["error"] == "interrupted_by_new_task"
        assert second_task["status"] == "success"
        assert attempts["count"] >= 2
    finally:
        await service.shutdown()


@pytest.mark.asyncio
async def test_digital_task_service_records_steps_and_execution_path(tmp_path) -> None:  # type: ignore[no-untyped-def]
    async def _executor(goal: str, session_id: str):  # type: ignore[no-untyped-def]
        return {
            "text": f"{session_id}:{goal}",
            "execution_path": "mcp",
        }

    service = DigitalTaskService(
        store=SQLiteDigitalTaskStore(tmp_path / "tasks.db"),
        executor=_executor,
        default_timeout_seconds=2,
    )
    try:
        result = await service.execute({"session_id": "sess-step", "goal": "steps"})
        task_id = result["task"]["task_id"]
        task = await _wait_task(service, task_id)
        assert task["status"] == "success"
        assert task["result"].get("execution_path") == "mcp"
        steps = task.get("steps") or []
        assert len(steps) >= 3
        assert any(str(step.get("stage")) == "accepted" for step in steps)
        assert any(str(step.get("stage")) == "running" for step in steps)
        assert any(str(step.get("stage")) == "success" for step in steps)
    finally:
        await service.shutdown()


@pytest.mark.asyncio
async def test_digital_task_service_cancel_wins_race_against_success(tmp_path) -> None:  # type: ignore[no-untyped-def]
    async def _executor(goal: str, session_id: str) -> str:
        del goal, session_id
        await asyncio.sleep(0.2)
        return "done"

    service = DigitalTaskService(
        store=SQLiteDigitalTaskStore(tmp_path / "tasks.db"),
        executor=_executor,
        default_timeout_seconds=3,
    )
    try:
        result = await service.execute({"session_id": "sess-race", "goal": "race"})
        task_id = result["task"]["task_id"]
        await asyncio.sleep(0.01)
        await service.cancel(task_id, reason="race-cancel")
        task = await _wait_task(service, task_id)
        assert task["status"] == "canceled"
        assert task["error"] == "race-cancel"
    finally:
        await service.shutdown()


@pytest.mark.asyncio
async def test_digital_task_service_recover_unfinished_tasks(tmp_path) -> None:  # type: ignore[no-untyped-def]
    db_path = tmp_path / "tasks.db"
    store = SQLiteDigitalTaskStore(db_path)
    store.create_task(
        task_id="recover-1",
        session_id="sess-recover",
        goal="recover goal",
        status="pending",
        timeout_seconds=2,
    )
    store.close()

    async def _executor(goal: str, session_id: str) -> str:
        return f"recovered:{session_id}:{goal}"

    service = DigitalTaskService(
        store=SQLiteDigitalTaskStore(db_path),
        executor=_executor,
        default_timeout_seconds=2,
    )
    try:
        recovered = await service.recover_unfinished_tasks()
        assert recovered == 1
        task = await _wait_task(service, "recover-1")
        assert task["status"] == "success"
        assert "recover goal" in task["result"].get("text", "")
    finally:
        await service.shutdown()


@pytest.mark.asyncio
async def test_digital_task_service_recover_restores_push_context(tmp_path) -> None:  # type: ignore[no-untyped-def]
    db_path = tmp_path / "tasks-recover-push.db"
    store = SQLiteDigitalTaskStore(db_path)
    store.create_task(
        task_id="recover-push-1",
        session_id="sess-recover-push",
        goal="recover push goal",
        status="pending",
        timeout_seconds=2,
        push_context={
            "device_id": "dev-recover",
            "session_id": "sess-target",
            "notify": True,
            "speak": True,
            "interrupt_previous": True,
        },
    )
    store.close()

    updates: list[dict] = []

    async def _executor(goal: str, session_id: str) -> str:
        return f"recovered:{session_id}:{goal}"

    async def _callback(payload):  # type: ignore[no-untyped-def]
        updates.append(dict(payload))
        return True

    service = DigitalTaskService(
        store=SQLiteDigitalTaskStore(db_path),
        executor=_executor,
        default_timeout_seconds=2,
        status_callback=_callback,
    )
    try:
        recovered = await service.recover_unfinished_tasks()
        assert recovered == 1
        task = await _wait_task(service, "recover-push-1")
        assert task["status"] == "success"
        assert task["device_id"] == "dev-recover"
        assert updates
        assert any(str(item.get("device_id")) == "dev-recover" for item in updates)
    finally:
        await service.shutdown()


@pytest.mark.asyncio
async def test_digital_task_service_queue_and_flush_pending_push_updates(tmp_path) -> None:  # type: ignore[no-untyped-def]
    fail_calls: list[dict] = []
    success_calls: list[dict] = []

    async def _executor(goal: str, session_id: str) -> str:
        return f"{session_id}:{goal}"

    async def _failing_callback(payload):  # type: ignore[no-untyped-def]
        fail_calls.append(dict(payload))
        return False

    async def _success_callback(payload):  # type: ignore[no-untyped-def]
        success_calls.append(dict(payload))
        return True

    service = DigitalTaskService(
        store=SQLiteDigitalTaskStore(tmp_path / "tasks.db"),
        executor=_executor,
        default_timeout_seconds=2,
        status_callback=_failing_callback,
        status_retry_count=0,
        status_retry_backoff_ms=10,
    )
    try:
        result = await service.execute(
            {
                "session_id": "sess-q",
                "device_id": "dev-q",
                "goal": "queue push",
                "notify": True,
                "speak": False,
            }
        )
        assert result["success"] is True
        task_id = result["task"]["task_id"]
        task = await _wait_task(service, task_id)
        assert task["status"] == "success"
        pending = service.store.list_push_queue(device_id="dev-q", status="pending")
        assert len(pending) >= 1

        service.set_status_callback(_success_callback)
        flushed = await service.flush_pending_updates(device_id="dev-q", session_id="sess-q", limit=50)
        assert flushed["success"] is True
        assert flushed["sent"] >= 1
        sent_rows = service.store.list_push_queue(device_id="dev-q", status="sent")
        assert len(sent_rows) >= 1
        assert len(success_calls) >= 1
    finally:
        await service.shutdown()


@pytest.mark.asyncio
async def test_digital_task_service_list_and_stats(tmp_path) -> None:  # type: ignore[no-untyped-def]
    async def _executor(goal: str, session_id: str) -> str:
        return f"{session_id}:{goal}"

    service = DigitalTaskService(
        store=SQLiteDigitalTaskStore(tmp_path / "tasks.db"),
        executor=_executor,
        default_timeout_seconds=2,
    )
    try:
        result1 = await service.execute({"session_id": "sess-stat", "goal": "task-1"})
        result2 = await service.execute({"session_id": "sess-stat", "goal": "task-2"})
        await _wait_task(service, result1["task"]["task_id"])
        await _wait_task(service, result2["task"]["task_id"])

        listed = await service.list_tasks({"session_id": "sess-stat", "limit": 10, "offset": 0})
        assert listed["success"] is True
        assert listed["count"] >= 2

        stats = await service.stats({"session_id": "sess-stat"})
        assert stats["success"] is True
        stats_data = stats["stats"]
        assert int(stats_data.get("total", 0)) >= 2
        assert float(stats_data.get("success_rate", 0.0)) > 0.0
    finally:
        await service.shutdown()


@pytest.mark.asyncio
async def test_digital_task_service_from_config_executor_prefers_mcp_stage(tmp_path) -> None:  # type: ignore[no-untyped-def]
    config = Config()
    config.digital_task.sqlite_path = str(tmp_path / "tasks.db")
    loop = _FakePolicyAgentLoop(
        tools=["mcp_browser_fill", "web_search", "exec"],
        outputs=["mcp done"],
    )
    service = DigitalTaskService.from_config(config, agent_loop=loop)
    try:
        result = await service.executor("帮我挂号", "sess-mcp")
        assert result["execution_path"] == "mcp"
        assert result["text"] == "mcp done"
        assert result["allowed_tools"] == ["mcp_browser_fill"]

        process_calls = [item for item in loop.calls if item.get("method") == "process_direct"]
        assert len(process_calls) == 1
        first = process_calls[0]
        assert first["require_tool_use"] is True
        assert first["allowed_tool_names"] == {"mcp_browser_fill"}
        assert "MCP 工具" in str(first["content"])
    finally:
        await service.shutdown()


@pytest.mark.asyncio
async def test_digital_task_service_from_config_executor_fallback_stage(tmp_path) -> None:  # type: ignore[no-untyped-def]
    config = Config()
    config.digital_task.sqlite_path = str(tmp_path / "tasks.db")
    loop = _FakePolicyAgentLoop(
        tools=["mcp_browser_fill", "web_search", "web_fetch", "exec"],
        outputs=[
            "MCP_FALLBACK_REQUIRED",
            "NO_TOOL_USED",
            "fallback done",
        ],
    )
    service = DigitalTaskService.from_config(config, agent_loop=loop)
    try:
        result = await service.executor("帮我查询医院预约", "sess-fallback")
        assert result["execution_path"] == "web_exec_fallback"
        assert result["text"] == "fallback done"
        assert result["allowed_tools"] == ["exec", "mcp_browser_fill", "web_fetch", "web_search"]

        process_calls = [item for item in loop.calls if item.get("method") == "process_direct"]
        assert len(process_calls) == 3
        first, second, third = process_calls
        assert first["require_tool_use"] is True
        assert first["allowed_tool_names"] == {"mcp_browser_fill"}
        assert second["require_tool_use"] is True
        assert second["allowed_tool_names"] == {"mcp_browser_fill", "web_search", "web_fetch", "exec"}
        assert "web_search / web_fetch / exec" in str(second["content"])
        assert third["require_tool_use"] is False
        assert third["content"] == "帮我查询医院预约"
    finally:
        await service.shutdown()
