from lib import safe_logging
from config import Config


class Visualizer(object):
    def __init__(self, data, pix, config):
        self.__data__ = data
        self.__pix__ = pix
        self.__config__: Config = config
        self.__effect__ = []
        self.__exclusive__ = False  # used to have exclusive control of renderer (ie. no locate() function!)

    @property
    def exclusive(self):
        return self.__exclusive__

    def get_effects(self):
        return self.__effect__

    def update_data(self, data):
        safe_logging.safe_log("[v]updating data in the visualizer ({0})".format(self.name))
        self.__data__ = data
        self.__effect__ = []  # clear existing effects
