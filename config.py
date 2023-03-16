import json
import sys
from json import JSONEncoder
import lib.safe_logging as safe_logging
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


class Config(object):
    def __init__(self, file, app_version):
        """
        Creates a new config object
        """
        self.__file__ = file
        self.__data__ = {}
        self.app_version = app_version
        self.LED_PIN = None
        self.LED_ORDER = None
        self.read()
        self.suntimes = utils.get_sun_times(self)
        self.__airports__ = {}
        self.read_airports()
        self.__renderer__ = None
        self.__display__ = None

    def read(self):
        with open(self.__file__, 'r') as f:
            self.__data__ = json.load(f, object_hook=lambda x: SimpleNamespace(**x))
        self.__post_process__()
        return

    def __post_process__(self):
        # LED config
        try:
            self.LED_PIN = eval("board.D" + str(self.__data__.led.pin))
            self.LED_ORDER = eval("neopixel." + self.__data__.led.order)
        except NameError as e:
            pass

    def write(self):
        with open(self.__file__, 'w') as f:
            json.dump(self.__data__, f, cls=MyJsonEncoder, indent=4)
        self.read()
        return

    def edit(self, key, value):
        if value in ['true', 'false']:
            value = value.capitalize()
        code = compile("self.__data__." + key + "=" + str(value), "<string>", "exec")
        exec(code)
        self.write()

    @property
    def renderer(self):
        return self.__renderer__

    @renderer.setter
    def renderer(self, ren):
        self.__renderer__ = ren

    @property
    def display(self):
        return self.__display__

    @display.setter
    def display(self, dis):
        self.__display__ = dis

    @property
    def data(self):
        return self.__data__

    def set_suntimes(self, suntimes):
        self.suntimes = suntimes

    @property
    def airports(self):
        return self.__airports__

    def read_airports(self):
        with open(self.__data__.airports_file) as f:
            fdata = f.read()
        self.__airports__ = json.loads(fdata)

    def write_airports(self):
        self.display.event.set()
        with open(self.__data__.airports_file, "w") as f:
            f.write(json.dumps(self.__airports__, indent=4))
        self.read_airports()
        # refresh display loop to pick up new config
        self.display.restart()

    def edit_airport(self, oldkey, newkey):
        # need to keep the existing order
        rep = {oldkey: newkey}
        for k, v in list(self.__airports__.items()):
            self.__airports__[rep.get(k, k)] = self.__airports__.pop(k)
        self.write_airports()

    def edit_airport_property(self, airport, key, value):
        # if boolean, force it!
        if value in ['true', 'false']:
            value = value.capitalize()
            value = eval(value)
        self.__airports__[airport][key] = value
        self.write_airports()


class MyJsonEncoder(JSONEncoder):
    def default(self, o):
        return o.__dict__


if __name__ == '__main__':
    # safe_logging.safe_log("[cfg]" + "Config")
    config = Config("config.json")
    # config.edit("display_screen.enabled", False)
    # config.edit("display_screen.delay", "0.6")
    # config.edit("display_screen.locate_active", True)
    # pprint(config.airports)


