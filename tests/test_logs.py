"""Tests for where the log goes (metarmap.logs) and what a line looks like."""

import io
import logging
import subprocess
import sys
from pathlib import Path

import pytest

from metarmap import logs

SRC = Path(__file__).parent.parent / "src"


@pytest.fixture
def configured(tmp_path):
    """The map's logging, to a file in tmp_path and a console in memory: (log file, console, a module's logger)."""
    console = io.StringIO()
    logs.configure(tmp_path / "metarmap.log", console=console)
    yield tmp_path / "metarmap.log", console, logging.getLogger("metarmap.metar")
    package = logging.getLogger(logs.LOG_NAME)
    for handler in list(package.handlers):
        package.removeHandler(handler)
        handler.close()
    package.propagate = True  # back as it was, for caplog in the other tests
    package.setLevel(logging.NOTSET)


def fetch(log):
    log.info("Fetching...")


def test_a_line_says_where_it_was_logged(configured):
    path, _, log = configured
    fetch(log)
    line = path.read_text()
    line_number = fetch.__code__.co_firstlineno + 1
    assert f" INFO metarmap.metar.fetch:{line_number}: Fetching...\n" in line
    assert line[:4].isdigit()  # starts with the time


def test_the_console_gets_warnings_and_errors_only(configured):
    path, console, log = configured
    log.debug("detail")
    log.info("normal")
    log.warning("odd")
    log.error("broken")
    assert [line.split(" ")[2] for line in path.read_text().splitlines()] == ["INFO", "WARNING", "ERROR"]
    assert [line.split(" ")[2] for line in console.getvalue().splitlines()] == ["WARNING", "ERROR"]


def test_a_traceback_is_on_lines_of_its_own(configured):
    path, console, log = configured
    try:
        raise ValueError("bad value")
    except ValueError:
        log.exception("parse failed")
    text = path.read_text()
    assert "ERROR metarmap.metar.test_a_traceback_is_on_lines_of_its_own" in text
    assert "\nTraceback (most recent call last):\n" in text
    assert text.rstrip().endswith("ValueError: bad value")
    assert "Traceback" in console.getvalue()


def test_configure_again_logs_once(configured, tmp_path):
    path, _, log = configured
    console = io.StringIO()
    logs.configure(path, console=console)
    log.warning("just one line")
    assert path.read_text().count("just one line") == 1
    assert console.getvalue().count("just one line") == 1


def test_the_file_rotates(configured):
    handler = next(h for h in logging.getLogger(logs.LOG_NAME).handlers if hasattr(h, "maxBytes"))
    assert (handler.maxBytes, handler.backupCount) == (10 * 1024 * 1024, 10)


def test_importing_the_map_writes_no_log(tmp_path):
    """Only the running map (app.main) sets up the log; tests and tools that import it leave no metarmap.log."""
    code = "import metarmap.app, logging; logging.getLogger('metarmap.metar').info('hello')"
    subprocess.run([sys.executable, "-c", code], cwd=tmp_path, env={"PYTHONPATH": str(SRC)}, check=True)
    assert list(tmp_path.iterdir()) == []
