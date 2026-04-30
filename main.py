import sys
import ctypes
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import shiboken6
from PySide6.QtCore import QFile, QObject, QEvent, QSize, Qt, QTimer, QUrl, QTranslator
from PySide6.QtGui import QDesktopServices, QIcon, QPixmap
from PySide6.QtUiTools import QUiLoader
from PySide6.QtWidgets import (
    QApplication,
    QAbstractItemView,
    QButtonGroup,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLayout,
    QLineEdit,
    QMessageBox,
    QMenu,
    QPushButton,
    QSizePolicy,
    QSystemTrayIcon,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from core.add_project_window import AddProjectDialog
from core.config_manager import ConfigManager
from core.game_manager import GameManager
from core.project_manager import ProjectManager
from core.settings_window import SettingsDialog
from core.sync_manager import SyncManager


BASE_DIR = Path(__file__).parent
APP_NAME = "Paratranz Mod Checker"
DEFAULT_API_BASE_URL = "https://paratranz.cn"


class NavWidgetItem(QWidget):
    """サイドバーの各アイテムを表示するウィジェット。"""

    def __init__(self, text: str, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TranslucentBackground)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 5, 0)
        layout.setSpacing(5)

        self.label_text = QLabel(text)
        self.label_text.setStyleSheet("background: transparent;")
        self.label_text.setAttribute(Qt.WA_TransparentForMouseEvents)

        self.label_badge = QLabel("")
        self.label_badge.setObjectName("badgeLabel")
        self.label_badge.setAlignment(Qt.AlignCenter)
        self.label_badge.setFixedSize(24, 20)
        self.label_badge.hide()
        self.label_badge.setAttribute(Qt.WA_TransparentForMouseEvents)

        layout.addWidget(self.label_text)
        layout.addStretch()
        layout.addWidget(self.label_badge)
        layout.setAlignment(self.label_text, Qt.AlignVCenter)
        layout.setAlignment(self.label_badge, Qt.AlignVCenter)

    def set_selected(self, selected: bool):
        weight = "bold" if selected else "normal"
        color = "palette(highlighted-text)" if selected else "palette(text)"
        self.label_text.setStyleSheet(
            f"background: transparent; color: {color}; font-weight: {weight};"
        )

    def set_badge(self, count: int):
        if count > 0:
            self.label_badge.setText(str(count))
            self.label_badge.show()
        else:
            self.label_badge.hide()


class MainWindow(QObject):
    """メイン画面の制御クラス。

    main.py は画面全体の配線だけを担当し、同期処理や設定保存などの実処理は
    ProjectManager / SyncManager / ConfigManager に寄せる。
    """

    TIMER_MULTIPLIERS = [
        1000,                      # 秒
        60 * 1000,                 # 分
        60 * 60 * 1000,            # 時間
        24 * 60 * 60 * 1000,       # 日
        7 * 24 * 60 * 60 * 1000,   # 週間
        30 * 24 * 60 * 60 * 1000,  # 月（概算）
        365 * 24 * 60 * 60 * 1000, # 年（概算）
    ]

    def __init__(self):
        super().__init__()

        self.loader = QUiLoader()
        self.window = self._load_ui("ui/paratranz_mod_checker.ui")
        self.current_filter_game: Optional[str] = None
        self.current_side_project_id: Optional[str] = None
        self.last_nav_index = 0
        self.nav_widgets: dict[int, NavWidgetItem] = {}

        self._apply_style()
        self._apply_logo()
        self._bind_main_widgets()
        self._setup_sync_table()
        self._setup_game_filter()
        self._setup_pages()
        self._setup_sidebar_nav()
        self._setup_side_panel()
        self._connect_actions()

        self.window.installEventFilter(self)

        self.setup_timer()
        self.setup_tray_icon()
        self.load_projects()
        self._select_initial_page()

    # ------------------------------------------------------------------
    # 初期化
    # ------------------------------------------------------------------

    def _load_ui(self, relative_path: str):
        ui_file = QFile(str(BASE_DIR / relative_path))
        ui_file.open(QFile.ReadOnly)
        window = self.loader.load(ui_file)
        ui_file.close()
        return window

    def _apply_style(self):
        style_path = BASE_DIR / "assets" / "style.qss"
        if style_path.exists():
            self.window.setStyleSheet(style_path.read_text(encoding="utf-8"))

    def _apply_logo(self):
        # ウィンドウアイコン設定 (icon.png)
        icon_path = BASE_DIR / "assets" / "icon.png"
        if icon_path.exists():
            self.window.setWindowIcon(QIcon(str(icon_path)))

        # 画面内ロゴ設定 (app_logo.svg)
        logo_path = BASE_DIR / "assets" / "app_logo.svg"
        if not logo_path.exists():
            return

        lbl_logo = self.window.findChild(QLabel, "lblLogo")
        if lbl_logo:
            pixmap = QPixmap(str(logo_path))
            lbl_logo.setPixmap(
                pixmap.scaled(160, 160, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            )
            lbl_logo.setText("")
            lbl_logo.setAlignment(Qt.AlignCenter)
            lbl_logo.setStyleSheet("background: transparent;")
            lbl_logo.setContentsMargins(10, 10, 10, 10)

    def _bind_main_widgets(self):
        self.stacked_widget = self.window.findChild(QWidget, "stackedWidget")
        self.table_sync = self.window.findChild(QWidget, "tableSync")
        self.scroll_area_content = self.window.findChild(QWidget, "scrollAreaContent")
        self.layout_project_cards = self.window.findChild(QVBoxLayout, "layoutProjectCards")
        self.card_template = self.window.findChild(QFrame, "projectCardBase")
        self.list_widget = self.window.findChild(QWidget, "listWidget")

    def _setup_sync_table(self):
        if not self.table_sync:
            return

        self.table_sync.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table_sync.setSelectionMode(QAbstractItemView.NoSelection)
        self.table_sync.setFocusPolicy(Qt.NoFocus)

        header = self.table_sync.horizontalHeader()
        header.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, header.ResizeMode.Fixed)
        header.setSectionResizeMode(1, header.ResizeMode.Stretch)
        header.setSectionResizeMode(2, header.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, header.ResizeMode.Fixed)

        self.table_sync.setColumnWidth(0, 50)
        self.table_sync.setColumnWidth(3, 100)

    def _setup_game_filter(self):
        self.layout_game_filter = self.window.findChild(QHBoxLayout, "layoutGameFilter")
        self.btn_filter_all = self.window.findChild(QToolButton, "btnGameFilterAll")
        self.cb_game_filter = self.window.findChild(QComboBox, "cbGameFilter")
        self.frame_game_filter = self.window.findChild(QFrame, "frameGameFilter")
        self.w_game_filter = self.window.findChild(QWidget, "wGameFilter")
        self.game_button_group = QButtonGroup(self.window)
        self.game_button_group.setExclusive(True)

        if self.btn_filter_all:
            self.btn_filter_all.setCheckable(True)
            self.btn_filter_all.setChecked(True)
            self.game_button_group.addButton(self.btn_filter_all)
            self.btn_filter_all.clicked.connect(lambda: self.filter_projects(None))

        if self.cb_game_filter:
            self.cb_game_filter.hide()
            self.cb_game_filter.activated.connect(self._on_combo_filter_activated)

        if self.frame_game_filter:
            self.layout_game_filter.setSizeConstraint(QLayout.SetNoConstraint)
            self.frame_game_filter.setMinimumWidth(1)
            self.frame_game_filter.installEventFilter(self)

        if self.w_game_filter:
            self.w_game_filter.layout().setSizeConstraint(QLayout.SetNoConstraint)
            self.w_game_filter.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
            self.w_game_filter.setMinimumWidth(1)
            self.w_game_filter.installEventFilter(self)

    def _setup_pages(self):
        self.add_project_widget = AddProjectDialog(self.window, as_widget=True)
        self.settings_widget = SettingsDialog(self.window, as_widget=True)

        if self.stacked_widget:
            self.stacked_widget.addWidget(self.add_project_widget.window)
            self.stacked_widget.addWidget(self.settings_widget.window)

        if hasattr(self.add_project_widget, "project_added"):
            self.add_project_widget.project_added.connect(self.on_project_added_success)
        if hasattr(self.settings_widget, "saved"):
            self.settings_widget.saved.connect(self.on_settings_saved)

    def _setup_sidebar_nav(self):
        if not self.list_widget:
            return

        self.list_widget.currentRowChanged.connect(self.on_nav_changed)

        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            text = item.text()
            item.setText("")

            nav_widget = NavWidgetItem(text)
            self.list_widget.setItemWidget(item, nav_widget)
            self.nav_widgets[i] = nav_widget

    def _setup_side_panel(self):
        self.frame_side_panel = self.window.findChild(QFrame, "frameSidePanel")
        self.btn_side_close = self.window.findChild(QToolButton, "btnSideClose")
        self.btn_side_link = self.window.findChild(QToolButton, "btnSideLink")
        self.lbl_side_title = self.window.findChild(QLabel, "lblSideTitle")
        self.btn_side_delete_action = self.window.findChild(QPushButton, "btnSideDeleteAction")

        root = self.frame_side_panel or self.window
        self.side_edit_url = root.findChild(QLineEdit, "lineEditProjectURL")
        self.side_edit_name = root.findChild(QLineEdit, "lineEditProjectName")
        self.side_lbl_permission = root.findChild(QLabel, "labelPermissionStatus")
        self.side_lbl_icon = root.findChild(QLabel, "lblIcon")
        self.side_edit_game = root.findChild(QLineEdit, "lineEditGame")
        self.side_edit_source = root.findChild(QLineEdit, "lineEditSourcePath")
        self.side_btn_browse_source = root.findChild(QPushButton, "btnBrowseSource")

        self._set_tool_icon(self.btn_side_close, "close-fill.svg", QSize(20, 20))
        self._set_tool_icon(self.btn_side_link, "external-link.svg", QSize(20, 20))

        if self.frame_side_panel:
            self.frame_side_panel.hide()

    def _connect_actions(self):
        self.btn_check_all = self.window.findChild(QPushButton, "btnCheckAll")
        self.btn_push_all = self.window.findChild(QPushButton, "btnPushAll")

        if self.btn_check_all:
            self.btn_check_all.clicked.connect(lambda: self.load_projects(auto_initialize=True))
        if self.btn_push_all:
            self.btn_push_all.clicked.connect(self.on_push_all_clicked)
        if self.btn_side_close:
            self.btn_side_close.clicked.connect(self.hide_side_panel)
        if self.btn_side_link:
            self.btn_side_link.clicked.connect(self.open_paratranz_link)
        if self.btn_side_delete_action:
            self.btn_side_delete_action.clicked.connect(self.on_side_delete_clicked)
        if self.side_btn_browse_source:
            self.side_btn_browse_source.clicked.connect(self.browse_source_side)
        if self.side_edit_source:
            self.side_edit_source.editingFinished.connect(self.save_side_panel_data)

    def _select_initial_page(self):
        if self.list_widget:
            self.list_widget.setCurrentRow(0)

    # ------------------------------------------------------------------
    # 共通ユーティリティ
    # ------------------------------------------------------------------

    @staticmethod
    def _is_valid_qobject(obj: Any) -> bool:
        try:
            return obj is not None and shiboken6.isValid(obj)
        except Exception:
            return False

    def _icon_path(self, filename: str) -> Path:
        return BASE_DIR / "assets" / "icons" / filename

    def _project_icon_path(self, project_id: Any) -> Path:
        data_dir = Path(sys.argv[0]).resolve().parent / "data"
        icon_path = data_dir / "logos" / f"project_{project_id}.png"
        if icon_path.exists():
            return icon_path
        return BASE_DIR / "assets" / "placeholder.png"

    def _set_tool_icon(self, button: Optional[QToolButton], filename: str, size: QSize):
        if not button:
            return

        icon_path = self._icon_path(filename)
        if icon_path.exists():
            button.setIcon(QIcon(str(icon_path)))
            button.setIconSize(size)
            button.setText("")

    @staticmethod
    def _format_updated_at(value: str) -> str:
        if not value:
            return "更新日不明"
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return dt.strftime("%Y-%m-%d %H:%M")
        except Exception:
            return value

    @staticmethod
    def _sync_summary_message(prefix: str, results: dict[str, list]) -> str:
        new_count = len(results.get("new", []))
        mod_count = len(results.get("modified", []))
        del_count = len(results.get("deleted", []))

        message = f"{prefix}\n\n"
        if new_count > 0:
            message += f"・新規追加: {new_count} 件\n"
        if mod_count > 0:
            message += f"・変更あり: {mod_count} 件\n"
        if del_count > 0:
            message += f"・削除対象: {del_count} 件\n"
        return message

    # ------------------------------------------------------------------
    # タスクトレイ・終了処理
    # ------------------------------------------------------------------

    def setup_tray_icon(self):
        self.tray_icon = QSystemTrayIcon(self.window)

        # トレイアイコンには icon.png を使用
        icon_path = BASE_DIR / "assets" / "icon.png"
        if icon_path.exists():
            self.tray_icon.setIcon(QIcon(str(icon_path)))

        self.tray_icon.setToolTip(APP_NAME)
        self.tray_icon.setContextMenu(self._create_tray_menu())
        self.tray_icon.activated.connect(self.on_tray_icon_activated)
        self.tray_icon.setVisible(ConfigManager.get("minimize_to_tray", False))

    def _create_tray_menu(self) -> QMenu:
        tray_menu = QMenu()

        show_action = tray_menu.addAction("表示")
        show_action.triggered.connect(self.restore_window)

        tray_menu.addSeparator()

        quit_action = tray_menu.addAction("終了")
        quit_action.triggered.connect(self.quit_app)

        return tray_menu

    def on_window_close(self, event):
        if ConfigManager.get("minimize_to_tray", False):
            event.ignore()
            self.window.hide()
            return

        event.accept()
        try:
            self.window.removeEventFilter(self)
        except Exception:
            pass
        self.quit_app()

    def on_tray_icon_activated(self, reason):
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            self.restore_window()

    def restore_window(self):
        self.window.show()
        self.window.setWindowState(self.window.windowState() & ~Qt.WindowMinimized | Qt.WindowActive)
        self.window.activateWindow()
        self.window.raise_()

    def quit_app(self):
        if hasattr(self, "monitor_timer"):
            self.monitor_timer.stop()
        if hasattr(self, "tray_icon"):
            self.tray_icon.hide()
        QApplication.instance().quit()

    # ------------------------------------------------------------------
    # 定期監視
    # ------------------------------------------------------------------

    def setup_timer(self):
        self.monitor_timer = QTimer(self)
        self.monitor_timer.timeout.connect(self.on_periodic_check)
        self.update_timer_settings()

    def update_timer_settings(self):
        self.monitor_timer.stop()

        if not ConfigManager.get("monitor_enabled", False):
            return

        interval_val = ConfigManager.get("monitor_interval", 30)
        unit_index = ConfigManager.get("monitor_unit_index", 1)
        if unit_index >= len(self.TIMER_MULTIPLIERS):
            return

        interval_ms = interval_val * self.TIMER_MULTIPLIERS[unit_index]
        self.monitor_timer.start(interval_ms)
        print(
            f"[{datetime.now().strftime('%H:%M:%S')}] "
            f"定期監視を開始しました (間隔: {interval_val} 単位インデックス: {unit_index})"
        )

    def on_periodic_check(self):
        print(f"[{datetime.now().strftime('%H:%M:%S')}] 定期監視実行中...")
        self.load_projects()

    def on_settings_saved(self):
        self.update_timer_settings()
        if hasattr(self, "tray_icon"):
            self.tray_icon.setVisible(ConfigManager.get("minimize_to_tray", True))
        
        # 翻訳の再適用
        apply_translation(QApplication.instance())

    # ------------------------------------------------------------------
    # プロジェクト一覧・同期一覧
    # ------------------------------------------------------------------

    def load_projects(self, auto_initialize: bool = False):
        if auto_initialize:
            print(f"\n[{datetime.now().strftime('%H:%M:%S')}] すべてをチェック中...")

        self._clear_project_views()

        projects = ProjectManager.load_projects()
        self.update_game_filters(projects)

        update_count = 0
        for project in projects:
            check_res = self._check_project_sync(project, auto_initialize)

            if SyncManager.has_changes(check_res):
                self.add_project_row(project)
                update_count += 1

            if self._project_matches_filter(project):
                self.add_project_card(project)

        if self.layout_project_cards:
            self.layout_project_cards.addStretch()

        self.update_sidebar_badge(update_count)

    def _clear_project_views(self):
        if self.table_sync:
            self.table_sync.setRowCount(0)

        if not self.layout_project_cards:
            return

        while self.layout_project_cards.count():
            item = self.layout_project_cards.takeAt(0)
            widget = item.widget()
            if widget and widget != self.card_template:
                widget.deleteLater()

    def _check_project_sync(self, project: dict, auto_initialize: bool) -> dict:
        project_name = project.get("project_name", "Unknown")
        if auto_initialize:
            print(f"  - {project_name} をチェック中...", end="", flush=True)

        check_res = SyncManager.check_sync(project)

        if auto_initialize and check_res.get("status") == "INITIALIZING":
            print(" [初期化中]", end="", flush=True)
            try:
                SyncManager.initialize_cache_from_paratranz(project.get("project_id"))
                check_res = SyncManager.check_sync(project)
            except Exception as e:
                print(f" [初期化失敗: {e}]", end="")

        if auto_initialize:
            print(" -> 変更あり" if SyncManager.has_changes(check_res) else " -> 変更なし")

        return check_res

    def _project_matches_filter(self, project: dict) -> bool:
        return not self.current_filter_game or project.get("game") == self.current_filter_game

    def update_sidebar_badge(self, count: int):
        widget = self.nav_widgets.get(1)
        if widget:
            widget.set_badge(count)

    def add_project_row(self, project: dict):
        if not self.table_sync:
            return

        row = self.table_sync.rowCount()
        self.table_sync.insertRow(row)

        self.table_sync.setCellWidget(row, 0, self._create_project_icon_label(project.get("project_id"), 32))
        self.table_sync.setItem(row, 1, QTableWidgetItem(project.get("project_name", "")))
        self.table_sync.setItem(row, 2, QTableWidgetItem(GameManager.get_game_display_name(project.get("game", ""))))

        btn_container, btn = self._create_action_button("更新")
        btn.clicked.connect(lambda: self.on_sync_clicked(project))
        self.table_sync.setCellWidget(row, 3, btn_container)
        self.table_sync.setRowHeight(row, 40)

    def add_project_card(self, project: dict):
        if not self.layout_project_cards:
            return

        card = QFrame()
        card.setObjectName("projectCard")
        card.setFrameShape(QFrame.StyledPanel)
        card.setFrameShadow(QFrame.Raised)
        card.setFixedHeight(150)
        card.setCursor(Qt.PointingHandCursor)
        card.setProperty("project_data", project)
        card.installEventFilter(self)

        layout_main = QHBoxLayout(card)
        layout_info = QVBoxLayout()

        lbl_title = QLabel(project.get("project_name", "名称未設定"))
        lbl_title.setObjectName("projectTitle")

        lbl_update = QLabel(f"最終更新: {self._format_updated_at(project.get('updated_at', ''))}")
        lbl_update.setObjectName("projectUpdate")

        lbl_desc = QLabel(project.get("description") or "説明はありません。")
        lbl_desc.setObjectName("projectDesc")
        lbl_desc.setWordWrap(True)
        lbl_desc.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)

        layout_info.addWidget(lbl_title)
        layout_info.addWidget(lbl_update)
        layout_info.addWidget(lbl_desc)
        layout_info.addLayout(self._create_card_bottom_row(project))

        icon_label = self._create_project_icon_label(project.get("project_id"), 120)

        for widget in (lbl_title, lbl_update, lbl_desc, icon_label):
            widget.setAttribute(Qt.WA_TransparentForMouseEvents)

        layout_main.addLayout(layout_info)
        layout_main.addWidget(icon_label)
        self.layout_project_cards.addWidget(card)

    def _create_card_bottom_row(self, project: dict) -> QHBoxLayout:
        row = QHBoxLayout()

        game_id = project.get("game", "")
        btn_tag = QToolButton()
        btn_tag.setObjectName("gameTagButton")
        btn_tag.setText(GameManager.get_game_display_name(game_id))
        btn_tag.clicked.connect(lambda: self.filter_projects(game_id))

        btn_delete = QToolButton()
        btn_delete.setObjectName("deleteButton")
        self._set_tool_icon(btn_delete, "trash-1.svg", QSize(24, 24))
        btn_delete.setToolTip("削除")
        btn_delete.clicked.connect(lambda: self.remove_project(project.get("project_id")))

        row.addWidget(btn_tag)
        row.addStretch()
        row.addWidget(btn_delete)
        return row

    def _create_project_icon_label(self, project_id: Any, size: int) -> QLabel:
        label = QLabel()
        label.setFixedSize(size, size)
        label.setAlignment(Qt.AlignCenter)

        icon_path = self._project_icon_path(project_id)
        if icon_path.exists():
            pixmap = QPixmap(str(icon_path))
            label.setPixmap(pixmap.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        else:
            label.setText("No Icon")

        return label

    def _create_action_button(self, text: str):
        container = QWidget()
        layout = QHBoxLayout(container)
        button = QPushButton(text)
        button.setFixedWidth(80)
        layout.addWidget(button)
        layout.setAlignment(Qt.AlignCenter)
        layout.setContentsMargins(0, 0, 0, 0)
        return container, button

    def remove_project(self, project_id: Any):
        reply = QMessageBox.question(
            self.window,
            "削除の確認",
            "このプロジェクトを削除してもよろしいですか？\n（設定ファイルからプロジェクトが除外されます）",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        projects = [p for p in ProjectManager.load_projects() if p.get("project_id") != project_id]
        ProjectManager.save_projects(projects)
        self.load_projects()

    # ------------------------------------------------------------------
    # ゲームフィルタ
    # ------------------------------------------------------------------

    def update_game_filters(self, projects: list[dict]):
        if not self.layout_game_filter:
            return

        from collections import Counter
        # ゲームごとの登録数をカウント
        game_counts = Counter(p.get("game") for p in projects if p.get("game"))
        # 登録数が多い順にソート（同じ場合は名前順）
        games = sorted(game_counts.keys(), key=lambda g: (-game_counts[g], g))
        
        # すでに生成済みのボタンのgame_idを取得して比較（順番も維持）
        existing_games = []
        for i in range(self.layout_game_filter.count()):
            widget = self.layout_game_filter.itemAt(i).widget()
            if widget and widget.property("game_id"):
                existing_games.append(widget.property("game_id"))
        
        if existing_games == games:
            # ゲーム一覧と並び順に変更がない場合は再生成しない
            self._update_game_filter_overflow()
            return

        self._remove_game_filter_buttons()
        for game_id in games:
            self._add_game_filter_button(game_id)

        self._update_game_filter_overflow()

    def _remove_game_filter_buttons(self):
        for i in reversed(range(self.layout_game_filter.count())):
            item = self.layout_game_filter.itemAt(i)
            widget = item.widget() if item else None
            if widget and widget != self.btn_filter_all and widget != getattr(self, "cb_game_filter", None):
                if isinstance(widget, QPushButton):
                    self.game_button_group.removeButton(widget)
                self.layout_game_filter.takeAt(i)
                widget.deleteLater()

    def _add_game_filter_button(self, game_id: str):
        button = QToolButton()
        button.setText(GameManager.get_game_display_name(game_id))
        button.setCheckable(True)
        button.setProperty("game_id", game_id)
        button.clicked.connect(lambda checked=False, g=game_id: self.filter_projects(g))
        self.game_button_group.addButton(button)

        self.layout_game_filter.addWidget(button)

        if game_id == self.current_filter_game:
            button.setChecked(True)

    def _update_game_filter_overflow(self):
        if not self.w_game_filter or not self.layout_game_filter or not self.cb_game_filter:
            return

        # スペーサー(40px)と余白を考慮して、ボタンがゆったり入る幅を計算
        available_width = self.w_game_filter.width() - 50
        
        self.cb_game_filter.setPlaceholderText("その他のゲーム...")
        self.cb_game_filter.clear()

        current_width = 0
        overflow_items = []
        spacing = self.layout_game_filter.spacing()
        
        # 1. 入り切るかどうかを計算
        for i in range(self.layout_game_filter.count()):
            item = self.layout_game_filter.itemAt(i)
            widget = item.widget()
            if not widget or widget == self.cb_game_filter:
                continue
            
            w = widget.sizeHint().width() + spacing
            
            # 「すべて」ボタン以外で、現在の利用可能幅を超える場合
            if i > 0 and current_width + w > available_width:
                widget.hide()
                game_id = widget.property("game_id")
                if game_id:
                    overflow_items.append((GameManager.get_game_display_name(game_id), game_id))
            else:
                widget.show()
                current_width += w
        
        # 2. オーバーフロー項目があれば名前順にソートしてコンボボックスを表示
        if overflow_items:
            # 名前（表示名）でソート
            overflow_items.sort(key=lambda x: x[0])
            for name, gid in overflow_items:
                self.cb_game_filter.addItem(name, gid)
            self.cb_game_filter.show()
        else:
            self.cb_game_filter.hide()
            
        self._sync_filter_selection()

    def _on_combo_filter_activated(self, index: int):
        game_id = self.cb_game_filter.itemData(index)
        if game_id:
            self.filter_projects(game_id)
        else:
            # プレースホルダ（インデックス-1など）が選ばれた場合
            self._sync_filter_buttons()

    def filter_projects(self, game_id: Optional[str]):
        self.current_filter_game = game_id
        self.load_projects()
        self._sync_filter_selection()

    def _sync_filter_selection(self):
        self._sync_filter_buttons()

    def _sync_filter_buttons(self):
        if not self.game_button_group:
            return

        self.game_button_group.setExclusive(False)
        found_in_buttons = False
        
        for button in self.game_button_group.buttons():
            button_game_id = button.property("game_id")
            
            # 選択中のゲームと一致するかチェック
            is_selected = (
                button_game_id == self.current_filter_game
                or (self.current_filter_game is None and button == self.btn_filter_all)
            )
            
            # ボタンが表示されている場合のみチェック状態を反映
            if button.isVisible():
                button.setChecked(is_selected)
                if is_selected:
                    found_in_buttons = True
            else:
                button.setChecked(False)

        self.game_button_group.setExclusive(True)

        # コンボボックスの同期
        if self.cb_game_filter:
            self.cb_game_filter.blockSignals(True)
            if self.current_filter_game and not found_in_buttons:
                idx = self.cb_game_filter.findData(self.current_filter_game)
                if idx >= 0:
                    self.cb_game_filter.setCurrentIndex(idx)
                else:
                    self.cb_game_filter.setCurrentIndex(-1)
            else:
                # 選択中のものがボタンとして表示されているか、何も選択されていない場合
                self.cb_game_filter.setCurrentIndex(-1)
            self.cb_game_filter.blockSignals(False)

    # ------------------------------------------------------------------
    # 同期実行
    # ------------------------------------------------------------------

    def on_sync_clicked(self, project: dict):
        project_name = project.get("project_name")
        project_id = project.get("project_id")
        check_res = SyncManager.check_sync(project)

        if "error" in check_res:
            QMessageBox.warning(self.window, "エラー", check_res["error"])
            return

        if check_res.get("status") == "INITIALIZING":
            self._confirm_initialize_cache(project_name, project_id)
            return

        results = check_res.get("results", {})
        if not SyncManager.has_changes(check_res):
            QMessageBox.information(self.window, "同期済み", "すべてのファイルが同期済みです。")
            return

        msg = self._sync_summary_message("同期が必要な項目が見つかりました：", results)
        msg += "\nこれらの変更を Paratranz に反映しますか？"

        reply = QMessageBox.question(
            self.window,
            "同期の実行確認",
            msg,
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            self._execute_single_sync(project, check_res)

    def _confirm_initialize_cache(self, project_name: str, project_id: Any):
        reply = QMessageBox.question(
            self.window,
            "初期化の確認",
            f"プロジェクト「{project_name}」の同期履歴がありません。\n"
            "Paratranzから現在のファイル状態を取得して初期化しますか？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes,
        )
        if reply != QMessageBox.Yes:
            return

        try:
            SyncManager.initialize_cache_from_paratranz(project_id)
            QMessageBox.information(self.window, "完了", "同期履歴の初期化が完了しました。もう一度更新ボタンを押してください。")
        except Exception as e:
            QMessageBox.critical(self.window, "エラー", f"初期化に失敗しました: {e}")

    def _execute_single_sync(self, project: dict, check_res: dict):
        project_name = project.get("project_name")
        print(f"\n[{datetime.now().strftime('%H:%M:%S')}] {project_name} を同期中...")

        success, message = SyncManager.execute_sync(project, check_res)
        if success:
            self._touch_project_updated_at(project)
            QMessageBox.information(self.window, "同期完了", f"「{project_name}」の同期が完了しました。\n{message}")
        else:
            QMessageBox.warning(self.window, "同期不完全", f"一部のファイルの同期に失敗しました。\n{message}")

        self.load_projects()

    def on_push_all_clicked(self):
        projects = ProjectManager.load_projects()
        changed_projects = []
        totals = {"new": 0, "modified": 0, "deleted": 0}

        print(f"\n[{datetime.now().strftime('%H:%M:%S')}] すべてを反映するための差分を確認中...")

        for project in projects:
            check_res = SyncManager.check_sync(project)
            if not SyncManager.has_changes(check_res):
                continue

            changed_projects.append((project, check_res))
            results = check_res.get("results", {})
            totals["new"] += len(results.get("new", []))
            totals["modified"] += len(results.get("modified", []))
            totals["deleted"] += len(results.get("deleted", []))

        if not changed_projects:
            QMessageBox.information(self.window, "通知", "反映が必要な変更はありません。")
            return

        if self._confirm_push_all(len(changed_projects), totals):
            self._execute_push_all(changed_projects)

    def _confirm_push_all(self, project_count: int, totals: dict[str, int]) -> bool:
        message = "以下の変更をすべてのプロジェクトに反映しますか？\n\n"
        message += f"対象プロジェクト: {project_count} 件\n"
        if totals["new"] > 0:
            message += f"・新規追加 合計: {totals['new']} 件\n"
        if totals["modified"] > 0:
            message += f"・変更あり 合計: {totals['modified']} 件\n"
        if totals["deleted"] > 0:
            message += f"・削除対象 合計: {totals['deleted']} 件\n"

        reply = QMessageBox.question(
            self.window,
            "一括反映の実行確認",
            message,
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        return reply == QMessageBox.Yes

    def _execute_push_all(self, changed_projects: list[tuple[dict, dict]]):
        print(f"[{datetime.now().strftime('%H:%M:%S')}] 一括反映を開始します...")

        for project, check_res in changed_projects:
            project_name = project.get("project_name", "Unknown")
            print(f"  - {project_name} を同期中...", end="", flush=True)
            success, message = SyncManager.execute_sync(project, check_res)
            if success:
                self._touch_project_updated_at(project)
                print(f" -> 完了 ({message})")
            else:
                print(f" -> 一部失敗 ({message})")

        QMessageBox.information(
            self.window,
            "一括反映完了",
            "すべてのプロジェクトの同期処理が終了しました。詳細はコンソールを確認してください。",
        )
        self.load_projects()

    @staticmethod
    def _touch_project_updated_at(project: dict):
        project["updated_at"] = datetime.now().isoformat()
        ProjectManager.add_project(project)

    # ------------------------------------------------------------------
    # ナビゲーション・イベント
    # ------------------------------------------------------------------

    def show_settings(self):
        settings = SettingsDialog(self.window)
        settings.exec()

    def show_add_project(self):
        dialog = AddProjectDialog(self.window)
        if dialog.exec():
            ProjectManager.add_project(dialog.get_data())
            self.load_projects()

    def on_nav_changed(self, index: int):
        if self.stacked_widget:
            self.stacked_widget.setCurrentIndex(index)

        for idx, widget in self.nav_widgets.items():
            widget.set_selected(idx == index)

        if index in (0, 1):
            self.last_nav_index = index

    def on_project_added_success(self):
        self.load_projects()
        if self.list_widget:
            self.list_widget.setCurrentRow(0)

    def eventFilter(self, watched, event):
        if not self._is_valid_qobject(watched) or not self._is_valid_qobject(getattr(self, "window", None)):
            return False

        try:
            if watched == self.window:
                if event.type() == QEvent.Close:
                    self.on_window_close(event)
                    return True
                elif event.type() == QEvent.Resize:
                    self._update_game_filter_overflow()

            if hasattr(self, "w_game_filter") and watched == self.w_game_filter:
                if event.type() == QEvent.Resize:
                    self._update_game_filter_overflow()

            if event.type() == QEvent.MouseButtonRelease:
                project_data = watched.property("project_data")
                if project_data:
                    self.show_side_panel(project_data)
                    return True
        except Exception:
            pass

        return super().eventFilter(watched, event)

    # ------------------------------------------------------------------
    # サイドパネル
    # ------------------------------------------------------------------

    def show_side_panel(self, project: dict):
        if not self.frame_side_panel:
            return

        if self.side_edit_source:
            self.side_edit_source.blockSignals(True)

        self.current_side_project_id = project.get("project_id")
        self._fill_side_panel_header(project)
        self._fill_side_panel_project_info(project)
        self._fill_side_panel_local_info(project)

        if self.side_edit_source:
            self.side_edit_source.blockSignals(False)

        self.frame_side_panel.show()

    def _fill_side_panel_header(self, project: dict):
        if self.lbl_side_title:
            self.lbl_side_title.setText(project.get("project_name", "名称未設定"))
        if self.side_lbl_icon:
            size = 64
            icon_path = self._project_icon_path(self.current_side_project_id)
            if icon_path.exists():
                pixmap = QPixmap(str(icon_path))
                self.side_lbl_icon.setPixmap(pixmap.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            else:
                self.side_lbl_icon.setText("No Icon")

    def _fill_side_panel_project_info(self, project: dict):
        if self.side_edit_url:
            self.side_edit_url.setText(str(project.get("project_id", "")))
        if self.side_edit_name:
            self.side_edit_name.setText(project.get("project_name", ""))
        if self.side_lbl_permission:
            self.side_lbl_permission.setText("確認済み" if project.get("project_id") else "未設定")

    def _fill_side_panel_local_info(self, project: dict):
        if self.side_edit_game:
            self.side_edit_game.setText(GameManager.get_game_display_name(project.get("game", "")))
        if self.side_edit_source:
            self.side_edit_source.setText(project.get("source_path", ""))

    def hide_side_panel(self):
        if self.frame_side_panel:
            self.frame_side_panel.hide()
        self.current_side_project_id = None

    def open_paratranz_link(self):
        if not self.current_side_project_id:
            return
        QDesktopServices.openUrl(QUrl(f"{DEFAULT_API_BASE_URL}/projects/{self.current_side_project_id}"))

    def on_side_delete_clicked(self):
        if not self.current_side_project_id:
            return
        self.remove_project(self.current_side_project_id)
        self.hide_side_panel()

    def browse_source_side(self):
        dir_path = QFileDialog.getExistingDirectory(self.window, "原文フォルダを選択")
        if dir_path:
            self.side_edit_source.setText(dir_path)
            self.save_side_panel_data()

    def fetch_project_info_side(self):
        QMessageBox.information(
            self.window,
            "情報",
            "情報の再取得機能は現在準備中です。\nプロジェクト追加画面のロジックを統合予定です。",
        )

    def save_side_panel_data(self):
        if not self.current_side_project_id:
            return

        projects = ProjectManager.load_projects()
        for project in projects:
            if project.get("project_id") == self.current_side_project_id:
                project["source_path"] = self.side_edit_source.text()
                break

        ProjectManager.save_projects(projects)
        self.load_projects()

    # ------------------------------------------------------------------
    # 表示
    # ------------------------------------------------------------------

    def show(self):
        self.window.show()


_translator = None

def apply_translation(app: QApplication):
    global _translator
    
    lang_code = ConfigManager.get("language", "")
    
    # 既存の翻訳を削除
    if _translator:
        app.removeTranslator(_translator)
    
    # System Defaultの場合の判定
    if not lang_code:
        from PySide6.QtCore import QLocale
        # システムのロケール名（例: 'ja_JP'）を取得
        lang_code = QLocale.system().name()
        
        # システム言語のファイルが存在しない場合は en_US をデフォルトにする
        loc_dir = Path(sys.argv[0]).resolve().parent / "localization"
        if not (loc_dir / f"{lang_code}.qm").exists():
            lang_code = "en_US"

    _translator = QTranslator()
    loc_dir = Path(sys.argv[0]).resolve().parent / "localization"
    qm_path = loc_dir / f"{lang_code}.qm"
    
    if qm_path.exists():
        if _translator.load(str(qm_path)):
            app.installTranslator(_translator)
            print(f"[{datetime.now().strftime('%H:%M:%S')}] 翻訳を適用しました: {lang_code}")
        else:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] 翻訳のロードに失敗しました: {lang_code}")
    else:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] 翻訳ファイルが見つかりません: {qm_path}")


def main():
    # Windowsのタスクバーアイコンを正しく表示させるための設定
    try:
        app_id = "ikumy.paratranz_checker.v1"
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(app_id)
    except Exception:
        pass

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    # 翻訳の適用
    apply_translation(app)

    # アプリ全体にアイコンを設定
    icon_path = BASE_DIR / "assets" / "icon.png"
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))

    main_window = MainWindow()
    main_window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
