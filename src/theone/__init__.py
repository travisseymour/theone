"""theone - a Python port of neo, the digital rain from "The Matrix"."""

__version__ = "0.6.1"


class NeoError(Exception):
    """A fatal error. The message is printed to stderr and neo exits with status 1."""
