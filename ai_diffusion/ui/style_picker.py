from __future__ import annotations

import asyncio
from pathlib import Path

from PyQt5.QtCore import QEvent, QSize, Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QIcon, QKeyEvent, QPainter, QPixmap
from PyQt5.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPushButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .. import eventloop
from ..backend.client import filter_supported_styles, resolve_arch
from ..backend.lora_manager import fetch_checkpoints_pages, fetch_preview_bytes
from ..localization import translate as _
from ..model.connection import ConnectionState
from ..model.root import root
from ..settings import settings
from ..style import Style, Styles, sort_recent_styles
from . import theme
from .lora_picker import _extract_video_frame, _ffmpeg_path, _is_video_url

_ARCH_ANY = "__any__"
_VIEW_LIST = "list"
_VIEW_GRID = "grid"


def _tint_pixmap(pixmap: QPixmap, color) -> QPixmap:
    tinted = QPixmap(pixmap.size())
    tinted.fill(Qt.GlobalColor.transparent)
    painter = QPainter(tinted)
    painter.drawPixmap(0, 0, pixmap)
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
    painter.fillRect(tinted.rect(), color)
    painter.end()
    return tinted


_star_pixmap = _tint_pixmap(QPixmap(str(theme.icon_path / "star.png")), Qt.GlobalColor.white)


def _favorite_icon(base: QIcon) -> QIcon:
    """Overlay a white star badge on the bottom-right corner of a checkpoint icon."""
    size = 16
    pixmap = base.pixmap(size, size)
    if pixmap.isNull():
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.GlobalColor.transparent)
    badge_size = max(7, size // 2)
    star = _star_pixmap.scaled(
        badge_size, badge_size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
    )
    painter = QPainter(pixmap)
    painter.drawPixmap(pixmap.width() - badge_size, pixmap.height() - badge_size, star)
    painter.end()
    return QIcon(pixmap)


class StylePickerDialog(QDialog):
    style_selected = pyqtSignal(Style)

    def __init__(self, current: Style, parent: QWidget | None = None):
        super().__init__(parent)
        self._current = current
        self._styles: list[Style] = []
        self._recent: set[str] = set()
        self._favorites_only = False
        self._ckpt_previews: dict[str, str] = {}  # checkpoint stem -> preview url
        self._preview_cache: dict[str, QPixmap] = {}  # stem -> pixmap
        self._pending_previews: set[str] = set()
        self._view = _VIEW_LIST

        self.setWindowTitle(_("Select Style"))
        self.setMinimumSize(420, 480)
        self.resize(480, 600)
        self.setModal(False)
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.Window)

        self._search = QLineEdit(self)
        self._search.setPlaceholderText(_("Search styles…"))
        self._search.setClearButtonEnabled(True)
        self._search.textChanged.connect(self._apply_filter)

        self._refresh_btn = QToolButton(self)
        self._refresh_btn.setIcon(theme.icon("reset"))
        self._refresh_btn.setToolTip(_("Reload styles and checkpoint thumbnails"))
        self._refresh_btn.clicked.connect(self._refresh)

        arch_label = QLabel(_("Base Model:"), self)
        self._arch_combo = QComboBox(self)
        self._arch_combo.addItem(_("Any"), _ARCH_ANY)
        self._arch_combo.currentIndexChanged.connect(self._apply_filter)

        self._favorites_check = QCheckBox(_("Favorites"), self)
        self._favorites_check.setIcon(QIcon(_star_pixmap))
        self._favorites_check.toggled.connect(self._set_favorites_only)

        self._view_combo = QComboBox(self)
        self._view_combo.addItem(_("List"), _VIEW_LIST)
        self._view_combo.addItem(_("Grid"), _VIEW_GRID)
        self._view_combo.currentIndexChanged.connect(self._set_view_mode)

        row1 = QHBoxLayout()
        row1.addWidget(self._search, 1)
        row1.addWidget(self._refresh_btn)

        row2 = QHBoxLayout()
        row2.addWidget(arch_label)
        row2.addWidget(self._arch_combo, 1)
        row2.addWidget(self._favorites_check)
        row2.addWidget(self._view_combo)

        self._list = QListWidget(self)
        self._list.setIconSize(QSize(48, 48))  # room for real checkpoint thumbnails
        self._list.itemActivated.connect(self._activate)
        self._list.itemSelectionChanged.connect(self._update_actions)
        self._list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._list.customContextMenuRequested.connect(self._show_context_menu)
        self._list.installEventFilter(self)

        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(120)
        self._preview_timer.timeout.connect(self._load_visible_previews)
        if scrollbar := self._list.verticalScrollBar():
            scrollbar.valueChanged.connect(self._schedule_visible_previews)

        hint = QLabel(_("Double-click to select. Right-click or F to toggle favorite."), self)
        hint.setStyleSheet(f"color: {theme.grey}; font-style: italic;")

        self._create_from_ckpt_btn = QPushButton(_("Create from Checkpoints…"), self)
        self._create_from_ckpt_btn.setToolTip(
            _("Bulk-create styles from Lora Manager checkpoints, using a template style")
        )
        self._create_from_ckpt_btn.clicked.connect(self._open_checkpoint_picker)
        self._checkpoint_dialog = None

        self._favorite_btn = QPushButton(_("Favorite"), self)
        self._favorite_btn.setEnabled(False)
        self._favorite_btn.clicked.connect(self._toggle_selected_favorite)

        self._delete_btn = QPushButton(_("Delete"), self)
        self._delete_btn.setEnabled(False)
        self._delete_btn.clicked.connect(self._delete_selected)

        close_btn = QPushButton(_("Close"), self)
        close_btn.clicked.connect(self.close)
        bottom = QHBoxLayout()
        bottom.addWidget(self._create_from_ckpt_btn)
        bottom.addStretch(1)
        bottom.addWidget(self._favorite_btn)
        bottom.addWidget(self._delete_btn)
        bottom.addWidget(close_btn)

        layout = QVBoxLayout()
        layout.addLayout(row1)
        layout.addLayout(row2)
        layout.addWidget(self._list, 1)
        layout.addWidget(hint)
        layout.addLayout(bottom)
        self.setLayout(layout)

        Styles.list().changed.connect(self._reload)
        settings.changed.connect(self._on_settings_changed)
        self._reload()
        self._load_checkpoint_previews()

    def _set_view_mode(self):
        self._view = self._view_combo.currentData()
        if self._view == _VIEW_GRID:
            self._list.setViewMode(QListWidget.ViewMode.IconMode)
            self._list.setFlow(QListWidget.Flow.LeftToRight)
            self._list.setWrapping(True)
            self._list.setResizeMode(QListWidget.ResizeMode.Adjust)
            self._list.setMovement(QListWidget.Movement.Static)
            self._list.setWordWrap(True)
            self._list.setSpacing(4)
            self._list.setIconSize(QSize(128, 128))
        else:
            self._list.setViewMode(QListWidget.ViewMode.ListMode)
            self._list.setFlow(QListWidget.Flow.TopToBottom)
            self._list.setWrapping(False)
            self._list.setResizeMode(QListWidget.ResizeMode.Fixed)
            self._list.setMovement(QListWidget.Movement.Static)
            self._list.setWordWrap(False)
            self._list.setSpacing(0)
            self._list.setIconSize(QSize(48, 48))
        self._apply_filter()

    # ── checkpoint thumbnails from Lora Manager ──

    def _refresh(self):
        self._ckpt_previews.clear()
        self._preview_cache.clear()
        self._pending_previews.clear()
        self._reload()
        self._load_checkpoint_previews()

    def _style_stem(self, style: Style) -> str:
        return Path(style.checkpoints[0]).stem if style.checkpoints else ""

    def _load_checkpoint_previews(self):
        client = self._client()
        if client is not None:
            eventloop.run(self._fetch_checkpoint_previews(client))

    async def _fetch_checkpoint_previews(self, client):
        try:
            async for batch in fetch_checkpoints_pages(client._requests, client.url):
                for c in batch:
                    if c.preview_url:
                        self._ckpt_previews[c.name] = c.preview_url
        finally:
            self._schedule_visible_previews()

    def _schedule_visible_previews(self):
        self._preview_timer.start()

    def _load_visible_previews(self):
        viewport_rect = self._list.viewport().rect()
        if self._client() is None:
            return
        for i in range(self._list.count()):
            item = self._list.item(i)
            if item is None or item.data(Qt.ItemDataRole.UserRole) is None:
                continue
            if not self._list.visualItemRect(item).intersects(viewport_rect):
                continue
            stem = item.data(Qt.ItemDataRole.UserRole + 1)
            if not stem or stem in self._preview_cache or stem in self._pending_previews:
                continue
            url = self._ckpt_previews.get(stem)
            if not url or (_is_video_url(url) and _ffmpeg_path is None):
                continue
            self._pending_previews.add(stem)
            eventloop.run(self._load_preview(stem, url))

    async def _load_preview(self, stem: str, url: str):
        client = self._client()
        if client is None:
            return
        data = await fetch_preview_bytes(client._requests, url)
        if data and _is_video_url(url):
            loop = asyncio.get_running_loop()
            data = await loop.run_in_executor(None, _extract_video_frame, data)
        if not data:
            return
        pixmap = QPixmap()
        pixmap.loadFromData(data)
        if pixmap.isNull():
            return
        self._preview_cache[stem] = pixmap
        for i in range(self._list.count()):  # apply to every item using this checkpoint
            item = self._list.item(i)
            if item is not None and item.data(Qt.ItemDataRole.UserRole + 1) == stem:
                item.setIcon(QIcon(pixmap))

    def _open_checkpoint_picker(self):
        from .checkpoint_picker import CheckpointPickerDialog

        if self._checkpoint_dialog is None:
            self._checkpoint_dialog = CheckpointPickerDialog(parent=self)
        self._checkpoint_dialog.show()
        self._checkpoint_dialog.raise_()
        self._checkpoint_dialog.activateWindow()

    def _client(self):
        if root.connection.state is ConnectionState.connected:
            return root.connection.client_if_connected
        return None

    def _on_settings_changed(self, name: str, value: object):
        if name == "favorite_styles":
            self._apply_filter()

    def _set_favorites_only(self, value: bool):
        self._favorites_only = value
        self._apply_filter()

    def _is_favorite(self, style: Style) -> bool:
        return style.filename in settings.favorite_styles

    def _toggle_favorite(self, style: Style):
        favorites = list(settings.favorite_styles)
        if style.filename in favorites:
            favorites.remove(style.filename)
        else:
            favorites.append(style.filename)
        settings.favorite_styles = favorites
        settings.save()

    def _reload(self):
        client = self._client()
        filtered = filter_supported_styles(Styles.list().filtered(), client)
        recent, remaining = sort_recent_styles(
            filtered, settings.recent_styles, settings.recent_styles_count
        )
        if self._current not in recent and self._current not in remaining:
            remaining.insert(0, self._current)
        self._recent = {s.filename for s in recent}
        self._styles = recent + remaining

        families = sorted({s.effective_family(resolve_arch(s, client)) for s in self._styles})
        current_arch = self._arch_combo.currentData()
        self._arch_combo.blockSignals(True)
        self._arch_combo.clear()
        self._arch_combo.addItem(_("Any"), _ARCH_ANY)
        for family in families:
            self._arch_combo.addItem(family, family)
        idx = self._arch_combo.findData(current_arch)
        self._arch_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self._arch_combo.blockSignals(False)

        self._apply_filter()

    def _apply_filter(self):
        client = self._client()
        search = self._search.text().strip().lower()
        family_filter = self._arch_combo.currentData()
        family_filter = "" if family_filter in (None, _ARCH_ANY) else family_filter

        self._list.clear()
        section = None  # None | "favorites" | "recent" | "all"

        # group into contiguous sections (favorites > recent > all) so each
        # header appears exactly once - favorites can be scattered through the
        # recent+remaining ordering otherwise
        def bucket(style: Style) -> int:
            if self._is_favorite(style):
                return 0
            if style.filename in self._recent:
                return 1
            return 2

        for style in sorted(self._styles, key=bucket):
            arch = resolve_arch(style, client)
            if family_filter and style.effective_family(arch) != family_filter:
                continue
            is_fav = self._is_favorite(style)
            if self._favorites_only and not is_fav:
                continue
            haystack = (style.name + " " + " ".join(style.checkpoints)).lower()
            if search and search not in haystack:
                continue

            is_recent = style.filename in self._recent
            wanted_section = "favorites" if is_fav else ("recent" if is_recent else "all")
            # section headers only make sense in the list view (a full-width row);
            # the grid view shows a flat grid in the same favorites>recent>all order
            if self._view == _VIEW_LIST and wanted_section != section:
                section = wanted_section
                label = {
                    "favorites": _("Favorites"),
                    "recent": _("Recently Used"),
                    "all": _("All Styles"),
                }[section]
                header = QListWidgetItem(label)
                header.setFlags(Qt.ItemFlag.NoItemFlags)
                self._list.addItem(header)

            stem = self._style_stem(style)
            if stem in self._preview_cache:  # real checkpoint thumbnail if we have it
                icon = QIcon(self._preview_cache[stem])
            else:
                icon = theme.checkpoint_icon(arch, client=client)
                if is_fav:
                    icon = _favorite_icon(icon)
            item = QListWidgetItem(icon, style.name)
            item.setData(Qt.ItemDataRole.UserRole, style.filename)
            item.setData(Qt.ItemDataRole.UserRole + 1, stem)
            if self._view == _VIEW_GRID:
                item.setSizeHint(QSize(128 + 16, 128 + 40))
                item.setTextAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
            if style == self._current:
                item.setSelected(True)
            self._list.addItem(item)

        self._schedule_visible_previews()

    def _activate(self, item: QListWidgetItem):
        filename = item.data(Qt.ItemDataRole.UserRole)
        if filename is None:
            return
        if style := Styles.list().find(filename):
            self._current = style
            self.style_selected.emit(style)
            self.close()

    def _selected_style(self) -> Style | None:
        items = self._list.selectedItems()
        if not items:
            return None
        filename = items[0].data(Qt.ItemDataRole.UserRole)
        return Styles.list().find(filename) if filename else None

    def _is_builtin(self, style: Style) -> bool:
        return style.filename.startswith("built-in/")

    def _update_actions(self):
        style = self._selected_style()
        self._favorite_btn.setEnabled(style is not None)
        self._delete_btn.setEnabled(style is not None and not self._is_builtin(style))
        if style is not None:
            self._favorite_btn.setText(
                _("Remove Favorite") if self._is_favorite(style) else _("Add Favorite")
            )
        else:
            self._favorite_btn.setText(_("Favorite"))

    def _toggle_selected_favorite(self):
        if style := self._selected_style():
            self._toggle_favorite(style)
            self._update_actions()

    def _delete_selected(self):
        self._delete_style(self._selected_style())

    def _delete_style(self, style: Style | None):
        if style is None or self._is_builtin(style):
            return
        confirm = QMessageBox.question(
            self,
            _("Delete Style"),
            _("Delete the style '{name}'? This removes its file and cannot be undone.").format(
                name=style.name
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
        )
        if confirm == QMessageBox.StandardButton.Yes:
            Styles.list().delete(style)  # _reload runs via the changed signal

    def _show_context_menu(self, pos):
        item = self._list.itemAt(pos)
        if item is None or item.data(Qt.ItemDataRole.UserRole) is None:
            return
        filename = item.data(Qt.ItemDataRole.UserRole)
        style = Styles.list().find(filename)
        if style is None:
            return
        menu = QMenu(self)
        label = _("Remove from Favorites") if self._is_favorite(style) else _("Add to Favorites")
        menu.addAction(label + "\tF", lambda: self._toggle_favorite(style))
        if not self._is_builtin(style):
            menu.addSeparator()
            menu.addAction(_("Delete Style"), lambda: self._delete_style(style))
        menu.exec(self._list.mapToGlobal(pos))

    def eventFilter(self, obj, event):
        if obj is self._list and event.type() == QEvent.Type.ShortcutOverride:
            assert isinstance(event, QKeyEvent)
            if event.key() == Qt.Key.Key_F:
                self._toggle_selected_favorite()
                event.accept()
                return True
        return super().eventFilter(obj, event)
