import hashlib
import json
import requests
import zipfile
import io
from pathlib import Path
from datetime import datetime
import sys
import fnmatch
from core.config_manager import ConfigManager

class SyncManager:
    CACHE_FILE = Path(sys.argv[0]).resolve().parent / "data" / "sync_cache.json"

    @staticmethod
    def calculate_hash(file_path):
        """ファイルのMD5ハッシュを計算する"""
        hash_md5 = hashlib.md5()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                hash_md5.update(chunk)
        return hash_md5.hexdigest()

    @classmethod
    def load_cache(cls):
        if cls.CACHE_FILE.exists():
            try:
                with open(cls.CACHE_FILE, "r", encoding="utf-8") as f:
                    content = f.read().strip()
                    if not content:
                        return {}
                    return json.loads(content)
            except Exception as e:
                print(f"Error loading sync cache: {e}")
                # 壊れている場合はバックアップを取って空にするなどの対応も検討できるが、まずは空で返す
        return {}

    @classmethod
    def save_cache(cls, cache_data):
        try:
            # 親ディレクトリ（data）がない場合は作成
            cls.CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(cls.CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump(cache_data, f, indent=4, ensure_ascii=False)
        except Exception as e:
            print(f"Error saving sync cache: {e}")

    @classmethod
    def get_project_cache(cls, project_id):
        cache = cls.load_cache()
        return cache.get(str(project_id), {"files": {}})

    @classmethod
    def update_project_cache(cls, project_id, project_cache):
        cache = cls.load_cache()
        cache[str(project_id)] = project_cache
        cls.save_cache(cache)

    @classmethod
    def initialize_cache_from_paratranz(cls, project_id):
        """ParatranzからArtifactをダウンロードしてキャッシュを初期化する"""
        api_url = ConfigManager.get("api_url")
        token = ConfigManager.get("api_token")
        
        if not api_url or not token:
            raise Exception("API URLまたはTokenが設定されていません。")

        headers = {"Authorization": token}
        
        # 1. Paratranzのファイル一覧を取得
        files_url = f"{api_url.rstrip('/')}/projects/{project_id}/files"
        files_res = requests.get(files_url, headers=headers, timeout=10)
        res_json = files_res.json() if files_res.status_code == 200 else {"error": files_res.text}
        
        # ファイル一覧は膨大になる可能性があるため、件数のみ記録
        cls._log_api("get_files", project_id, files_res.status_code, {
            "url": files_url,
            "file_count": len(res_json) if isinstance(res_json, list) else len(res_json.get("results", [])),
            "message": "File list fetched successfully" if files_res.status_code == 200 else "Failed to fetch files"
        })

        if files_res.status_code != 200:
            raise Exception(f"ファイル一覧の取得に失敗しました (Status: {files_res.status_code})")
        
        res_json = files_res.json()
        if isinstance(res_json, list):
            remote_results = res_json
        else:
            remote_results = res_json.get("results", [])
        project_cache = {"files": {}}
        
        if not remote_results:
            # リモートが空の場合は空のキャッシュで初期化
            cls.update_project_cache(project_id, project_cache)
            return project_cache

        # 2. Artifactの生成リクエスト (POST /projects/{id}/artifacts)
        build_url = f"{api_url.rstrip('/')}/projects/{project_id}/artifacts"
        build_res = requests.post(build_url, headers=headers, timeout=30)
        cls._log_api("build_artifact", project_id, build_res.status_code, {
            "url": build_url,
            "message": "Artifact build requested"
        })

        # 3. Artifactのダウンロード (GET /projects/{id}/artifacts/download)
        download_url = f"{api_url.rstrip('/')}/projects/{project_id}/artifacts/download"
        response = requests.get(download_url, headers=headers, timeout=60)
        cls._log_api("download_artifact", project_id, response.status_code, {
            "url": download_url,
            "message": f"Download status: {response.status_code}"
        })

        if response.status_code != 200:
            raise Exception(f"Artifactのダウンロードに失敗しました (Status: {response.status_code})")

        # 4. ZIPを展開してハッシュ計算
        remote_files = {}
        for f in remote_results:
            # 'name' または 'path' フィールドからパスを取得
            remote_path = f.get("name") or f.get("path")
            if remote_path:
                remote_files[remote_path] = f

        with zipfile.ZipFile(io.BytesIO(response.content)) as z:
            for member in z.infolist():
                if member.is_dir():
                    continue
                
                full_path = member.filename
                # 'utf8/' フォルダ内のファイルのみを対象にする
                if not full_path.startswith("utf8/"):
                    continue
                
                # 'utf8/' を除いたパスを取得
                path = full_path[len("utf8/"):]
                content = z.read(member)
                file_hash = hashlib.md5(content).hexdigest()
                
                remote_info = remote_files.get(path, {})
                
                project_cache["files"][path] = {
                    "hash": file_hash,
                    "remote_file_id": remote_info.get("id"),
                    "last_sync_at": remote_info.get("updatedAt", datetime.now().isoformat())
                }
        
        cls._log_api("initialize_cache", project_id, 200, "Cache initialized from Artifact")
        cls.update_project_cache(project_id, project_cache)
        return project_cache

    @classmethod
    def check_sync(cls, project_data):
        """同期状態を確認する"""
        project_id = project_data.get("project_id")
        source_path = Path(project_data.get("source_path", ""))
        include_pattern = project_data.get("include_pattern", "*")
        exclude_pattern = project_data.get("exclude_pattern", "")
        
        if not source_path or not source_path.exists():
            return {"error": "ソースパスが無効です。"}

        cache_data = cls.load_cache()
        if str(project_id) not in cache_data:
            return {"status": "INITIALIZING"}
        
        cache = cache_data[str(project_id)]

        results = {
            "new": [],
            "modified": [],
            "deleted": [],
            "synced": []
        }

        # ローカルファイルの走査
        local_files = {}
        for file_path in source_path.rglob("*"):
            if file_path.is_dir():
                continue
            
            # source_pathからの相対パスを取得し、Paratranz形式（スラッシュ）にする
            rel_path = file_path.relative_to(source_path).as_posix()
            
            # フィルタリング
            if not cls._should_include(rel_path, include_pattern, exclude_pattern):
                continue

            current_hash = cls.calculate_hash(file_path)
            local_files[rel_path] = current_hash

            cached_info = cache["files"].get(rel_path)
            if not cached_info:
                results["new"].append({
                    "path": rel_path, 
                    "local_path": str(file_path),
                    "hash": current_hash
                })
            elif cached_info["hash"] != current_hash:
                results["modified"].append({
                    "path": rel_path, 
                    "local_path": str(file_path),
                    "remote_file_id": cached_info.get("remote_file_id"),
                    "hash": current_hash
                })
            else:
                results["synced"].append(rel_path)

        # 削除されたファイルの確認（キャッシュにあってローカルにないもの）
        # ただし、設定されたパターンの範囲外のファイルは無視する
        for cached_path, info in cache["files"].items():
            if cached_path not in local_files:
                # フィルタリング設定の範囲内にあるファイルのみ削除対象とする
                if cls._should_include(cached_path, include_pattern, exclude_pattern):
                    results["deleted"].append({
                        "path": cached_path,
                        "remote_file_id": info.get("remote_file_id")
                    })

        return {"status": "READY", "results": results}

    @staticmethod
    def _should_include(path, include_pat, exclude_pat):
        """パスがフィルタリング条件に合致するか判定する"""
        includes = [p.strip() for p in include_pat.split(",") if p.strip()] if include_pat else ["*"]
        excludes = [p.strip() for p in exclude_pat.split(",") if p.strip()] if exclude_pat else []

        # 包含チェック (いずれかにマッチすればOK)
        is_included = any(fnmatch.fnmatch(path, p) for p in includes)
        if not is_included:
            return False

        # 除外チェック (いずれかにマッチすれば除外)
        is_excluded = any(fnmatch.fnmatch(path, p) for p in excludes)
        return not is_excluded

    @staticmethod
    def has_changes(check_res):
        """同期チェック結果に変更が含まれるか判定する"""
        if check_res.get("status") == "READY":
            results = check_res.get("results", {})
            return bool(results.get("new") or results.get("modified") or results.get("deleted"))
        return False

    @classmethod
    def execute_sync(cls, project_data, check_res, callback=None):
        """同期を実行する"""
        if check_res.get("status") != "READY":
            return False, "Not ready"

        project_id = project_data.get("project_id")
        results = check_res.get("results", {})
        
        success_count = 0
        total_actions = len(results["new"]) + len(results["modified"]) + len(results["deleted"])
        
        # 新規と更新のアップロード
        for item in results["new"] + results["modified"]:
            if cls.upload_file(project_id, item["local_path"], item["path"], item.get("remote_file_id"), item.get("hash")):
                success_count += 1
            if callback: callback(success_count, total_actions)
            
        # 削除
        for item in results["deleted"]:
            if cls.delete_file(project_id, item["path"], item["remote_file_id"]):
                success_count += 1
            if callback: callback(success_count, total_actions)
            
        return success_count == total_actions, f"{success_count}/{total_actions} items synced"

    @classmethod
    def upload_file(cls, project_id, local_file_path, rel_path, remote_file_id=None, file_hash=None):
        """ファイルをアップロード（新規または更新）する"""
        api_url = ConfigManager.get("api_url")
        token = ConfigManager.get("api_token")
        
        headers = {"Authorization": token}
        
        # multipart/form-data でファイルを送信
        files = {
            "file": (rel_path, open(local_file_path, "rb"))
        }
        
        if remote_file_id:
            # 更新 (POST /projects/{id}/files/{fileId})
            url = f"{api_url.rstrip('/')}/projects/{project_id}/files/{remote_file_id}"
        else:
            # 新規 (POST /projects/{id}/files)
            url = f"{api_url.rstrip('/')}/projects/{project_id}/files"
        
        data = {"path": rel_path}
        response = requests.post(url, headers=headers, files=files, data=data, timeout=30)
        
        # 生のレスポンスデータをログに記録
        cls._log_api("upload_file", project_id, response.status_code, {
            "url": url,
            "path": rel_path,
            "response": response.json() if response.status_code in [200, 201] else response.text
        })
        
        if response.status_code in [200, 201]:
            # キャッシュを更新
            cache = cls.get_project_cache(project_id)
            new_hash = file_hash if file_hash else cls.calculate_hash(local_file_path)
            
            # APIのレスポンスから最新の情報を取得（IDなど）
            res_data = response.json()
            # 複数ファイルが返る場合もあるので確認が必要だが、通常は単一
            file_info = res_data if isinstance(res_data, dict) else (res_data[0] if res_data else {})
            
            # IDの確定（レスポンスになければ引数のものを使う）
            # ParaTranzのレスポンスは {"file": {"id": ...}, "revision": ...} の形式
            final_remote_id = file_info.get("id")
            if not final_remote_id and "file" in file_info:
                final_remote_id = file_info["file"].get("id")
            
            final_remote_id = final_remote_id or remote_file_id
            
            # 更新日時の取得
            updated_at = file_info.get("updatedAt")
            if not updated_at and "file" in file_info:
                updated_at = file_info["file"].get("updatedAt")
            
            cache["files"][rel_path] = {
                "hash": new_hash,
                "remote_file_id": final_remote_id,
                "last_sync_at": updated_at or datetime.now().isoformat()
            }
            cls.update_project_cache(project_id, cache)
            return True
        elif response.status_code == 400 and "exists" in response.text:
            # 既に存在する場合、IDを取得して更新として再試行
            remote_id = cls.get_remote_file_id_by_path(project_id, rel_path)
            if remote_id:
                return cls.upload_file(project_id, local_file_path, rel_path, remote_id, file_hash)
            else:
                print(f"Upload failed: {response.status_code} - {response.text}")
                return False
        else:
            print(f"Upload failed: {response.status_code} - {response.text}")
            return False

    @classmethod
    def get_remote_file_id_by_path(cls, project_id, rel_path):
        """パスからリモートのファイルIDを検索する"""
        api_url = ConfigManager.get("api_url")
        token = ConfigManager.get("api_token")
        headers = {"Authorization": token}
        
        files_url = f"{api_url.rstrip('/')}/projects/{project_id}/files"
        res = requests.get(files_url, headers=headers, timeout=10)
        cls._log_api(f"GET {files_url}", project_id, res.status_code, "File list fetched")
        if res.status_code == 200:
            res_json = res.json()
            results = res_json if isinstance(res_json, list) else res_json.get("results", [])
            for f in results:
                # 'name' または 'path' フィールドからパスを取得
                remote_path = f.get("name") or f.get("path")
                if remote_path == rel_path:
                    return f.get("id")
        return None

    @classmethod
    def delete_file(cls, project_id, rel_path, remote_file_id):
        """Paratranz上のファイルを削除する"""
        api_url = ConfigManager.get("api_url")
        token = ConfigManager.get("api_token")
        
        headers = {"Authorization": token}
        delete_url = f"{api_url.rstrip('/')}/projects/{project_id}/files/{remote_file_id}"
        
        response = requests.delete(delete_url, headers=headers, timeout=10)
        
        # 削除の実行結果を記録
        cls._log_api("delete_file", project_id, response.status_code, {
            "url": delete_url,
            "path": rel_path,
            "response": response.json() if response.status_code == 200 else response.text
        })
        
        if response.status_code == 200:
            # キャッシュから削除
            cache = cls.get_project_cache(project_id)
            if rel_path in cache["files"]:
                del cache["files"][rel_path]
            cls.update_project_cache(project_id, cache)
            return True
        else:
            print(f"Delete failed: {response.status_code} - {response.text}")
            return False

    @staticmethod
    def _log_api(endpoint, project_id, status_code, data):
        """APIのレスポンスをログファイルに追記する"""
        try:
            log_path = Path(sys.argv[0]).resolve().parent / "data" / "api_history.log"
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            log_entry = {
                "timestamp": timestamp,
                "endpoint": endpoint,
                "project_id": project_id,
                "status": status_code,
                "data": data
            }
            # 親ディレクトリ（data）がない場合は作成
            log_path.parent.mkdir(parents=True, exist_ok=True)
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(log_entry, ensure_ascii=False) + "\n")
        except Exception as e:
            print(f"Failed to write API log in SyncManager: {e}")
