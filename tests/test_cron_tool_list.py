"""Tests for CronTool list output formatting."""

from opencane.agent.tools.cron import CronTool
from opencane.cron.service import CronService
from opencane.cron.types import CronSchedule


def _make_tool(tmp_path) -> CronTool:  # type: ignore[no-untyped-def]
    service = CronService(tmp_path / "cron" / "jobs.json")
    return CronTool(service)


def test_list_empty(tmp_path) -> None:
    tool = _make_tool(tmp_path)
    assert tool._list_jobs() == "No scheduled jobs."


def test_format_timing_every_seconds() -> None:
    s = CronSchedule(kind="every", every_ms=30_000)
    assert CronTool._format_timing(s) == "every 30s"


def test_format_timing_every_non_minute_seconds() -> None:
    s = CronSchedule(kind="every", every_ms=90_000)
    assert CronTool._format_timing(s) == "every 90s"


def test_format_timing_every_milliseconds() -> None:
    s = CronSchedule(kind="every", every_ms=200)
    assert CronTool._format_timing(s) == "every 200ms"


def test_format_timing_at() -> None:
    s = CronSchedule(kind="at", at_ms=1773684000000)
    result = CronTool._format_timing(s)
    assert result.startswith("at 2026-")


def test_list_cron_job_shows_expression_and_timezone(tmp_path) -> None:
    tool = _make_tool(tmp_path)
    tool._cron.add_job(
        name="Morning scan",
        schedule=CronSchedule(kind="cron", expr="0 9 * * 1-5", tz="America/Denver"),
        message="scan",
    )
    result = tool._list_jobs()
    assert "cron: 0 9 * * 1-5 (America/Denver)" in result


def test_list_every_job_shows_human_interval(tmp_path) -> None:
    tool = _make_tool(tmp_path)
    tool._cron.add_job(
        name="Frequent check",
        schedule=CronSchedule(kind="every", every_ms=1_800_000),
        message="check",
    )
    result = tool._list_jobs()
    assert "every 30m" in result


def test_list_every_job_hours(tmp_path) -> None:
    tool = _make_tool(tmp_path)
    tool._cron.add_job(
        name="Hourly check",
        schedule=CronSchedule(kind="every", every_ms=7_200_000),
        message="check",
    )
    result = tool._list_jobs()
    assert "every 2h" in result


def test_list_every_job_seconds(tmp_path) -> None:
    tool = _make_tool(tmp_path)
    tool._cron.add_job(
        name="Fast check",
        schedule=CronSchedule(kind="every", every_ms=30_000),
        message="check",
    )
    result = tool._list_jobs()
    assert "every 30s" in result


def test_list_every_job_non_minute_seconds(tmp_path) -> None:
    tool = _make_tool(tmp_path)
    tool._cron.add_job(
        name="Ninety-second check",
        schedule=CronSchedule(kind="every", every_ms=90_000),
        message="check",
    )
    result = tool._list_jobs()
    assert "every 90s" in result


def test_list_every_job_milliseconds(tmp_path) -> None:
    tool = _make_tool(tmp_path)
    tool._cron.add_job(
        name="Sub-second check",
        schedule=CronSchedule(kind="every", every_ms=200),
        message="check",
    )
    result = tool._list_jobs()
    assert "every 200ms" in result


def test_list_at_job_shows_iso_timestamp(tmp_path) -> None:
    tool = _make_tool(tmp_path)
    tool._cron.add_job(
        name="One-shot",
        schedule=CronSchedule(kind="at", at_ms=1773684000000),
        message="fire",
    )
    result = tool._list_jobs()
    assert "at 2026-" in result


def test_list_shows_last_run_state(tmp_path) -> None:
    tool = _make_tool(tmp_path)
    job = tool._cron.add_job(
        name="Stateful job",
        schedule=CronSchedule(kind="cron", expr="0 9 * * *", tz="UTC"),
        message="test",
    )
    job.state.last_run_at_ms = 1773673200000
    job.state.last_status = "ok"
    tool._cron._save_store()

    result = tool._list_jobs()
    assert "Last run:" in result
    assert "ok" in result


def test_list_shows_error_message(tmp_path) -> None:
    tool = _make_tool(tmp_path)
    job = tool._cron.add_job(
        name="Failed job",
        schedule=CronSchedule(kind="cron", expr="0 9 * * *", tz="UTC"),
        message="test",
    )
    job.state.last_run_at_ms = 1773673200000
    job.state.last_status = "error"
    job.state.last_error = "timeout"
    tool._cron._save_store()

    result = tool._list_jobs()
    assert "error" in result
    assert "timeout" in result


def test_list_shows_next_run(tmp_path) -> None:
    tool = _make_tool(tmp_path)
    tool._cron.add_job(
        name="Upcoming job",
        schedule=CronSchedule(kind="cron", expr="0 9 * * *", tz="UTC"),
        message="test",
    )
    result = tool._list_jobs()
    assert "Next run:" in result


def test_add_job_with_timezone_via_tool(tmp_path) -> None:
    tool = _make_tool(tmp_path)
    tool.set_context("cli", "chat-1")

    result = tool._add_job(
        message="Morning reminder",
        every_seconds=None,
        cron_expr="0 9 * * *",
        tz="America/Vancouver",
        at=None,
    )

    assert "Created job" in result
    jobs = tool._cron.list_jobs(include_disabled=True)
    assert jobs
    assert jobs[0].schedule.tz == "America/Vancouver"


def test_add_job_rejects_timezone_without_cron_expression(tmp_path) -> None:
    tool = _make_tool(tmp_path)
    tool.set_context("cli", "chat-2")

    result = tool._add_job(
        message="Bad tz usage",
        every_seconds=60,
        cron_expr=None,
        tz="UTC",
        at=None,
    )

    assert result == "Error: tz can only be used with cron_expr"


def test_list_excludes_disabled_jobs(tmp_path) -> None:
    tool = _make_tool(tmp_path)
    job = tool._cron.add_job(
        name="Paused job",
        schedule=CronSchedule(kind="cron", expr="0 9 * * *", tz="UTC"),
        message="test",
    )
    tool._cron.enable_job(job.id, enabled=False)

    result = tool._list_jobs()
    assert "Paused job" not in result
    assert result == "No scheduled jobs."
