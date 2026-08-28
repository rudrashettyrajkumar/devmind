import json
import logging

import pytest

from devmind.core.logging import LoggingConfigurator, SessionIdBinder


def test_configure_installs_a_single_json_handler() -> None:
    LoggingConfigurator().configure("DEBUG")
    root = logging.getLogger()
    assert len(root.handlers) == 1
    assert root.level == logging.DEBUG


def test_log_record_is_valid_json(capfd: pytest.CaptureFixture[str]) -> None:
    LoggingConfigurator().configure("INFO")
    logger = logging.getLogger("devmind.test.json")
    logger.info("hello world")

    out = capfd.readouterr().err
    record = json.loads(out.strip().splitlines()[-1])
    assert record["message"] == "hello world"
    assert record["level"] == "INFO"
    assert "timestamp" in record


def test_log_record_includes_exception_traceback(capfd: pytest.CaptureFixture[str]) -> None:
    LoggingConfigurator().configure("INFO")
    logger = logging.getLogger("devmind.test.exception")

    try:
        raise ValueError("boom")
    except ValueError:
        logger.exception("something failed")

    out = capfd.readouterr().err
    record = json.loads(out.strip().splitlines()[-1])
    assert record["message"] == "something failed"
    assert "exception" in record
    assert "ValueError: boom" in record["exception"]


def test_session_id_binder_injects_into_record(capfd: pytest.CaptureFixture[str]) -> None:
    LoggingConfigurator().configure("INFO")
    logger = logging.getLogger("devmind.test.session")

    with SessionIdBinder("session-123"):
        logger.info("bound message")
    logger.info("unbound message")

    out = capfd.readouterr().err
    lines = [json.loads(line) for line in out.strip().splitlines() if line.strip()]
    bound = next(rec for rec in lines if rec["message"] == "bound message")
    unbound = next(rec for rec in lines if rec["message"] == "unbound message")
    assert bound["session_id"] == "session-123"
    assert unbound["session_id"] is None
