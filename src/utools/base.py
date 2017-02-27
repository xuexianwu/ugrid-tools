from abc import ABCMeta


class AbstractUToolsObject(object):
    __metaclass__ = ABCMeta


class AbstractUToolsException(Exception):
    def __init__(self, message=None):
        self.message = message

    def __str__(self):
        return self.message
