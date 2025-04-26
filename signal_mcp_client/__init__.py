try:
    from ._version import version as __version__
except ImportError:
    # Development installation without version info
    __version__ = "0.0.0.dev0+unknown"
