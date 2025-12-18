"""Configuration loader - reads config.yaml and environment variables"""

import os
import yaml
from pathlib import Path
from typing import Any, Dict

CONFIG_PATH = Path(__file__).parent.parent.parent / "config" / "config.yaml"


def substitute_env_vars(value: Any) -> Any:
    """Recursively substitute ${VAR} with environment variables"""
    if isinstance(value, str):
        # Replace ${VAR} with os.getenv("VAR", "")
        import re
        pattern = r'\$\{([^}]+)\}'
        matches = re.findall(pattern, value)
        for match in matches:
            env_value = os.getenv(match, f"${{{match}}}")
            value = value.replace(f"${{{match}}}", str(env_value))

        # Try to convert to int if it looks like a number
        try:
            return int(value)
        except ValueError:
            return value
    elif isinstance(value, dict):
        return {k: substitute_env_vars(v) for k, v in value.items()}
    elif isinstance(value, list):
        return [substitute_env_vars(v) for v in value]
    else:
        return value


def load_config(config_path: Path = CONFIG_PATH) -> Dict:
    """Load configuration from YAML file with environment variable substitution"""
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    with open(config_path, 'r') as f:
        config = yaml.safe_load(f)

    # Substitute environment variables
    config = substitute_env_vars(config)

    return config


def get_config() -> Dict:
    """Singleton-like function to get config"""
    return load_config()


class Config:
    """Configuration object with dot-notation access"""
    def __init__(self, data: Dict = None):
        if data is None:
            data = load_config()
        self._data = data

    def get(self, key: str, default: Any = None) -> Any:
        """Get value by dot-separated key path (e.g., 'instagram.user_id')"""
        keys = key.split('.')
        value = self._data
        for k in keys:
            if isinstance(value, dict):
                value = value.get(k)
            else:
                return default
        return value if value is not None else default

    def __getattr__(self, name: str) -> Any:
        """Allow dot-notation access"""
        if name.startswith('_'):
            return super().__getattr__(name)
        return self._data.get(name)

    def __repr__(self):
        return f"<Config {self._data}>"


# Global config instance
_config_instance = None


def get_config_instance() -> Config:
    """Get or create global config instance"""
    global _config_instance
    if _config_instance is None:
        _config_instance = Config()
    return _config_instance
