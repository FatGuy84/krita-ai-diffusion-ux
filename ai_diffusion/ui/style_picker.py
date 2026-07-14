from __future__ import annotations

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..backend.client import filter_supported_styles, resolve_arch
from ..localization import translate as _
from ..model.connection import ConnectionState
from ..model.root import root
from ..settings import settings
from ..style import Style, Styles, sort_recent_styles
from . import theme

_ARCH_ANY = "__any__"


class StylePickerDialog(QDialog):
    style_selected = pyqtSignal(Style)

    def __init__(self, current: Style, parent: QWidget | None = None):
        super().__init__(parent)
        self._current = current
        self._styles: list[Style] = []
        self._recent: set[str] = set()

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

        row1 = QHBoxLayout()
        row1.addWidget(self._search, 1)

        row2 = QHBoxLayout()
        row2.addWidget(arch_label)
        row2.addWidget(self._arch_combo, 1)

        self._list = QListWidget(self)
        self._list.itemActivated.connect(self._activate)

        close_btn = QPushButton(_("Close"), self)
        close_btn.clicked.connect(self.close)
        bottom = QHBoxLayout()
        bottom.addStretch(1)
        bottom.addWidget(close_btn)

        layout = QVBoxLayout()
        layout.addLayout(row1)
        layout.addLayout(row2)
        layout.addWidget(self._list, 1)
        layout.addLayout(bottom)
        self.setLayout(layout)

        Styles.list().changed.connect(self._reload)
        self._reload()

    def _client(self):
        if root.connection.state is ConnectionState.connected:
            return root.connection.client_if_connected
        return None

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

        archs = sorted({resolve_arch(s, client).name for s in self._styles}, key=str)
        current_arch = self._arch_combo.currentData()
        self._arch_combo.blockSignals(True)
        self._arch_combo.clear()
        self._arch_combo.addItem(_("Any"), _ARCH_ANY)
        for arch in archs:
            self._arch_combo.addItem(arch, arch)
        idx = self._arch_combo.findData(current_arch)
        self._arch_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self._arch_combo.blockSignals(False)

        self._apply_filter()

    def _apply_filter(self):
        client = self._client()
        search = self._search.text().strip().lower()
        arch = self._arch_combo.currentData()
        arch = "" if arch in (None, _ARCH_ANY) else arch

        self._list.clear()
        shown_recent = False
        for style in self._styles:
            if arch and resolve_arch(style, client).name != arch:
                continue
            haystack = (style.name + " " + " ".join(style.checkpoints)).lower()
            if search and search not in haystack:
                continue

            is_recent = style.filename in self._recent
            if is_recent and not shown_recent:
                header = QListWidgetItem(_("Recently Used"))
                header.setFlags(Qt.ItemFlag.NoItemFlags)
                self._list.addItem(header)
                shown_recent = True
            elif not is_recent and shown_recent:
                header = QListWidgetItem(_("All Styles"))
                header.setFlags(Qt.ItemFlag.NoItemFlags)
                self._list.addItem(header)
                shown_recent = False

            icon = theme.checkpoint_icon(resolve_arch(style, client), client=client)
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
