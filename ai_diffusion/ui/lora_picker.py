from __future__ import annotations

from typing import TYPE_CHECKING

from PyQt5.QtCore import QSize, Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QIcon, QPixmap
from PyQt5.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .. import eventloop
from ..backend.lora_manager import LoraInfo, arch_for_base_model, fetch_loras, fetch_preview_bytes
from ..localization import translate as _
from ..model.root import root
from ..util import client_logger as log
from . import theme

if TYPE_CHECKING:
    pass

_PREVIEW_SIZE = 96
_TAG_ALL = "__all__"
_KNOWN_TAGS = ["character", "style", "concept", "clothing", "pose", "background", "object"]
_ARCH_ANY = "__any__"
_KNOWN_ARCHES = [
    "sd15", "sdxl", "illu", "sd3", "flux", "flux_k",
    "chroma", "qwen", "anima", "zimage", "ernie", "krea2",
]


class LoraPickerDialog(QDialog):
    lora_selected = pyqtSignal(str, float)  # name, strength

    def __init__(self, current_arch: str, parent: QWidget | None = None):
        super().__init__(parent)
        self._current_arch = current_arch
        self._all_loras: list[LoraInfo] = []
        self._filtered: list[LoraInfo] = []
        self._active_tag = _TAG_ALL
        self._preview_cache: dict[str, QPixmap] = {}
        self._pending_previews: set[str] = set()

        self.setWindowTitle(_("LoRA Browser"))
        self.setMinimumSize(640, 480)
        self.resize(800, 560)

        # ── top bar ──
        self._search = QLineEdit(self)
        self._search.setPlaceholderText(_("Search LoRAs…"))
        self._search.textChanged.connect(self._apply_filter)

        arch_label = QLabel(_("Arch:"), self)
        self._arch_combo = QComboBox(self)
        self._arch_combo.addItem(_("Any"), _ARCH_ANY)
        for arch in _KNOWN_ARCHES:
            self._arch_combo.addItem(arch, arch)
        # pre-select current style's arch if known, otherwise "Any" (most LoRAs have no base_model info)
        idx = self._arch_combo.findData(current_arch)
        self._arch_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self._arch_combo.currentIndexChanged.connect(self._apply_filter)

        self._refresh_btn = QToolButton(self)
        self._refresh_btn.setIcon(theme.icon("reset"))
        self._refresh_btn.setToolTip(_("Reload LoRA list from server"))
        self._refresh_btn.clicked.connect(self._load_loras)

        top_layout = QHBoxLayout()
        top_layout.addWidget(self._search, 1)
        top_layout.addWidget(arch_label)
        top_layout.addWidget(self._arch_combo)
        top_layout.addWidget(self._refresh_btn)

        # ── tag filter row ──
        self._tag_buttons: dict[str, QPushButton] = {}
        tag_layout = QHBoxLayout()
        tag_layout.setSpacing(4)
        for tag in [_TAG_ALL] + _KNOWN_TAGS:
            label = _("All") if tag == _TAG_ALL else tag.capitalize()
            btn = QPushButton(label, self)
            btn.setCheckable(True)
            btn.setChecked(tag == _TAG_ALL)
            btn.setFlat(True)
            btn.clicked.connect(lambda checked, t=tag: self._select_tag(t))
            self._tag_buttons[tag] = btn
            tag_layout.addWidget(btn)
        tag_layout.addStretch()

        # ── grid ──
        self._grid = QListWidget(self)
        self._grid.setViewMode(QListWidget.ViewMode.IconMode)
        self._grid.setIconSize(QSize(_PREVIEW_SIZE, _PREVIEW_SIZE))
        self._grid.setGridSize(QSize(_PREVIEW_SIZE + 16, _PREVIEW_SIZE + 40))
        self._grid.setResizeMode(QListWidget.ResizeMode.Adjust)
        self._grid.setMovement(QListWidget.Movement.Static)
        self._grid.setWordWrap(True)
        self._grid.setSpacing(4)
        self._grid.itemSelectionChanged.connect(self._on_selection_changed)

        # ── bottom bar ──
        self._selected_label = QLabel(_("No LoRA selected"), self)
        self._selected_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        strength_label = QLabel(_("Strength:"), self)
        self._strength = QDoubleSpinBox(self)
        self._strength.setMinimum(0.0)
        self._strength.setMaximum(2.0)
        self._strength.setSingleStep(0.05)
        self._strength.setValue(1.0)
        self._strength.setDecimals(2)
        self._strength.setFixedWidth(72)

        self._add_btn = QPushButton(_("Add to Prompt"), self)
        self._add_btn.setEnabled(False)
        self._add_btn.clicked.connect(self._add_to_prompt)

        close_btn = QPushButton(_("Close"), self)
        close_btn.clicked.connect(self.close)

        bottom_layout = QHBoxLayout()
        bottom_layout.addWidget(self._selected_label, 1)
        bottom_layout.addWidget(strength_label)
        bottom_layout.addWidget(self._strength)
        bottom_layout.addWidget(self._add_btn)
        bottom_layout.addWidget(close_btn)

        # ── status ──
        self._status = QLabel(_("Loading…"), self)
        self._status.setStyleSheet(f"color: {theme.grey}; font-style: italic;")

        layout = QVBoxLayout()
        layout.addLayout(top_layout)
        layout.addLayout(tag_layout)
        layout.addWidget(self._grid, 1)
        layout.addWidget(self._status)
        layout.addLayout(bottom_layout)
        self.setLayout(layout)

        self._load_loras()

    # ── data loading ──

    def _load_loras(self):
        self._status.setText(_("Loading…"))
        self._grid.clear()
        self._all_loras = []
        eventloop.run(self._fetch())

    async def _fetch(self):
        client = root.connection.client_if_connected
        if client is None:
            self._status.setText(_("Not connected to ComfyUI"))
            return
        loras = await fetch_loras(client._requests, client.url)
        if not loras:
            self._status.setText(_("LoRA Manager not installed or no LoRAs found"))
            return
        self._all_loras = loras
        self._apply_filter()

    # ── filtering ──

    def _select_tag(self, tag: str):
        self._active_tag = tag
        for t, btn in self._tag_buttons.items():
            btn.setChecked(t == tag)
        self._apply_filter()

    def _apply_filter(self):
        search = self._search.text().lower()
        arch = self._arch_combo.currentData()
        arch = "" if arch == _ARCH_ANY else (arch or "")

        def matches(lora: LoraInfo) -> bool:
            if arch and lora.base_model:
                lora_arch = arch_for_base_model(lora.base_model)
                if lora_arch and lora_arch != arch:
                    return False
            # no base_model info or unmapped → show always
            if self._active_tag != _TAG_ALL:
                if not any(self._active_tag in t.lower() for t in lora.tags):
                    return False
            if search:
                haystack = lora.name.lower() + " " + " ".join(lora.tags).lower()
                if search not in haystack:
                    return False
            return True

        self._filtered = [l for l in self._all_loras if matches(l)]
        self._populate_grid()

    def _populate_grid(self):
        self._grid.clear()
        for lora in self._filtered:
            item = QListWidgetItem(lora.name)
            item.setData(Qt.ItemDataRole.UserRole, lora)
            item.setToolTip(
                f"{lora.name}\nBase: {lora.base_model or '?'}\n"
                + (f"Triggers: {', '.join(lora.trigger_words)}" if lora.trigger_words else "")
            )
            if lora.sha256 in self._preview_cache:
                item.setIcon(QIcon(self._preview_cache[lora.sha256]))
            elif lora.preview_url and lora.sha256 not in self._pending_previews:
                self._pending_previews.add(lora.sha256)
                eventloop.run(self._load_preview(lora, item))
            self._grid.addItem(item)
        count = len(self._filtered)
        total = len(self._all_loras)
        self._status.setText(f"{count} / {total} LoRAs")

    async def _load_preview(self, lora: LoraInfo, item: QListWidgetItem):
        client = root.connection.client_if_connected
        if client is None:
            return
        data = await fetch_preview_bytes(client._requests, lora.preview_url)
        if data:
            pixmap = QPixmap()
            pixmap.loadFromData(data)
            if not pixmap.isNull():
                pixmap = pixmap.scaled(
                    _PREVIEW_SIZE,
                    _PREVIEW_SIZE,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
                self._preview_cache[lora.sha256] = pixmap
                item.setIcon(QIcon(pixmap))

    # ── selection / insertion ──

    def _on_selection_changed(self):
        items = self._grid.selectedItems()
        if items:
            lora: LoraInfo = items[0].data(Qt.ItemDataRole.UserRole)
            self._selected_label.setText(f"{lora.name}  [{lora.base_model or '?'}]")
            self._add_btn.setEnabled(True)
        else:
            self._selected_label.setText(_("No LoRA selected"))
            self._add_btn.setEnabled(False)

    def _add_to_prompt(self):
        items = self._grid.selectedItems()
        if not items:
            return
        lora: LoraInfo = items[0].data(Qt.ItemDataRole.UserRole)
        strength = self._strength.value()
        tag = f"<lora:{lora.name}:{strength:.2f}>"
        model = root.active_model
        if model is None:
            return
        region = model.regions.active_or_root
        current = region.positive
        separator = ", " if current.strip() and not current.rstrip().endswith(",") else ""
        region.positive = current.rstrip() + separator + tag
        self.lora_selected.emit(lora.name, strength)
