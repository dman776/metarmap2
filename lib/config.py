import json
from json import JSONEncoder
try:
    import lib.safe_logging as safe_logging
except ModuleNotFoundError as e:
    import safe_logging as safe_logging
from pprint import pprint
from types import SimpleNamespace
from lib import utils

try:
    import board
    import neopixel
except ModuleNotFoundError:
    pass
except NotImplementedError:
    pass


def load_airports(file):
    with open(file) as f:
        fdata = f.read()
    return json.loads(fdata)


class Config(object):
    def __init__(self, file):
        """
        Creates a new config object
        """
        self.__file__ = file
        self.__data__ = {}
        self.LED_PIN = None
        self.LED_ORDER = None
        self.read()
        self.suntimes = utils.get_sun_times(self)
        self.__airports__ = load_airports(self.__data__.airports_file)

    def read(self):
        with open(self.__file__, 'r') as f:
            self.__data__ = json.load(f, object_hook=lambda x: SimpleNamespace(**x))
        self.post_process()
        return

    def post_process(self):
        # LED config
        try:
            self.LED_PIN = eval("board.D" + str(self.__data__.led.pin))
            self.LED_ORDER = eval("neopixel." + self.__data__.led.order)
        except NameError as e:
            pass

    def write(self):
        with open(self.__file__, 'w') as f:
            json.dump(self.data, f, cls=MyJsonEncoder, indent=4)
        self.read()
        return

    def edit(self, key, value):
        if value in ['true', 'false']:
            value = value.capitalize()
        code = compile("self.__data__." + key + "=" + str(value), "<string>", "exec")
        exec(code)
        self.write()

    @property
    def data(self):
        return self.__data__

    def set_suntimes(self, suntimes):
        self.suntimes = suntimes

    @property
    def airports(self):
        return self.__airports__

class MyJsonEncoder(JSONEncoder):
    def default(self, o):
        return o.__dict__


if __name__ == '__main__':
    # safe_logging.safe_log("[cfg]" + "Config")
    config = Config("config.json")
    # config.edit("display_screen.enabled", False)
    # config.edit("display_screen.delay", "0.6")
    # config.edit("display_screen.locate_active", True)
    # config.write()
    pprint(config.airports)


