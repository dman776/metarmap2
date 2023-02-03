import json
try:
    import lib.safe_logging as safe_logging
except ModuleNotFoundError as e:
    import safe_logging as safe_logging
from pprint import pprint
from types import SimpleNamespace
try:
    import board
    import neopixel
except:
    pass

class Config(object):
    def read(self):
        with open(self.__file__, 'r') as f:
            self.__data__ = json.load(f, object_hook= lambda x: SimpleNamespace(**x))
        # self.post_process()
        return

    def post_process(self):
        # LED config
        # self.LED_PIN = eval("board.D" + str(self.__data__.led.pin))
        # self.LED_ORDER = eval("neopixel." + self.__data__.led.order)

    def write(self):
        with open(self.__file__, 'w') as f:
            json.dump(config, f)
        self.read()
        return

    def edit(self, key, value):
        # config['key3'] = 'value3'
        return

    def data(self):
        return self.__data__

    def __init__(self, file):
        """
        Creates a new config object
        """
        self.__file__ = file
        self.__data__ = {}
        # self.LED_PIN = None
        # self.LED_ORDER = None
        self.read()


if __name__ == '__main__':
    safe_logging.safe_log("Config")
    config = Config("../config.json")
    pprint(config.data().led.brightness)
    pprint(config.data().color.cat.vfr.fade)
    # pprint(config.LED_ORDER)
    # pprint(config.LED_PIN)



