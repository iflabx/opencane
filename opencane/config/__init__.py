"""Configuration module for opencane."""

from opencane.config.loader import get_config_path, load_config
from opencane.config.schema import Config

__all__ = ["Config", "load_config", "get_config_path"]
