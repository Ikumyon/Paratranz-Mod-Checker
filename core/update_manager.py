import requests
from typing import Optional, Dict, Any

class UpdateManager:
    """アプリのアップデートを確認するクラス。"""
    
    REPO_OWNER = "Ikumyon"
    REPO_NAME = "Paratranz-Mod-Checker"
    GITHUB_API_URL = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/releases/latest"

    @classmethod
    def check_for_update(cls, current_version: str) -> Optional[Dict[str, Any]]:
        """最新バージョンをチェックし、更新があれば情報を返す。"""
        try:
            response = requests.get(cls.GITHUB_API_URL, timeout=10)
            if response.status_code != 200:
                print(f"Failed to check for update: {response.status_code}")
                return None
            
            latest_release = response.json()
            latest_version = latest_release.get("tag_name", "").lstrip("v")
            
            if not latest_version:
                return None
                
            if cls._is_newer(current_version, latest_version):
                return {
                    "version": latest_version,
                    "url": latest_release.get("html_url"),
                    "body": latest_release.get("body"),
                    "published_at": latest_release.get("published_at")
                }
        except Exception as e:
            print(f"Update check error: {e}")
            
        return None

    @staticmethod
    def _is_newer(current: str, latest: str) -> bool:
        """latest が current より新しいか判定する。"""
        try:
            # 簡易的なセマンティックバージョニング比較 (x.y.z)
            curr_parts = [int(p) for p in current.split(".")]
            late_parts = [int(p) for p in latest.split(".")]
            
            # 長さを合わせる (1.0 vs 1.0.1 のようなケース)
            max_len = max(len(curr_parts), len(late_parts))
            curr_parts += [0] * (max_len - len(curr_parts))
            late_parts += [0] * (max_len - len(late_parts))
            
            return late_parts > curr_parts
        except Exception:
            # 比較に失敗した場合は単純な不一致で判断
            return current != latest
