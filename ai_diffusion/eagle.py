"""Send generated images to the Eagle app (https://eagle.cool) via its local API."""

from __future__ import annotations

import time
from pathlib import Path
from typing import TYPE_CHECKING

from . import util
from .backend.network import RequestManager
from .localization import translate as _
from .text import create_img_metadata
from .util import client_logger as log

if TYPE_CHECKING:
    from .model.jobs import Job

EAGLE_URL = "http://localhost:41595"

_upload_dir = util.user_data_dir / "eagle_upload"
_requests: RequestManager | None = None


def _request_manager() -> RequestManager:
    # keep one instance alive - a per-call QNetworkAccessManager can be
    # garbage-collected before the reply arrives
    global _requests
    if _requests is None:
        _requests = RequestManager()
    return _requests


def _cleanup_old_uploads(max_age_hours: float = 24):
    try:
        if not _upload_dir.exists():
            return
        cutoff = time.time() - max_age_hours * 3600
        for f in _upload_dir.iterdir():
            if f.is_file() and f.stat().st_mtime < cutoff:
                f.unlink(missing_ok=True)
    except Exception as e:
        log.warning(f"Could not clean up eagle upload dir: {e}")


async def send_image_to_eagle(image, job: Job, index: int) -> str | None:
    """Save composited result to a temp file and import it into Eagle.

    Returns an error message on failure, None on success. The temp file is kept
    (Eagle imports asynchronously) and cleaned up on later calls after 24h.
    """
    _cleanup_old_uploads()
    _upload_dir.mkdir(parents=True, exist_ok=True)

    timestamp = job.timestamp.strftime("%Y%m%d-%H%M%S")
    prompt = util.sanitize_prompt(job.params.name)
    file_name = f"krita-ai-{timestamp}-{index}-{prompt}"[:120] + ".png"
    path = util.find_unused_path(_upload_dir / file_name)

    metadata_text = create_img_metadata(job.params)
    image.save_png_with_metadata(filepath=path, metadata_text=metadata_text)

    tags = ["krita-ai"]
    if style := job.params.metadata.get("style"):
        tags.append(str(style))
    for lora in job.params.metadata.get("loras", []):
        if isinstance(lora, dict) and lora.get("name"):
            tags.append(Path(str(lora["name"])).stem)

    payload = {
        "path": str(path),
        "name": job.params.name[:100] or "Krita AI generation",
        "annotation": metadata_text,
        "tags": tags,
    }
    try:
        result = await _request_manager().post(f"{EAGLE_URL}/api/item/addFromPath", payload)
        if isinstance(result, dict) and result.get("status") == "success":
            return None
        return _("Eagle returned an error") + f": {result}"
    except Exception as e:
        log.warning(f"Could not send image to Eagle: {e}")
        return _("Could not reach Eagle - is the app running?") + f" ({e})"
