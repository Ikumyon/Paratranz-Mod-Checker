from pathlib import Path
from PySide6.QtUiTools import QUiLoader
from PySide6.QtCore import QFile, Qt, QEvent, QObject, Signal
from PySide6.QtWidgets import QFileDialog, QMessageBox, QPushButton
from PySide6.QtGui import QPixmap, QCursor
import requests
import re
import json
import sys
from datetime import datetime
from core.game_manager import GameManager
from core.config_manager import ConfigManager
from core.sync_manager import SyncManager

class AddProjectDialog(QObject):
    project_added = Signal() # プロジェクト追加完了を通知する信号

    def __init__(self, parent=None, as_widget=False):
        super().__init__(parent)
        self.as_widget = as_widget
        self.loader = QUiLoader()
        ui_file_path = Path(__file__).parent.parent / "ui" / "add_project_page.ui"
        ui_file = QFile(str(ui_file_path))
        ui_file.open(QFile.ReadOnly)
        self.window = self.loader.load(ui_file, parent)
        ui_file.close()

        # UI要素の取得
        self.line_edit_project_url = self.window.findChild(object, "lineEditProjectURL")
        self.line_edit_project_name = self.window.findChild(object, "lineEditProjectName")
        self.line_edit_game = self.window.findChild(object, "lineEditGame")
        self.line_edit_source_path = self.window.findChild(object, "lineEditSourcePath")
        
        self._project_desc = "" # 説明文の保持用
        self._updated_at = "" # 更新日時の保持用
        self._current_game_id = "" # ゲームIDの保持用
        self.btn_fetch_info = self.window.findChild(object, "btnFetchInfo")
        self.btn_browse_source = self.window.findChild(object, "btnBrowseSource")
        self.lbl_icon = self.window.findChild(object, "lblIcon")
        self.lbl_permission = self.window.findChild(object, "labelPermissionStatus")
        
        # 登録ボタンの作成（UIにないためPython側で追加）
        self.btn_add_project = QPushButton("このプロジェクトを追加")
        self.btn_add_project.setFixedHeight(40)
        self.btn_add_project.setEnabled(False) # 情報取得までは無効
        self.window.layout().insertWidget(self.window.layout().count() - 1, self.btn_add_project)

        # 権限ラベルの初期化
        if self.lbl_permission:
            self.lbl_permission.setText("未取得")
            self.lbl_permission.setProperty("status", "default")

        # アイコンラベルの設定（正方形）
        if self.lbl_icon:
            self.lbl_icon.setFixedSize(64, 64)
            self.lbl_icon.setScaledContents(True)
            self.lbl_icon.setObjectName("lblIcon")
            self.update_icon()

        # シグナルの接続
        self.btn_browse_source.clicked.connect(self.browse_source)
        # ゲーム名が変わったらアイコンも更新（APIセット時など）
        if self.line_edit_game:
            self.line_edit_game.textChanged.connect(self.update_icon)
        self.btn_fetch_info.clicked.connect(self.fetch_project_info)
        self.line_edit_project_url.textChanged.connect(self.on_url_changed)
        # 原文パスが変更されたらボタンの有効状態を更新
        if self.line_edit_source_path:
            self.line_edit_source_path.textChanged.connect(self.update_add_button_state)
        # プロジェクト名が変わった場合も（手動編集に備えて）チェック
        if self.line_edit_project_name:
            self.line_edit_project_name.textChanged.connect(self.update_add_button_state)
            
        self.btn_add_project.clicked.connect(self.handle_accepted)

    def on_url_changed(self, text):
        """URL入力欄が変更されたら、ボタンの有効化状態を切り替える"""
        self.btn_fetch_info.setEnabled(len(text.strip()) > 0)
        # URLが変わったら権限表示もリセット
        if self.lbl_permission:
            self.lbl_permission.setText("未取得")
            self.lbl_permission.setProperty("status", "default")
            self.lbl_permission.style().unpolish(self.lbl_permission)
            self.lbl_permission.style().polish(self.lbl_permission)

    def _log_api_response(self, endpoint, status_code, data):
        """APIのレスポンスをログファイルに追記する"""
        try:
            log_path = Path(sys.argv[0]).resolve().parent / "data" / "api_history.log"
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            log_entry = {
                "timestamp": timestamp,
                "endpoint": endpoint,
                "status": status_code,
                "data": data
            }
            # 親ディレクトリ（data）がない場合は作成
            log_path.parent.mkdir(parents=True, exist_ok=True)
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(log_entry, ensure_ascii=False) + "\n")
        except Exception as e:
            print(f"Failed to write API log: {e}")

    def extract_project_id(self, text):
        """URLまたは文字列からプロジェクトIDを抽出する"""
        text = text.strip()
        # 数字のみの場合
        if text.isdigit():
            return text
        # URLの場合 (https://paratranz.cn/projects/12345/...)
        match = re.search(r'projects/(\d+)', text)
        if match:
            return match.group(1)
        return None

    def fetch_project_info(self):
        """入力されたURL/IDからプロジェクト情報を取得する"""
        url_input = self.line_edit_project_url.text()
        project_id = self.extract_project_id(url_input)

        if not project_id:
            QMessageBox.warning(self.window, "エラー", "有効なプロジェクトIDまたはURLを入力してください。")
            return

        api_url = ConfigManager.get("api_url")
        token = ConfigManager.get("api_token")

        if not api_url or not token:
            QMessageBox.warning(self.window, "エラー", "先に設定画面でAPI URLとトークンを設定してください。")
            return

        # 取得中の表示
        old_text = self.btn_fetch_info.text()
        self.btn_fetch_info.setText("取得中...")
        self.btn_fetch_info.setEnabled(False)
        self.window.repaint()

        try:
            endpoint = f"{api_url.rstrip('/')}/projects/{project_id}"
            headers = {
                "Authorization": token,
                "Accept": "application/json"
            }
            response = requests.get(endpoint, headers=headers, timeout=10)
            
            # ログの記録
            self._log_api_response(endpoint, response.status_code, response.json() if response.status_code == 200 else response.text)

            if response.status_code == 200:
                project = response.json()
                self.line_edit_project_name.setText(project.get("name", ""))
                self._project_desc = project.get("desc", "")
                self._updated_at = project.get("updatedAt", "") # 更新日時を保持
                # IDを正規化（URLから数字のみにする）
                self.line_edit_project_url.setText(project_id)
                
                # ゲームの自動セット
                game_info = project.get("game")
                if game_info:
                    game_id = str(game_info)
                    self._current_game_id = game_id
                    game_data = GameManager.get_game_by_id(game_id)
                    if game_data:
                        self.line_edit_game.setText(game_data.get("name", game_id))
                    else:
                        self.line_edit_game.setText(game_id)
                else:
                    self._current_game_id = ""
                    self.line_edit_game.clear()

                # 権限情報の取得
                self.update_permission_status(project_id, headers)
                
                # 入力状況に応じて登録ボタンの有効状態を更新
                self.update_add_button_state()

                # アイコンの更新（ロゴURLがある場合）
                logo_url = project.get("logo")
                project_id_str = str(project_id)
                logos_dir = Path(sys.argv[0]).resolve().parent / "data" / "logos"
                local_logo_path = logos_dir / f"project_{project_id_str}.png"

                if logo_url:
                    try:
                        # 相対パスの場合はベースURLを補完
                        if not logo_url.startswith("http"):
                            base_url = api_url.split("/api")[0]
                            logo_url = base_url + logo_url
                        
                        img_res = requests.get(logo_url, timeout=5)
                        if img_res.status_code == 200:
                            # ディレクトリがなければ作成
                            logos_dir.mkdir(parents=True, exist_ok=True)
                            # ローカルに保存（ダウンロードのみ実施）
                            with open(local_logo_path, "wb") as f:
                                f.write(img_res.content)
                            
                            pixmap = QPixmap()
                            pixmap.loadFromData(img_res.content)
                            if not pixmap.isNull():
                                self.lbl_icon.setPixmap(pixmap)
                            else:
                                self.update_icon()
                        else:
                            self.update_icon()
                    except Exception as img_err:
                        print(f"Failed to fetch logo: {img_err}")
                        self.update_icon()
                else:
                    self.update_icon()
            else:
                QMessageBox.critical(self.window, "エラー", f"プロジェクト情報の取得に失敗しました。\nID: {project_id}\nStatus: {response.status_code}")
        except Exception as e:
            QMessageBox.critical(self.window, "エラー", f"通信エラーが発生しました: {str(e)}")
        finally:
            # 状態を戻す
            self.btn_fetch_info.setText(old_text)
            self.btn_fetch_info.setEnabled(True)


    def update_permission_status(self, project_id, headers):
        """提供された資料に基づき、権限状態を表示する"""
        if not self.lbl_permission:
            return

        api_url = ConfigManager.get("api_url")
        try:
            # 読み取り権限のチェック (GET /projects/{id}/files)
            files_endpoint = f"{api_url.rstrip('/')}/projects/{project_id}/files"
            res = requests.get(files_endpoint, headers=headers, timeout=5)
            
            if res.status_code == 200:
                # 読み取りOK、書き込み・削除は実行時確認
                status_text = "読み取り: OK / 書き込み: 実行時に確認"
                self.lbl_permission.setText(status_text)
                self.lbl_permission.setProperty("status", "ok")
            elif res.status_code == 403:
                self.lbl_permission.setText("アクセス権限がありません (403)")
                self.lbl_permission.setProperty("status", "error")
            elif res.status_code == 401:
                self.lbl_permission.setText("Tokenが無効です (401)")
                self.lbl_permission.setProperty("status", "error")
            else:
                self.lbl_permission.setText(f"確認失敗 (Status: {res.status_code})")
                self.lbl_permission.setProperty("status", "warning")
            
            self.lbl_permission.style().unpolish(self.lbl_permission)
            self.lbl_permission.style().polish(self.lbl_permission)

        except Exception as e:
            print(f"Failed to fetch permission: {e}")
            self.lbl_permission.setText("通信エラー")
            self.lbl_permission.setProperty("status", "error")
            self.lbl_permission.style().unpolish(self.lbl_permission)
            self.lbl_permission.style().polish(self.lbl_permission)

    def update_icon(self):
        # なければゲームごとのデフォルト
        game_name = self.line_edit_game.text() if self.line_edit_game else ""
        game = GameManager.get_game_by_name(game_name)
        
        # 仮のアイコン表示（assets/placeholder.png）
        icon_path = Path(__file__).parent.parent / "assets" / "placeholder.png"
        if icon_path.exists():
            pixmap = QPixmap(str(icon_path))
            self.lbl_icon.setPixmap(pixmap)
        else:
            self.lbl_icon.setText("No Icon")

    def browse_source(self):
        directory = QFileDialog.getExistingDirectory(self.window, "原文フォルダを選択")
        if directory:
            self.line_edit_source_path.setText(directory)

    def get_data(self):
        """入力されたデータを辞書形式で返す"""
        return {
            "project_id": self.line_edit_project_url.text(),
            "project_name": self.line_edit_project_name.text(),
            "description": self._project_desc,
            "updated_at": self._updated_at,
            "game": self._current_game_id, # IDを返す
            "source_path": self.line_edit_source_path.text()
        }

    def update_add_button_state(self):
        """入力状況に応じて「プロジェクトを追加」ボタンの有効状態を切り替える"""
        data = self.get_data()
        # ID, 名前, 原文パスがすべて入力されている場合のみ有効化
        is_valid = bool(
            data["project_id"].strip() and 
            data["project_name"].strip() and 
            data["source_path"].strip()
        )
        self.btn_add_project.setEnabled(is_valid)

    def handle_accepted(self):
        """確定処理（プロジェクトを追加）"""
        data = self.get_data()
        
        # 必須項目のチェック（念のため実行時にも行う）
        missing = []
        if not data["project_id"].strip():
            missing.append("プロジェクトID")
        if not data["project_name"].strip():
            missing.append("プロジェクト名")
        if not data["source_path"].strip():
            missing.append("原文フォルダ（パス）")
            
        if missing:
            msg = "以下の項目を入力してください：\n・" + "\n・".join(missing)
            QMessageBox.warning(self.window, "入力エラー", msg)
            return
        
        # 追加中の表示
        old_text = self.btn_add_project.text()
        self.btn_add_project.setText("追加中...")
        self.btn_add_project.setEnabled(False)
        self.window.repaint()

        try:
            from core.project_manager import ProjectManager
            ProjectManager.add_project(data)
            
            # 同期キャッシュの初期化
            try:
                SyncManager.initialize_cache_from_paratranz(data["project_id"])
            except Exception as e:
                print(f"Failed to initialize cache: {e}")
                # ここではエラーをログに留め、プロジェクト追加自体は継続する
                
            self.project_added.emit()
            self.clear_fields()
        finally:
            # 状態を戻す（成功時はclear_fieldsでリセットされるが、念のため）
            self.btn_add_project.setText(old_text)
            # 成功時は clear_fields が呼ばれてボタンは無効のままが正しい
            # 失敗した場合は再度押せるようにする必要があるかもしれないが、
            # 現状のコードでは成功時のみ emit される。

    def clear_fields(self):
        """入力欄をクリアする"""
        self.line_edit_project_url.clear()
        self.line_edit_project_name.clear()
        self.line_edit_game.clear()
        self.line_edit_source_path.clear()
        self._current_game_id = ""
        if self.lbl_permission:
            self.lbl_permission.setText("未取得")
            self.lbl_permission.setStyleSheet("color: gray;")
        self.update_icon()
