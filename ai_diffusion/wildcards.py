"""File-based wildcards: __name__ in a prompt picks a random line from
<user_data_dir>/wildcards/name.txt (or wildcards/folder/name.txt for
__folder/name__), matching the convention used by collections like
https://github.com/mattjaybe/sd-wildcards - drop such a repo's `wildcards/`
folder in directly and it works with no extra setup."""

from __future__ import annotations

from pathlib import Path

from .util import client_logger as log
from .util import user_data_dir


class WildcardLibrary:
    default_folder = user_data_dir / "wildcards"

    def __init__(self, folder: Path | None = None):
        self.folder = folder or self.default_folder
        self._entries: dict[str, list[str]] = {}
        self.reload()

    def reload(self):
        """Rescan the wildcards folder. Call after adding/removing files."""
        entries: dict[str, list[str]] = {}
        if self.folder.exists():
            for path in self.folder.rglob("*.txt"):
                name = path.relative_to(self.folder).with_suffix("").as_posix().lower()
                lines = _read_lines(path)
                if lines:
                    entries[name] = lines
                else:
                    log.warning(f"Wildcard file has no usable lines: {path}")
        self._entries = entries

    def get(self, name: str) -> list[str] | None:
        return self._entries.get(name.lower())

    def names(self) -> list[str]:
        return sorted(self._entries.keys())

    def __len__(self):
        return len(self._entries)

    _instance: WildcardLibrary | None = None

    @classmethod
    def instance(cls) -> WildcardLibrary:
        if cls._instance is None:
            cls._instance = WildcardLibrary()
        return cls._instance


def _read_lines(path: Path) -> list[str]:
    try:
        lines = []
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            lines.append(line)
        return lines
    except Exception as e:
        log.warning(f"Could not read wildcard file {path}: {e}")
        return []
