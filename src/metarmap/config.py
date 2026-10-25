import json

from metarmap.settings import Settings


class Config(object):
    """
    The map's settings (config.json) and its airports (airports.json), in LED order.
    """
    def __init__(self, file):
        self.__file__ = file
        self.__data__ = Settings()
        self.read()
        self.__airports__ = {}
        self.read_airports()

    def read(self):
        self.__data__ = Settings.load(self.__file__)

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
    def data(self):
        return self.__data__

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

    def edit_airport(self, oldkey, newkey):
        # need to keep the existing order
        rep = {oldkey: newkey}
        for k, v in list(self.__airports__.items()):
            self.__airports__[rep.get(k, k)] = self.__airports__.pop(k)
        self.write_airports()

    def edit_airport_property(self, airport, key, value):
        # "true"/"false" from the URL are stored as booleans
        if value in ['true', 'false']:
            value = value == 'true'
        self.__airports__[airport][key] = value
        self.write_airports()
