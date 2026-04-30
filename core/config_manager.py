import json
import sys
from pathlib import Path

class ConfigManager:
    CONFIG_FILE = Path(sys.argv[0]).resolve().parent / "data" / "config.json"

    @classmethod
    def load_config(cls):
        if cls.CONFIG_FILE.exists():
            try:
                with open(cls.CONFIG_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                print(f"Error loading config: {e}")
        return {}

    @classmethod
    def save_config(cls, data):
        try:
            # 既存の設定を読み込んで更新
            config = cls.load_config()
            config.update(data)
            with open(cls.CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(config, f, indent=4, ensure_ascii=False)
        except Exception as e:
            print(f"Error saving config: {e}")

    @classmethod
    def get(cls, key, default=None):
        config = cls.load_config()
        return config.get(key, default)
