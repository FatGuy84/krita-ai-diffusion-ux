from __future__ import annotations

from krita import Krita
from PyQt5.QtCore import QUrl, Qt, pyqtSignal
from PyQt5.QtGui import QDesktopServices
from PyQt5.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ..localization import translate as _
from ..model.root import root
from ..wildcards import WildcardLibrary
from . import theme

_POS_END = "end"
_POS_START = "start"
_POS_CURSOR = "cursor"
_MODE_NORMAL = "normal"
_MODE_RANDOM = "random"
_MODE_SEQUENTIAL = "sequential"


class WildcardPickerDialog(QDialog):
    """Browse file-based wildcards (<user data>/wildcards/*.txt, one option per line,
    __name__ or __folder/name__ in the prompt) and insert a reference tag."""

    wildcard_selected = pyqtSignal(str)  # name

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._library = WildcardLibrary.instance()

        self.setWindowTitle(_("Wildcards"))
        self.setMinimumSize(420, 480)
        self.resize(480, 560)
        self.setModal(False)
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.Window)

        self._search = QLineEdit(self)
        self._search.setPlaceholderText(_("Search wildcards…"))
        self._search.setClearButtonEnabled(True)
        self._search.textChanged.connect(self._apply_filter)

        self._reload_btn = QToolButton(self)
        self._reload_btn.setIcon(theme.icon("reset"))
        self._reload_btn.setToolTip(_("Rescan the wildcards folder for new/changed files"))
        self._reload_btn.clicked.connect(self._reload)

        self._folder_btn = QToolButton(self)
        self._folder_btn.setIcon(Krita.instance().icon("document-open"))
        self._folder_btn.setToolTip(_("Open the wildcards folder"))
        self._folder_btn.clicked.connect(self._open_folder)

        row1 = QHBoxLayout()
        row1.addWidget(self._search, 1)
        row1.addWidget(self._reload_btn)
        row1.addWidget(self._folder_btn)

        self._list = QListWidget(self)
        self._list.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        self._list.itemSelectionChanged.connect(self._on_selection_changed)
        self._list.itemDoubleClicked.connect(lambda _item: self._add_to_prompt())

        self._hint = QLabel(self)
        self._hint.setWordWrap(True)
        self._hint.setStyleSheet(f"color: {theme.grey}; font-style: italic;")

        mode_label = QLabel(_("Mode:"), self)
        self._mode_combo = QComboBox(self)
        self._mode_combo.addItem(_("Normal __name__"), _MODE_NORMAL)
        self._mode_combo.addItem(_("Random {a|b}"), _MODE_RANDOM)
        self._mode_combo.addItem(_("Sequential [[a|b]]"), _MODE_SEQUENTIAL)
        self._mode_combo.setToolTip(
            _(
                "Normal: live reference to the file, picks one line at random per image."
                " Random/Sequential: expands the file's lines directly into the prompt as a"
                " wildcard group (a frozen snapshot, not a live reference) - Sequential cycles"
                " through every line across the batch instead of picking randomly."
            )
        )

        position_label = QLabel(_("Insert:"), self)
        self._position_combo = QComboBox(self)
        self._position_combo.addItem(_("at End"), _POS_END)
        self._position_combo.addItem(_("at Start"), _POS_START)
        self._position_combo.addItem(_("at Cursor"), _POS_CURSOR)

        self._selected_label = QLabel(_("No wildcard selected"), self)
        self._selected_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        self._add_btn = QPushButton(_("Add to Prompt"), self)
        self._add_btn.setEnabled(False)
        self._add_btn.clicked.connect(self._add_to_prompt)

        close_btn = QPushButton(_("Close"), self)
        close_btn.clicked.connect(self.close)

        bottom = QHBoxLayout()
        bottom.addWidget(self._selected_label, 1)
        bottom.addWidget(mode_label)
        bottom.addWidget(self._mode_combo)
        bottom.addWidget(position_label)
        bottom.addWidget(self._position_combo)
        bottom.addWidget(self._add_btn)
        bottom.addWidget(close_btn)

        layout = QVBoxLayout()
        layout.addLayout(row1)
        layout.addWidget(self._list, 1)
        layout.addWidget(self._hint)
        layout.addLayout(bottom)
        self.setLayout(layout)

        self._reload()

    # ── data ──

    def _reload(self):
        self._library.reload()
        self._apply_filter()

    def _apply_filter(self):
        search = self._search.text().strip().lower()
        self._list.clear()
        names = self._library.names()
        for name in names:
            if search and search not in name:
                continue
            options = self._library.get(name) or []
            item = QListWidgetItem(f"{name}  ({len(options)})")
            item.setData(Qt.ItemDataRole.UserRole, name)
            preview = "\n".join(options[:8])
            more = f"\n… +{len(options) - 8} more" if len(options) > 8 else ""
            item.setToolTip(f"__{name}__\n\n{preview}{more}")
            self._list.addItem(item)

        if not names:
            self._hint.setText(
                _("No wildcard files found. Put .txt files (one option per line) in:")
                + f"\n{self._library.folder}"
            )
        else:
            self._hint.setText(f"{self._list.count()} / {len(names)} " + _("wildcards"))

    def _open_folder(self):
        self._library.folder.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._library.folder)))

    # ── selection / insertion ──

    def _selected_name(self) -> str | None:
        items = self._list.selectedItems()
        return items[0].data(Qt.ItemDataRole.UserRole) if items else None

    def _on_selection_changed(self):
        name = self._selected_name()
        self._add_btn.setEnabled(name is not None)
        self._selected_label.setText(f"__{name}__" if name else _("No wildcard selected"))

    def _build_tag(self, name: str) -> str:
        mode = self._mode_combo.currentData()
        if mode == _MODE_NORMAL:
            return f"__{name}__"
        options = self._library.get(name) or []
        joined = "|\n".join(options)
        if mode == _MODE_SEQUENTIAL:
            return f"[[\n{joined}\n]]"
        return f"{{\n{joined}\n}}"

    def _add_to_prompt(self):
        name = self._selected_name()
        model = root.active_model
        if name is None or model is None:
            return
        tag = self._build_tag(name)
        self.wildcard_selected.emit(name)

        position = self._position_combo.currentData()
        if position == _POS_CURSOR and self._insert_at_cursor(tag):
            return

        region = model.regions.active_or_root
        current = region.positive
        if position == _POS_START:
            region.positive = tag + "\n" + current.lstrip("\n")
        else:
            region.positive = current.rstrip("\n") + "\n" + tag

    def _insert_at_cursor(self, text: str) -> bool:
        widget = getattr(self.parent(), "positive", None)
        if widget is None or not hasattr(widget, "textCursor"):
            return False
        cursor = widget.textCursor()
        cursor.insertText(text)
        widget.setTextCursor(cursor)
        return True
