"""Configuration loader for the collector."""

import os
import yaml


def load_config(config_path: str = None) -> dict:
    """Load configuration from YAML file."""
    if config_path is None:
        config_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)), "config.yaml"
        )
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def get_enabled_targets(config: dict) -> list[dict]:
    """Return only enabled collection targets."""
    return [t for t in config.get("targets", []) if t.get("enabled", True)]
