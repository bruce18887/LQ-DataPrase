import os
import json
from typing import Optional, Dict
from pathlib import Path
from utils.encryption import get_encryption_manager


class ConfigManager:
    def __init__(self, config_dir=None):
        self.config_dir = config_dir or os.path.join(
            os.path.expanduser("~"), ".sftp_searcher"
        )
        os.makedirs(self.config_dir, exist_ok=True)
        self.config_file = os.path.join(self.config_dir, "config.json")
        self.encryption = get_encryption_manager()

    def save_connection(self, name: str, host: str, port: int, username: str, password: str):
        config = self._load_config()
        if "connections" not in config:
            config["connections"] = {}

        config["connections"][name] = {
            "host": host,
            "port": port,
            "username": username,
            "password_encrypted": self.encryption.encrypt(password),
        }
        self._save_config(config)
        print(f"Connection '{name}' saved successfully.")

    def load_connection(self, name: str) -> Optional[Dict]:
        config = self._load_config()
        if "connections" not in config or name not in config["connections"]:
            return None

        conn = config["connections"][name]
        return {
            "host": conn["host"],
            "port": conn["port"],
            "username": conn["username"],
            "password": self.encryption.decrypt(conn["password_encrypted"]),
        }

    def list_connections(self) -> list:
        config = self._load_config()
        if "connections" not in config:
            return []
        return list(config["connections"].keys())

    def delete_connection(self, name: str) -> bool:
        config = self._load_config()
        if "connections" not in config or name not in config["connections"]:
            return False
        del config["connections"][name]
        self._save_config(config)
        print(f"Connection '{name}' deleted.")
        return True

    def get_default_connection(self) -> Optional[str]:
        config = self._load_config()
        return config.get("default_connection")

    def set_default_connection(self, name: str) -> bool:
        config = self._load_config()
        if "connections" not in config or name not in config["connections"]:
            return False
        config["default_connection"] = name
        self._save_config(config)
        print(f"Default connection set to '{name}'.")
        return True

    def _load_config(self) -> Dict:
        if os.path.exists(self.config_file):
            with open(self.config_file, "r", encoding="utf-8") as f:
                return json.load(f)
        return {}

    def _save_config(self, config: Dict):
        with open(self.config_file, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=4, ensure_ascii=False)
