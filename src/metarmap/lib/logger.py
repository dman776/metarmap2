"""
Simple wrapper around a logger.
"""
import logging
import logging.handlers
import threading
from datetime import datetime

LOG_NAME = "metarmap"

_lock = threading.Lock()


def _escape(text):
    """
    Replaces escape sequences do they can be printed.

    Funny story. PyDoc can't unit test strings with a CR or LF...
    It gives a white space error.

    >>> _escape("text")
    'text'
    >>> _escape("")
    ''
    """

    return str(text).replace('\r', '\\r').replace('\n', '\\n').replace('\x1a', '\\x1a')


class Logger(object):
    """
    Wrapper around a normal logger so stuff gets printed too.
    """

    def info(self, message_to_log):
        self.log_info_message(message_to_log, True)

    def warn(self, message_to_log):
        self.log_warning_message(message_to_log)

    def log_info_message(self, message_to_log, print_to_screen=True):
        """ Log and print at Info level """
        try:
            _lock.acquire()

            if print_to_screen:
                text = "{} INFO: {}".format(
                    datetime.utcnow(), _escape(message_to_log))
                print(text)
            self._logger.info(_escape(message_to_log))
        finally:
            _lock.release()

        return message_to_log

    def log_warning_message(self, message_to_log):
        """ Log and print at Warning level """
        try:
            _lock.acquire()

            text = "{} WARN: {}".format(datetime.utcnow(), message_to_log)
            self._logger.warning(_escape(text))
        finally:
            _lock.release()

        return message_to_log

    def __init__(self, logger):
        self._logger = logger


_python_logger = logging.getLogger(LOG_NAME)
_python_logger.setLevel(logging.DEBUG)
_handler = logging.handlers.RotatingFileHandler(
    "metarmap.log",
    maxBytes=10485760,
    backupCount=10)
_handler.setFormatter(logging.Formatter(
    '%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
_python_logger.addHandler(_handler)

LOGGER = Logger(_python_logger)
