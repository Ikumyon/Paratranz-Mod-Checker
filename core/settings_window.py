from pathlib import Path
from PySide6.QtUiTools import QUiLoader
from PySide6.QtCore import QFile, Qt, QObject, Signal, QTranslator
from PySide6.QtWidgets import QMessageBox
import requests
from core.config_manager import ConfigManager

class SettingsDialog(QObject):
    saved = Signal()

    def __init__(self, parent=None, as_widget=False):
        super().__init__(parent)
        self.as_widget = as_widget
        self.loader = QUiLoader()
        ui_file_path = Path(__file__).parent.parent / "ui" / "settingsPage.ui"
        ui_file = QFile(str(ui_file_path))
        ui_file.open(QFile.ReadOnly)
        self.window = self.loader.load(ui_file, parent)
        ui_file.close()

        # UI要素の取得
        self.line_edit_url = self.window.findChild(object, "lineEditUrl")
        self.line_edit_token = self.window.findChild(object, "lineEditToken")
        self.btn_test = self.window.findChild(object, "btnTestConnection")
        self.label_status = self.window.findChild(object, "labelStatus")
        
        # 監視設定
        self.chk_enable_monitor = self.window.findChild(object, "chkEnableMonitor")
        self.spin_interval = self.window.findChild(object, "spinMonitorInterval")
        self.cb_interval_unit = self.window.findChild(object, "cbIntervalUnit")
        self.cb_localization = self.window.findChild(object, "cbLocalization")
        self.chk_minimize_to_tray = self.window.findChild(object, "chkMinimizeToTray")
        
        # 言語リストの初期化
        self.populate_languages()
        
        # 設定のロード
        self.load_settings()

        # シグナルの接続 (即時保存)
        if self.line_edit_url:
            self.line_edit_url.textChanged.connect(self.save_settings)
        if self.line_edit_token:
            self.line_edit_token.textChanged.connect(self.save_settings)
        if self.btn_test:
            self.btn_test.clicked.connect(self.test_connection)
            
        # 監視設定の変更を即時保存
        if self.chk_enable_monitor:
            self.chk_enable_monitor.toggled.connect(self.save_settings)
        if self.spin_interval:
            self.spin_interval.valueChanged.connect(self.save_settings)
        if self.cb_interval_unit:
            self.cb_interval_unit.currentIndexChanged.connect(self.save_settings)
        if self.chk_minimize_to_tray:
            self.chk_minimize_to_tray.toggled.connect(self.save_settings)
        if self.cb_localization:
            self.cb_localization.currentIndexChanged.connect(self.save_settings)

    def populate_languages(self):
        if not self.cb_localization:
            return
        
        self.cb_localization.clear()
        self.cb_localization.addItem(self.tr("System Default"), "")
        
        loc_dir = Path(__file__).parent.parent / "localization"
        if loc_dir.exists():
            for qm_file in loc_dir.glob("*.qm"):
                lang_code = qm_file.stem
                
                # .qmファイルから表示名を取得
                temp_translator = QTranslator()
                if temp_translator.load(str(qm_file)):
                    display_name = temp_translator.translate("Language", "Language Name")
                    if not display_name:
                        display_name = lang_code
                    self.cb_localization.addItem(display_name, lang_code)
                else:
                    self.cb_localization.addItem(lang_code, lang_code)

    def test_connection(self):
        url = self.line_edit_url.text().strip()
        token = self.line_edit_token.text().strip()

        if not url or not token:
            self.update_status("URLとトークンを入力してください", "warning")
            return

        self.update_status("接続中...", "default")
        self.window.repaint() # 状態を即座に反映

        try:
            # プロジェクト一覧を取得して認証チェック
            endpoint = f"{url.rstrip('/')}/projects"
            headers = {"Authorization": token}
            response = requests.get(endpoint, headers=headers, timeout=10)

            if response.status_code == 200:
                self.update_status("接続成功！", "ok")
            elif response.status_code == 401:
                self.update_status("認証エラー (トークンが無効)", "error")
            else:
                self.update_status(f"エラー: {response.status_code}", "error")
        except requests.exceptions.Timeout:
            self.update_status("タイムアウトしました", "error")
        except Exception as e:
            self.update_status(f"接続失敗: {str(e)}", "error")

    def update_status(self, text, status="default"):
        if self.label_status:
            self.label_status.setText(f"状態: {text}")
            self.label_status.setProperty("status", status)
            self.label_status.style().unpolish(self.label_status)
            self.label_status.style().polish(self.label_status)

    def load_settings(self):
        url = ConfigManager.get("api_url", "https://paratranz.cn/api")
        token = ConfigManager.get("api_token", "")
        
        if self.line_edit_url:
            self.line_edit_url.setText(url)
        if self.line_edit_token:
            self.line_edit_token.setText(token)
            
        # 監視設定
        if self.chk_enable_monitor:
            self.chk_enable_monitor.setChecked(ConfigManager.get("monitor_enabled", False))
        if self.spin_interval:
            self.spin_interval.setValue(ConfigManager.get("monitor_interval", 30))
        if self.cb_interval_unit:
            self.cb_interval_unit.setCurrentIndex(ConfigManager.get("monitor_unit_index", 1)) # デフォルト「分」
        if self.chk_minimize_to_tray:
            self.chk_minimize_to_tray.setChecked(ConfigManager.get("minimize_to_tray", True))
        
        if self.cb_localization:
            self.cb_localization.blockSignals(True)
            current_lang = ConfigManager.get("language", "")
            index = self.cb_localization.findData(current_lang)
            if index >= 0:
                self.cb_localization.setCurrentIndex(index)
            self.cb_localization.blockSignals(False)

    def save_settings(self):
        old_lang = ConfigManager.get("language", "")
        new_lang = self.cb_localization.currentData() if self.cb_localization else ""
        
        data = {
            "api_url": self.line_edit_url.text() if self.line_edit_url else "https://paratranz.cn/api",
            "api_token": self.line_edit_token.text() if self.line_edit_token else "",
            "monitor_enabled": self.chk_enable_monitor.isChecked() if self.chk_enable_monitor else False,
            "monitor_interval": self.spin_interval.value() if self.spin_interval else 30,
            "monitor_unit_index": self.cb_interval_unit.currentIndex() if self.cb_interval_unit else 1,
            "minimize_to_tray": self.chk_minimize_to_tray.isChecked() if self.chk_minimize_to_tray else True,
            "language": self.cb_localization.currentData() if self.cb_localization else ""
        }
        ConfigManager.save_config(data)
        self.saved.emit() # 設定変更を他へ通知するためにemitする
        
        # 言語が変更された場合に再起動を促すメッセージを表示
        if old_lang != new_lang:
            QMessageBox.information(
                self.window,
                self.tr("言語設定の変更"),
                self.tr("言語設定を反映するにはアプリの再起動が必要です。")
            )
        # 即時保存なので、saved.emit() は基本不要だが、
        # 他の画面で設定変更を検知したい場合のために残すことも可能。
        # ここでは遷移はさせないので emit しない。
