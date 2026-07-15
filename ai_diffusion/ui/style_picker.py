from __future__ import annotations

from PyQt5.QtCore import QEvent, Qt, pyqtSignal
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
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..backend.client import filter_supported_styles, resolve_arch
from ..backend.resources import Arch
from ..localization import translate as _
from ..model.connection import ConnectionState
from ..model.root import root
from ..settings import settings
from ..style import Style, Styles, sort_recent_styles
from . import theme

_ARCH_ANY = "__any__"

# Checkpoint families that share an Arch (e.g. Pony/Illustrious are both
# technically SDXL-derived) but that users think of as distinct categories.
# Detected heuristically from style name / checkpoint filename, same approach
# as the LoRA browser's base_model mapping.
_FAMILY_HINTS = ["pony", "illustrious"]


def _family_label(style: Style, arch: Arch) -> str:
    haystack = (style.name + " " + " ".join(style.checkpoints)).lower()
    for hint in _FAMILY_HINTS:
        if hint in haystack:
            return hint.capitalize()
    return arch.name


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

        self.setWindowTitle(_("Select Style"))
        self.setMinimumSize(420, 480)
        self.resize(480, 600)
        self.setModal(False)
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.Window)

        self._search = QLineEdit(self)
        self._search.setPlaceholderText(_("Search styles…"))
        self._search.setClearButtonEnabled(True)
        self._search.textChanged.connect(self._apply_filter)

        arch_label = QLabel(_("Base Model:"), self)
        self._arch_combo = QComboBox(self)
        self._arch_combo.addItem(_("Any"), _ARCH_ANY)
        self._arch_combo.currentIndexChanged.connect(self._apply_filter)

        self._favorites_check = QCheckBox(_("Favorites"), self)
        self._favorites_check.setIcon(QIcon(_star_pixmap))
        self._favorites_check.toggled.connect(self._set_favorites_only)

        row1 = QHBoxLayout()
        row1.addWidget(self._search, 1)

        row2 = QHBoxLayout()
        row2.addWidget(arch_label)
        row2.addWidget(self._arch_combo, 1)
        row2.addWidget(self._favorites_check)

        self._list = QListWidget(self)
        self._list.itemActivated.connect(self._activate)
        self._list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._list.customContextMenuRequested.connect(self._show_context_menu)
        self._list.installEventFilter(self)

        hint = QLabel(_("Double-click to select. Right-click or F to toggle favorite."), self)
        hint.setStyleSheet(f"color: {theme.grey}; font-style: italic;")

        close_btn = QPushButton(_("Close"), self)
        close_btn.clicked.connect(self.close)
        bottom = QHBoxLayout()
        bottom.addStretch(1)
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

        families = sorted({_family_label(s, resolve_arch(s, client)) for s in self._styles})
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
        for style in self._styles:
            arch = resolve_arch(style, client)
            if family_filter and _family_label(style, arch) != family_filter:
                continue
            is_fav = self._is_favorite(style)
            if self._favorites_only and not is_fav:
                continue
            haystack = (style.name + " " + " ".join(style.checkpoints)).lower()
            if search and search not in haystack:
                continue

            is_recent = style.filename in self._recent
            wanted_section = "favorites" if is_fav else ("recent" if is_recent else "all")
            if wanted_section != section:
                section = wanted_section
                label = {
                    "favorites": _("Favorites"),
                    "recent": _("Recently Used"),
                    "all": _("All Styles"),
                }[section]
                header = QListWidgetItem(label)
                header.setFlags(Qt.ItemFlag.NoItemFlags)
                self._list.addItem(header)

            icon = theme.checkpoint_icon(arch, client=client)
            if is_fav:
                icon = _favorite_icon(icon)
            item = QListWidgetItem(icon, style.name)
            item.setData(Qt.ItemDataRole.UserRole, style.filename)
            if style == self._current:
                item.setSelected(True)
            self._list.addItem(item)

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

    def _toggle_selected_favorite(self):
        if style := self._selected_style():
            self._toggle_favorite(style)

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
        menu.exec(self._list.mapToGlobal(pos))

    def eventFilter(self, obj, event):
        if obj is self._list and event.type() == QEvent.Type.ShortcutOverride:
            assert isinstance(event, QKeyEvent)
            if event.key() == Qt.Key.Key_F:
                self._toggle_selected_favorite()
                event.accept()
                return True
        return super().eventFilter(obj, event)
