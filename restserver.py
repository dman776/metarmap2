import bottle
from bottle import hook, route, run, request, abort, response, static_file

from lib.safe_logging import safe_log
import threading

CONFIGURATION_HOST_PORT = 8081


class RESTServer(object):
    """
    Class to handle running a REST endpoint to handle configuration.
    """

    def get_server_ip(
        self
    ):
        """
        Returns the IP address of this REST server.

        Returns:
            string -- The IP address of this server.
        """

        return '0.0.0.0'

    def run(
        self
    ):
        """
        Starts the server.
        """

        safe_log("localhost = {}:{}".format(self.__local_ip__, self.__port__))
        threading.Thread(target=self.__httpd__.run, kwargs=dict(host=self.__local_ip__, port=self.__port__)).start()

    def stop(self):
        if self.__httpd__ is not None:
            self.__httpd__ = None

    def __init__(
        self
    ):
        self.__port__ = CONFIGURATION_HOST_PORT
        self.__local_ip__ = self.get_server_ip()
        self.__httpd__ = bottle

    @route('/', method='GET')
    def index():
        return "Hello REST API Server!"