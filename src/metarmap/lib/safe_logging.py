"""
Logging utilities for the WeatherMap
"""

import sys
from datetime import datetime

from metarmap.lib.logger import LOGGER


MODULE_NAME = '<module>'
PACKAGE_PREFIX = 'metarmap.'


def __get_location(
    stack_adjustment: int = 2
) -> str:
    """
    Returns where the logging statement is, to put in front of the message.

    Keyword Arguments:
        stack_adjustment {int} -- The number of frames down the ACTUAL function name is. (default: {2})

    Returns:
        string -- e.g. 'metar.METAR.fetch():177: '
    """

    function_name = 'UNKNOWN'
    line_num = 'UNKNOWN'

    try:
        frame = sys._getframe(stack_adjustment)
        function_name = __get_caller_name(frame)
        line_num = frame.f_lineno
    except Exception:
        pass

    return '{}:{}: '.format(function_name, line_num)


def __get_caller_name(
    frame
) -> str:
    """
    Returns where a frame's code lives: the module, then the class and function if there are any,
    e.g. 'metar.METAR.fetch()', 'app.main()', or just 'app' for module-level code.
    The package prefix 'metarmap.' is left off, and so is '<locals>' for nested functions.

    Arguments:
        frame {frame} -- The frame of the code that logged the message.

    Returns:
        string -- The caller's name.
    """

    code = frame.f_code
    qualname = getattr(code, 'co_qualname', None)  # Python 3.11+

    if qualname is None:
        owner = frame.f_locals.get('self', frame.f_locals.get('cls'))
        qualname = code.co_name

        if owner is not None and code.co_name != MODULE_NAME:
            owner_class = owner if isinstance(owner, type) else type(owner)
            qualname = '{}.{}'.format(owner_class.__name__, code.co_name)

    module = str(frame.f_globals.get('__name__', '?')).removeprefix(PACKAGE_PREFIX)

    if qualname == MODULE_NAME:
        return module

    return '{}.{}()'.format(module, qualname.replace('.<locals>', ''))


def safe_log(
    message: str
):
    """
    Logs an INFO level message safely. Also prints it to the screen.

    Arguments:
        message {string} -- The message to log.
    """

    location = ''

    try:
        location = __get_location()

        if LOGGER is not None:
            LOGGER.log_info_message(location + message)
        else:
            print('{} INFO: {}{}'.format(datetime.now(), location, message))
    except Exception:
        print('{}{}'.format(location, message))


def safe_log_warning(
    message: str
):
    """
    Logs a WARN level message safely. Also prints it to the screen.

    Arguments:
        message {string} -- The message to log.
    """

    location = ''

    try:
        location = __get_location()

        if LOGGER is not None:
            LOGGER.log_warning_message(location + message)
        else:
            print('{} WARN: {}{}'.format(datetime.now(), location, message))
    except Exception:
        print('{}{}'.format(location, message))
