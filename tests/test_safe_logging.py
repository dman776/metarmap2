"""Tests for the caller's module, class and function at the start of every safe_log message."""
import sys
import threading
from types import SimpleNamespace

from metarmap.lib import safe_logging
from metarmap.lib.safe_logging import safe_log

caller_name = getattr(safe_logging, "__get_caller_name")


class Thing:
    def method(self):
        safe_log("from a method")

    def nested(self):
        def inner():
            safe_log("from a nested function")
        inner()

    @classmethod
    def class_method(cls):
        safe_log("from a classmethod")


def function():
    safe_log("from a function")


# Before Python 3.11 a frame doesn't know its qualified name, so a nested function is just 'inner()'
NESTED_NAME = "test_safe_logging.Thing.nested.inner():" if sys.version_info >= (3, 11) else "test_safe_logging.inner():"


def logged(capsys):
    return capsys.readouterr().out.rstrip("\n").split(" INFO: ", 1)[1]


def test_a_method_logs_its_module_class_and_function(capsys):
    Thing().method()
    assert logged(capsys).startswith("test_safe_logging.Thing.method():")


def test_a_function_logs_its_module_and_function(capsys):
    function()
    assert logged(capsys).startswith("test_safe_logging.function():")


def test_a_nested_function_leaves_out_locals(capsys):
    Thing().nested()
    assert logged(capsys).startswith(NESTED_NAME)


def test_a_classmethod_logs_its_class(capsys):
    Thing.class_method()
    assert logged(capsys).startswith("test_safe_logging.Thing.class_method():")


def test_the_line_number_and_message_follow(capsys):
    function()
    assert logged(capsys).endswith(":27: from a function")


def test_a_message_from_a_thread_is_not_indented(capsys):
    thread = threading.Thread(target=Thing().nested)
    thread.start()
    thread.join()
    assert logged(capsys).startswith(NESTED_NAME)


def fake_frame(name, module="metarmap.metar", **local_vars):
    return SimpleNamespace(f_code=SimpleNamespace(co_name=name), f_globals={"__name__": module},
                           f_locals=local_vars)


def test_the_metarmap_package_prefix_is_left_off():
    assert caller_name(fake_frame("process")) == "metar.process()"


def test_module_level_code_logs_only_the_module():
    assert caller_name(fake_frame("<module>", "metarmap.app")) == "app"


def test_before_python_3_11_the_class_comes_from_self_or_cls():
    class METAR:
        pass

    assert caller_name(fake_frame("fetch", self=METAR())) == "metar.METAR.fetch()"
    assert caller_name(fake_frame("load", cls=METAR)) == "metar.METAR.load()"
