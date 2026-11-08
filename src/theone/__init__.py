from importlib.metadata import version

"""
theone - a Python port of neo, the digital rain from "The Matrix".
"""


__version__ = version("theone")


class NeoError(Exception):
    """A fatal error. The message is printed to stderr and neo exits with status 1."""
