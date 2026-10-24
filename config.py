import json
from lib import utils
from metarmap.settings import Settings

try:
    import board
    import neopixel
except ModuleNotFoundError:
    pass
except NotImplementedError:
    pass

__version__ = "2.2.4"


class Config(object):
    def __init__(self, file):
        """
        Creates a new config object
        """
        self.__file__ = file
        self.__data__ = Settings()
        self.app_version = __version__
        self.LED_PIN = None
        self.LED_ORDER = None
        self.read()
        self.suntimes = None
        self.__airports__ = {}
        self.read_airports()
        self.__renderer__ = None  # set later (for convenience)
        self.__display__ = None  # set later (for convenience)

    def read(self):
        self.__data__ = Settings.load(self.__file__)
        self.__post_process__()

    def __post_process__(self):
        # LED config (only available on the Pi)
        try:
            self.LED_PIN = getattr(board, "D" + str(self.__data__.led.pin), None)
            self.LED_ORDER = getattr(neopixel, self.__data__.led.order, None)
        except NameError:
            pass

    def write(self):
        self.__data__.save(self.__file__)
        self.read()

    def edit(self, key, value):
        """
        Saves one setting by its dotted path, e.g. edit("display_screen.delay", "5").
        Raises KeyError for an unknown setting and ValueError for a value of the wrong type.
        """
        self.__data__.set(key, value)
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

    def set_suntimes(self):
        # self.suntimes = suntimes
        self.suntimes = utils.get_sun_times(self)

    @property
    def airports(self):
        return self.__airports__

    def read_airports(self):
        with open(self.__data__.airports_file) as f:
            fdata = f.read()
        self.__airports__ = json.loads(fdata)

    def write_airports(self):
        with open(self.__data__.airports_file, "w") as f:
            f.write(json.dumps(self.__airports__, indent=4))
        self.read_airports()
        # refresh display loop to pick up new config
        if self.display:
            self.display.restart(timeout=15)

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


if __name__ == '__main__':
    # safe_logging.safe_log("[cfg]" + "Config")
    config = Config("config.json")
    # config.edit("display_screen.enabled", False)
    # config.edit("display_screen.delay", "0.6")
    # config.edit("display_screen.locate_active", True)
    # pprint(config.airports)


