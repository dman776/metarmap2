from lib import safe_logging

class Visualizer(object):
    def __init__(self, data, pix, config):
        self.__data__ = data
        self.__pix__ = pix
        self.__config__ = config
        self.__effect__ = []
        # self.update_data(data)

    def get_effects(self):
        return self.__effect__

    def update_data(self, data):
        safe_logging.safe_log("[v]updating data in the visualizer ({0})".format(self.name))
        self.__data__ = data
        self.__effect__ = []  # clear existing effects
