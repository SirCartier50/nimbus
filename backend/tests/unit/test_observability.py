import json
import logging

from observability import JsonFormatter, request_id_var


def _record(msg="hello", exc_info=None):
    return logging.LogRecord(
        name="test", level=logging.INFO, pathname=__file__, lineno=1,
        msg=msg, args=(), exc_info=exc_info,
    )


def test_json_formatter_emits_parseable_structured_lines():
    line = JsonFormatter().format(_record("something happened"))
    entry = json.loads(line)
    assert entry["message"] == "something happened"
    assert entry["level"] == "INFO"
    assert entry["logger"] == "test"
    assert "request_id" not in entry  # no request context → no noise key


def test_json_formatter_stamps_request_id_from_context():
    token = request_id_var.set("req-abc123")
    try:
        entry = json.loads(JsonFormatter().format(_record()))
    finally:
        request_id_var.reset(token)
    assert entry["request_id"] == "req-abc123"


def test_json_formatter_includes_exceptions():
    try:
        raise ValueError("boom")
    except ValueError:
        import sys
        entry = json.loads(JsonFormatter().format(_record(exc_info=sys.exc_info())))
    assert "boom" in entry["exc_info"]
    assert "Traceback" in entry["exc_info"]
