from __future__ import annotations

import hashlib
import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from .. import util
from ..util import client_logger as log

if TYPE_CHECKING:
    from .network import RequestManager

_STRIP_SUFFIXES = (".safetensors", ".pt", ".ckpt", ".bin")
_CACHE_MAX_AGE = 6 * 3600  # seconds


def _clean_name(file_name: str) -> str:
    for suffix in _STRIP_SUFFIXES:
        if file_name.endswith(suffix):
            return file_name[: -len(suffix)]
    return file_name


@dataclass
class LoraInfo:
    name: str  # file name without extension - this is what ComfyUI expects in <lora:name:weight>
    display_name: str = ""  # human-readable title shown in the UI
    base_model: str = ""
    tags: list[str] = field(default_factory=list)
    preview_url: str = ""
    # Each entry is one alternative trigger phrase / word group, as reported by
    # CivitAI - they are alternatives, not meant to be concatenated together.
    trigger_words: list[str] = field(default_factory=list)
    sha256: str = ""
    favorite: bool = False

    @staticmethod
    def from_api(data: dict, base_url: str) -> LoraInfo:
        # ComfyUI-Lora-Manager format: GET /api/lm/loras/list
        file_name = data.get("file_name") or data.get("model_name", "")
        name = _clean_name(file_name)
        display_name = data.get("model_name") or name
        sha256 = data.get("sha256", "")
        preview = data.get("preview_url", "")
        if preview and preview.startswith("/"):
            preview = base_url + preview
        tags = data.get("tags") or []
        if isinstance(tags, str):
            tags = [t.strip() for t in tags.split(",") if t.strip()]
        trigger_words = []
        civitai = data.get("civitai") or {}
        if isinstance(civitai, dict):
            trigger_words = civitai.get("trainedWords") or []
        return LoraInfo(
            name=name,
            display_name=display_name,
            base_model=data.get("base_model", ""),
            tags=tags,
            preview_url=preview,
            trigger_words=trigger_words,
            favorite=bool(data.get("favorite", False)),
            sha256=sha256,
        )


# base_model strings (as stored by ComfyUI-Lora-Manager metadata) → Arch enum value name
# Longer/more specific keys must come before shorter ones they overlap with
# (e.g. "illustrious" before "sd xl", "flux kontext" before "flux").
_BASE_MODEL_MAP = [
    ("illustrious", "illu"),
    ("pony", "sdxl"),
    ("sdxl", "sdxl"),
    ("sd xl", "sdxl"),
    ("sd 1", "sd15"),
    ("sd1", "sd15"),
    ("v1", "sd15"),
    ("sd 3", "sd3"),
    ("sd3", "sd3"),
    ("flux kontext", "flux_k"),
    ("flux", "flux"),
    ("chroma", "chroma"),
    ("qwen", "qwen"),
    ("anima", "anima"),
    ("z-image", "zimage"),
    ("zimage", "zimage"),
    ("ernie", "ernie"),
    ("krea", "krea2"),
]


def arch_for_base_model(base_model: str) -> str:
    """Return Arch enum name (e.g. 'sdxl') for a base_model string, or '' if unknown."""
    lower = base_model.lower()
    for key, arch in _BASE_MODEL_MAP:
        if key in lower:
            return arch
    return ""


def _cache_path(base_url: str) -> Path:
    url_hash = hashlib.md5(base_url.encode()).hexdigest()[:8]
    return util.user_data_dir / f"lora_manager_cache_{url_hash}.json"


def load_cached_loras(base_url: str) -> list[LoraInfo] | None:
    """Return cached LoRA list if present and not expired, else None."""
    path = _cache_path(base_url)
    try:
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        if time.time() - data.get("timestamp", 0) > _CACHE_MAX_AGE:
            return None
        return [LoraInfo(**item) for item in data.get("loras", [])]
    except Exception as e:
        log.warning(f"Could not load LoRA cache: {e}")
        return None


def save_lora_cache(base_url: str, loras: list[LoraInfo]):
    path = _cache_path(base_url)
    try:
        data = {"timestamp": time.time(), "loras": [asdict(l) for l in loras]}
        path.write_text(json.dumps(data), encoding="utf-8")
    except Exception as e:
        log.warning(f"Could not save LoRA cache: {e}")


async def fetch_loras_pages(requests: RequestManager, base_url: str):
    """Yield LoRA list incrementally, one server page at a time.

    Falls back to a single yield from /models/loras (filename list only) if
    ComfyUI-Lora-Manager is not installed.
    """
    base = base_url.rstrip("/")

    # ComfyUI-Lora-Manager (rich metadata: tags, base_model, preview, trigger words)
    # Server caps page_size regardless of what we request, so page through all results.
    try:
        page = 1
        page_size = 200
        got_any = False
        while True:
            data = await requests.get(
                f"{base}/api/lm/loras/list?page={page}&page_size={page_size}", timeout=15.0
            )
            if isinstance(data, (bytes, bytearray)):
                data = json.loads(data)
            if not isinstance(data, dict):
                break
            items = data.get("items") or data.get("loras") or []
            if not items:
                break
            got_any = True
            batch = [LoraInfo.from_api(item, base) for item in items]
            yield batch
            total = data.get("total", page * page_size)
            actual_page_size = data.get("page_size", page_size)
            loaded = page * actual_page_size
            if loaded >= total or len(items) < actual_page_size:
                break
            page += 1
        if got_any:
            return
    except Exception as e:
        log.warning(f"Lora Manager API not available: {e}")

    # Fallback: standard ComfyUI /models/loras (filename list only)
    try:
        data = await requests.get(f"{base}/models/loras", timeout=10.0)
        if isinstance(data, (bytes, bytearray)):
            data = json.loads(data)
        if isinstance(data, list):
            result = []
            for entry in data:
                if isinstance(entry, str):
                    result.append(LoraInfo(name=_clean_name(entry), display_name=_clean_name(entry)))
                elif isinstance(entry, dict):
                    result.append(LoraInfo.from_api(entry, base))
            if result:
                log.info(f"Loaded {len(result)} LoRAs from /models/loras (no metadata)")
                yield result
    except Exception as e:
        log.warning(f"Could not fetch LoRA list: {e}")


async def fetch_preview_bytes(requests: RequestManager, preview_url: str) -> bytes | None:
    """Fetch preview image bytes. Returns None on error."""
    if not preview_url:
        return None
    try:
        result = await requests.download(preview_url, timeout=8.0)
        return bytes(result) if result else None
    except Exception as e:
        log.warning(f"Could not fetch LoRA preview {preview_url}: {e}")
        return None
