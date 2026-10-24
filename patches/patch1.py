import sys

from lib import safe_logging
# from config import Config
import json
from pprint import pprint


class Patch(object):
    def __init__(self):
        self.name = "TestPatch1"
        self.__file__ = "config.json"

    def patch(self):
        safe_logging.safe_log("[PATCH]applying patch ({0})".format(self.name))
        data = {}
        with open(self.__file__, 'r') as f:
            data = json.load(f)
        data["patch1"] = {"foo": "bar"}
        with open(self.__file__, 'w') as g:
            json.dump(data, g, indent=4)

        return True
