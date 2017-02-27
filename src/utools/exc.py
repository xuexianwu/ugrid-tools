from utools.base import AbstractUToolsException


class NoInteriorsError(AbstractUToolsException):
    def __init__(self, message=None):
        if message is None:
            message = 'Polygon has no holes or interiors. Nothing to do.'
        super(NoInteriorsError, self).__init__(message)
