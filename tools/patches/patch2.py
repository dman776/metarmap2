from metarmap.lib import safe_logging
from metarmap.config import Config


class Patch(object):
    def __init__(self):
        self.name = "TestPatch2"

    def patch(self):
        safe_logging.safe_log("[PATCH]applying patch ({0})".format(self.name))
        return True
