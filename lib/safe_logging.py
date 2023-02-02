"""
Logging utilities for the WeatherMap
"""

import inspect
import traceback
from datetime import datetime, timedelta

import lib.logger
from lib.logger import LOGGER

TAB_TEXT = ' ' * 4
MODULE_NAME = '<module>'


def __get_callstack_indent_count(
    stack_adjustment: int = 3
) -> int:
    """
    Returns the number of indents that should be applied to the logging statement.

    Keyword Arguments:
        stack_adjustment {int -- The number of frames down the ACTUAL function name is. (default: {3})

    Returns:
        int -- The number of indents.
    """

    try:
        cs_info = traceback.extract_stack()

        indents = 0

        for index in range(len(cs_info) - stack_adjustment, 0, -1):
            if MODULE_NAME in cs_info[index].name:
                break
            else:
                indents += 1

        if indents < 0:
            indents = 0

        return indents
    except Exception:
        return 0


def __get_indents(
    count: int = 0,
    stack_adjustment: int = 3
) -> str:
    """
    Returns whitespace for the number of given indents.

    Keyword Arguments:
        count {int} -- The number of indents to return whitespace for. (default: {0})
        stack_adjustment {int -- The number of frames down the ACTUAL function name is. (default: {3})

    Returns:
        string -- A whitespace string.
    """

    if count < 0:
        count = 0

    function_name = 'UNKNOWN'
    line_num = 'UNKNOWN'

    try:
        cs_info = traceback.extract_stack()
        index = len(cs_info) - stack_adjustment
        function_name = '{}()'.format(cs_info[index].name)

        if MODULE_NAME in function_name:
            function_name = cs_info[index].filename

        line_num = cs_info[index].lineno
    except:
        pass

    return '{}{}:{}: '.format(TAB_TEXT * count, function_name, line_num)


def safe_log(
    message: str
):
    """
    Logs an INFO level message safely. Also prints it to the screen.

    Arguments:
        logger {logger} -- The logger to use.
        message {string} -- The message to log.
    """

    try:
        indents = __get_indents(__get_callstack_indent_count())
        if LOGGER is not None:
            LOGGER.log_info_message(indents + message)
        else:
            print('{} INFO: {}{}'.format(datetime.now(), indents, message))
    except Exception:
        print('{}{}'.format(indents,  message))


def safe_log_warning(
    message: str
):
    """
    Logs a WARN level message safely. Also prints it to the screen.

    Arguments:
        logger {logger} -- The logger to use.
        message {string} -- The message to log.
    """

    try:
        indents = __get_indents(__get_callstack_indent_count())

        if LOGGER is not None:
            LOGGER.log_warning_message(indents + message)
        else:
            print('{} WARN: {}{}'.format(datetime.now(), indents, message))
    except Exception:
        print(indents + message)
