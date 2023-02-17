class Visualizer(object):
    def __init__(self, data, pix, config):
        self.__data__ = data
        self.__pix__ = pix
        self.__config__ = config
        self.__effect__ = []
        self.update_data(data)
