import json
from pathlib import Path
from typing import List, Dict, Optional, Any

class GameManager:
    _games: Optional[List[Dict[str, Any]]] = None

    @classmethod
    def load_games(cls) -> List[Dict[str, Any]]:
        """games.jsonからゲーム一覧を読み込む（キャッシュ付き）"""
        if cls._games is None:
            json_path = Path(__file__).parent.parent / "data" / "games.json"
            if json_path.exists():
                try:
                    with open(json_path, "r", encoding="utf-8") as f:
                        cls._games = json.load(f)
                except Exception as e:
                    print(f"Error loading games.json: {e}")
                    cls._games = []
            else:
                cls._games = []
        return cls._games

    @classmethod
    def get_game_names(cls) -> List[str]:
        """全ゲームの名前一覧を取得する"""
        return [game["name"] for game in cls.load_games()]

    @classmethod
    def _get_game_by_field(cls, field: str, value: Any) -> Optional[Dict[str, Any]]:
        """指定したフィールドの値に一致するゲーム情報を取得する"""
        for game in cls.load_games():
            if game.get(field) == value:
                return game
        return None

    @classmethod
    def get_game_by_name(cls, name: str) -> Optional[Dict[str, Any]]:
        """IDからゲーム名を取得する"""
        return cls._get_game_by_field("name", name)

    @classmethod
    def get_game_by_id(cls, game_id: str) -> Optional[Dict[str, Any]]:
        """IDからゲーム情報を取得する"""
        return cls._get_game_by_field("id", game_id)

    @classmethod
    def get_game_display_name(cls, game_id: str) -> str:
        """IDから表示用のゲーム名を取得する。見つからない場合はIDを返す。"""
        if not game_id:
            return ""
        game = cls.get_game_by_id(game_id)
        if game:
            return game.get("name", game_id)
        return game_id
