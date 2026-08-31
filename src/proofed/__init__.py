"""Proofed public deterministic completion gate."""

from importlib.metadata import PackageNotFoundError, version


try:
    __version__ = version("proofed-agent")
except PackageNotFoundError:  # Source tree used before installation.
    __version__ = "0.0.0+local"
