from __future__ import annotations

from PyQt5.QtCore import QSize, Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QIcon, QPixmap
from PyQt5.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSizePolicy,
    QSlider,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .. import eventloop
from ..backend.lora_manager import (
    LoraInfo,
    arch_for_base_model,
    fetch_loras_pages,
    fetch_preview_bytes,
    load_cached_loras,
    save_lora_cache,
)
from ..localization import translate as _
from ..model.root import root
from . import theme

_PREVIEW_SIZE_DEFAULT = 96
_PREVIEW_SIZE_MIN = 48
_PREVIEW_SIZE_MAX = 192
_TAG_ALL = "__all__"
_MAX_TAG_ENTRIES = 30
_TRIGGER_ALL = "__all_triggers__"
_ARCH_ANY = "__any__"
_KNOWN_ARCHES = [
    "sd15", "sdxl", "illu", "sd3", "flux", "flux_k",
    "chroma", "qwen", "anima", "zimage", "ernie", "krea2",
]
_VIDEO_EXTENSIONS = (".mp4", ".webm", ".mov")


def _is_video_url(url: str) -> bool:
    # the real filename is in the `path` query param (e.g. /api/lm/previews?path=...mp4),
    # so check the whole url rather than stripping the query string
    lower = url.lower()
    return any(lower.endswith(ext) for ext in _VIDEO_EXTENSIONS)


class LoraPickerDialog(QDialog):
    lora_selected = pyqtSignal(str, float)  # name, strength

    def __init__(self, current_arch: str, parent: QWidget | None = None):
        super().__init__(parent)
        self._current_arch = current_arch
        self._all_loras: list[LoraInfo] = []
        self._filtered: list[LoraInfo] = []
        self._preview_cache: dict[str, QPixmap] = {}  # original, unscaled
        self._pending_previews: set[str] = set()
        self._loading = False
        self._preview_size = _PREVIEW_SIZE_DEFAULT

        self.setWindowTitle(_("LoRA Browser"))
        self.setMinimumSize(640, 480)
        self.resize(800, 560)
        # Non-modal: Krita stays interactive while this dialog is open
        self.setModal(False)
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.Window)

        # ── row 1: search ──
        self._search = QLineEdit(self)
        self._search.setPlaceholderText(_("Search LoRAs…"))
        self._search.textChanged.connect(self._apply_filter)

        self._refresh_btn = QToolButton(self)
        self._refresh_btn.setIcon(theme.icon("reset"))
        self._refresh_btn.setToolTip(_("Reload LoRA list from server (bypass cache)"))
        self._refresh_btn.clicked.connect(self._force_reload)

        row1 = QHBoxLayout()
        row1.addWidget(self._search, 1)
        row1.addWidget(self._refresh_btn)

        # ── row 2: base model + tag dropdowns ──
        arch_label = QLabel(_("Base Model:"), self)
        self._arch_combo = QComboBox(self)
        self._arch_combo.addItem(_("Any"), _ARCH_ANY)
        for arch in _KNOWN_ARCHES:
            self._arch_combo.addItem(arch, arch)
        idx = self._arch_combo.findData(current_arch)
        self._arch_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self._arch_combo.currentIndexChanged.connect(self._apply_filter)

        tag_label = QLabel(_("Tag:"), self)
        self._tag_combo = QComboBox(self)
        self._tag_combo.addItem(_("All"), _TAG_ALL)
        self._tag_combo.currentIndexChanged.connect(self._apply_filter)

        self._favorites_only = QCheckBox(_("Favorites"), self)
        self._favorites_only.toggled.connect(self._apply_filter)

        size_label = QLabel(_("Size:"), self)
        self._size_slider = QSlider(Qt.Orientation.Horizontal, self)
        self._size_slider.setMinimum(_PREVIEW_SIZE_MIN)
        self._size_slider.setMaximum(_PREVIEW_SIZE_MAX)
        self._size_slider.setValue(_PREVIEW_SIZE_DEFAULT)
        self._size_slider.setFixedWidth(90)
        self._size_slider.valueChanged.connect(self._on_preview_size_changed)

        row2 = QHBoxLayout()
        row2.addWidget(arch_label)
        row2.addWidget(self._arch_combo, 1)
        row2.addWidget(tag_label)
        row2.addWidget(self._tag_combo, 1)
        row2.addWidget(self._favorites_only)
        row2.addWidget(size_label)
        row2.addWidget(self._size_slider)

        # ── grid ──
        self._grid = QListWidget(self)
        self._grid.setViewMode(QListWidget.ViewMode.IconMode)
        self._grid.setIconSize(QSize(self._preview_size, self._preview_size))
        self._grid.setGridSize(QSize(self._preview_size + 16, self._preview_size + 40))
        self._grid.setResizeMode(QListWidget.ResizeMode.Adjust)
        self._grid.setMovement(QListWidget.Movement.Static)
        self._grid.setWordWrap(True)
        self._grid.setSpacing(4)
        self._grid.itemSelectionChanged.connect(self._on_selection_changed)

        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(120)
        self._preview_timer.timeout.connect(self._load_visible_previews)
        self._grid.verticalScrollBar().valueChanged.connect(self._schedule_visible_previews)

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

        self._include_triggers = QCheckBox(_("+ triggers:"), self)
        self._include_triggers.setChecked(True)
        self._include_triggers.setToolTip(
            _("Also insert the selected trigger word group into the prompt")
        )
        self._include_triggers.toggled.connect(self._update_trigger_combo_enabled)

        self._trigger_combo = QComboBox(self)
        self._trigger_combo.setMinimumWidth(160)
        self._trigger_combo.setToolTip(
            _("CivitAI lists alternative trigger phrases - pick which one to insert")
        )

        self._add_btn = QPushButton(_("Add to Prompt"), self)
        self._add_btn.setEnabled(False)
        self._add_btn.clicked.connect(self._add_to_prompt)

        close_btn = QPushButton(_("Close"), self)
        close_btn.clicked.connect(self.close)

        bottom_layout = QHBoxLayout()
        bottom_layout.addWidget(self._selected_label, 1)
        bottom_layout.addWidget(strength_label)
        bottom_layout.addWidget(self._strength)
        bottom_layout.addWidget(self._include_triggers)
        bottom_layout.addWidget(self._trigger_combo)
        bottom_layout.addWidget(self._add_btn)
        bottom_layout.addWidget(close_btn)

        # ── status ──
        self._status = QLabel(_("Loading…"), self)
        self._status.setStyleSheet(f"color: {theme.grey}; font-style: italic;")

        layout = QVBoxLayout()
        layout.addLayout(row1)
        layout.addLayout(row2)
        layout.addWidget(self._grid, 1)
        layout.addWidget(self._status)
        layout.addLayout(bottom_layout)
        self.setLayout(layout)

        self._load_loras()

    # ── data loading ──

    def _load_loras(self, force_refresh: bool = False):
        if self._loading:
            return
        client = root.connection.client_if_connected
        if client is None:
            self._status.setText(_("Not connected to ComfyUI"))
            return

        if not force_refresh:
            cached = load_cached_loras(client.url)
            if cached:
                self._all_loras = cached
                self._rebuild_filters()
                self._apply_filter()
                self._status.setText(f"{len(cached)} {_('LoRAs (cached)')}")
                return

        self._status.setText(_("Loading…"))
        self._grid.clear()
        self._all_loras = []
        self._loading = True
        eventloop.run(self._fetch_progressive(client))

    def _force_reload(self):
        self._load_loras(force_refresh=True)

    async def _fetch_progressive(self, client):
        try:
            async for batch in fetch_loras_pages(client._requests, client.url):
                self._all_loras.extend(batch)
                self._rebuild_filters()
                self._apply_filter()
                self._status.setText(f"{_('Loading…')} ({len(self._all_loras)})")
        finally:
            self._loading = False
            if self._all_loras:
                save_lora_cache(client.url, self._all_loras)
                self._status.setText(f"{len(self._filtered)} / {len(self._all_loras)} LoRAs")
            else:
                self._status.setText(_("LoRA Manager not installed or no LoRAs found"))

    # ── filtering ──

    def _rebuild_filters(self):
        counts: dict[str, int] = {}
        for lora in self._all_loras:
            for tag in lora.tags:
                counts[tag] = counts.get(tag, 0) + 1
        top_tags = sorted(counts, key=lambda t: -counts[t])[:_MAX_TAG_ENTRIES]

        current = self._tag_combo.currentData()
        self._tag_combo.blockSignals(True)
        self._tag_combo.clear()
        self._tag_combo.addItem(_("All"), _TAG_ALL)
        for tag in top_tags:
            self._tag_combo.addItem(f"{tag} ({counts[tag]})", tag)
        idx = self._tag_combo.findData(current)
        self._tag_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self._tag_combo.blockSignals(False)

    def _apply_filter(self):
        search = self._search.text().lower()
        arch = self._arch_combo.currentData()
        arch = "" if arch == _ARCH_ANY else (arch or "")
        active_tag = self._tag_combo.currentData()
        favorites_only = self._favorites_only.isChecked()

        def matches(lora: LoraInfo) -> bool:
            if favorites_only and not lora.favorite:
                return False
            if arch:
                if lora.base_model:
                    # has base_model info: must match, even if we don't recognize
                    # the string (otherwise unmapped models like "NoobAI" would
                    # bypass every arch filter)
                    if arch_for_base_model(lora.base_model) != arch:
                        return False
                # else: no base_model info at all -> can't tell, show anyway
            if active_tag and active_tag != _TAG_ALL:
                if active_tag not in lora.tags:
                    return False
            if search:
                haystack = (lora.name + " " + lora.display_name + " " + " ".join(lora.tags)).lower()
                if search not in haystack:
                    return False
            return True

        self._filtered = [l for l in self._all_loras if matches(l)]
        self._populate_grid()

    def _populate_grid(self):
        self._grid.clear()
        for lora in self._filtered:
            item = QListWidgetItem(lora.display_name or lora.name)
            item.setData(Qt.ItemDataRole.UserRole, lora)
            fav = "★ " if lora.favorite else ""
            item.setToolTip(
                f"{fav}{lora.display_name}\nFile: {lora.name}\nBase: {lora.base_model or '?'}\n"
                + (f"Triggers: {' | '.join(lora.trigger_words)}" if lora.trigger_words else "")
            )
            if lora.sha256 in self._preview_cache:
                item.setIcon(self._scaled_icon(lora.sha256))
            elif lora.preview_url and _is_video_url(lora.preview_url):
                item.setIcon(theme.icon("play"))
            self._grid.addItem(item)
        if not self._loading:
            self._status.setText(f"{len(self._filtered)} / {len(self._all_loras)} LoRAs")
        self._schedule_visible_previews()

    def _scaled_icon(self, sha256: str) -> QIcon:
        pixmap = self._preview_cache[sha256]
        scaled = pixmap.scaled(
            self._preview_size,
            self._preview_size,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        return QIcon(scaled)

    def _on_preview_size_changed(self, value: int):
        self._preview_size = value
        self._grid.setIconSize(QSize(value, value))
        self._grid.setGridSize(QSize(value + 16, value + 40))
        for i in range(self._grid.count()):
            item = self._grid.item(i)
            lora: LoraInfo = item.data(Qt.ItemDataRole.UserRole)
            if lora.sha256 in self._preview_cache:
                item.setIcon(self._scaled_icon(lora.sha256))
        self._schedule_visible_previews()

    # ── lazy preview loading (only visible items) ──

    def _schedule_visible_previews(self):
        self._preview_timer.start()

    def _load_visible_previews(self):
        viewport_rect = self._grid.viewport().rect()
        client = root.connection.client_if_connected
        if client is None:
            return
        for i in range(self._grid.count()):
            item = self._grid.item(i)
            rect = self._grid.visualItemRect(item)
            if not rect.intersects(viewport_rect):
                continue
            lora: LoraInfo = item.data(Qt.ItemDataRole.UserRole)
            if not lora.preview_url or lora.sha256 in self._preview_cache:
                continue
            if _is_video_url(lora.preview_url):
                continue  # handled synchronously in _populate_grid
            if lora.sha256 in self._pending_previews:
                continue
            self._pending_previews.add(lora.sha256)
            eventloop.run(self._load_preview(lora, item))

    async def _load_preview(self, lora: LoraInfo, item: QListWidgetItem):
        client = root.connection.client_if_connected
        if client is None:
            return
        data = await fetch_preview_bytes(client._requests, lora.preview_url)
        if data:
            pixmap = QPixmap()
            pixmap.loadFromData(data)
            if not pixmap.isNull():
                self._preview_cache[lora.sha256] = pixmap
                item.setIcon(self._scaled_icon(lora.sha256))
            else:
                # format not decodable by Qt (e.g. some animated webp builds) - placeholder
                item.setIcon(theme.icon("filter"))

    # ── selection / insertion ──

    def _on_selection_changed(self):
        items = self._grid.selectedItems()
        if items:
            lora: LoraInfo = items[0].data(Qt.ItemDataRole.UserRole)
            fav = "★ " if lora.favorite else ""
            self._selected_label.setText(f"{fav}{lora.display_name}  [{lora.base_model or '?'}]")
            self._add_btn.setEnabled(True)
            self._trigger_combo.clear()
            if lora.trigger_words:
                self._trigger_combo.addItem(_("All"), _TRIGGER_ALL)
                for group in lora.trigger_words:
                    self._trigger_combo.addItem(group, group)
                self._trigger_combo.setCurrentIndex(0)
            self._update_trigger_combo_enabled()
        else:
            self._selected_label.setText(_("No LoRA selected"))
            self._add_btn.setEnabled(False)
            self._trigger_combo.clear()

    def _update_trigger_combo_enabled(self):
        enabled = self._include_triggers.isChecked() and self._trigger_combo.count() > 0
        self._trigger_combo.setEnabled(enabled)

    def _add_to_prompt(self):
        items = self._grid.selectedItems()
        if not items:
            return
        lora: LoraInfo = items[0].data(Qt.ItemDataRole.UserRole)
        strength = self._strength.value()
        parts = [f"<lora:{lora.name}:{strength:.2f}>"]
        if self._include_triggers.isChecked() and self._trigger_combo.currentData():
            selected = self._trigger_combo.currentData()
            if selected == _TRIGGER_ALL:
                parts.append("\n----\n".join(lora.trigger_words))
            else:
                parts.append(selected)
        addition = " ".join(parts)
        model = root.active_model
        if model is None:
            return
        region = model.regions.active_or_root
        current = region.positive
        # always add the lora on its own new line at the end of the prompt
        region.positive = current.rstrip("\n") + "\n" + addition
        self.lora_selected.emit(lora.name, strength)
