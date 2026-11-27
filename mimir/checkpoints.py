"""Checkpoints: save the whole project before a risky change, compare against
it, and roll back in one call. Stored under <project>/.mimir/checkpoints/."""
from __future__ import annotations

import difflib
import hashlib
import json
import os
import re
import shutil
import time
from pathlib import Path

from .codemap import SKIP_DIRS

MAX_FILE_BYTES = 1_000_000
MAX_DIFF_CHARS = 6000


class Checkpoints:
    def __init__(self, root: str | Path):
        self.root = Path(root).resolve()
        self.store = self.root / ".mimir" / "checkpoints"

    def _project_files(self) -> list[str]:
        out = []
        for dirpath, dirnames, filenames in os.walk(self.root):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")]
            for f in filenames:
                p = Path(dirpath, f)
                if p.stat().st_size <= MAX_FILE_BYTES:
                    out.append(p.relative_to(self.root).as_posix())
        return sorted(out)

    @staticmethod
    def _hash(p: Path) -> str:
        return hashlib.sha1(p.read_bytes()).hexdigest()

    def _dir(self, cp_id: str) -> Path:
        d = self.store / cp_id
        if not re.fullmatch(r"[\w-]+", cp_id) or not d.is_dir():
            raise ValueError(f"No checkpoint '{cp_id}'. Use list_checkpoints().")
        return d

    def _manifest(self, cp_id: str) -> dict:
        return json.loads((self._dir(cp_id) / "manifest.json").read_text())

    def create(self, label: str = "") -> str:
        n = len(list(self.store.glob("*"))) + 1 if self.store.exists() else 1
        slug = re.sub(r"[^\w-]+", "-", label.strip().lower()).strip("-")[:40]
        cp_id = f"{n:03d}-{slug}" if slug else f"{n:03d}"
        d = self.store / cp_id
        files = {}
        for rel in self._project_files():
            dst = d / "files" / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(self.root / rel, dst)
            files[rel] = self._hash(self.root / rel)
        (d / "manifest.json").write_text(json.dumps(
            {"id": cp_id, "label": label, "time": time.strftime("%Y-%m-%d %H:%M:%S"), "files": files}, indent=1))
        return cp_id

    def list(self) -> list[dict]:
        if not self.store.exists():
            return []
        out = []
        for d in sorted(self.store.iterdir()):
            m = d / "manifest.json"
            if m.exists():
                data = json.loads(m.read_text())
                out.append({"id": data["id"], "label": data["label"], "time": data["time"],
                            "files": len(data["files"])})
        return out

    def changes(self, cp_id: str) -> dict[str, list[str]]:
        saved = self._manifest(cp_id)["files"]
        now = {rel: self._hash(self.root / rel) for rel in self._project_files()}
        return {
            "modified": sorted(r for r in saved if r in now and now[r] != saved[r]),
            "added": sorted(r for r in now if r not in saved),
            "deleted": sorted(r for r in saved if r not in now),
        }

    def diff(self, cp_id: str) -> str:
        ch = self.changes(cp_id)
        d = self._dir(cp_id) / "files"
        parts = []
        for rel in ch["modified"] + ch["added"] + ch["deleted"]:
            old = (d / rel).read_text(encoding="utf-8", errors="replace").splitlines() if (d / rel).exists() else []
            new = (self.root / rel).read_text(encoding="utf-8", errors="replace").splitlines() \
                if (self.root / rel).exists() else []
            parts.extend(difflib.unified_diff(old, new, f"a/{rel}", f"b/{rel}", lineterm="", n=2))
        text = "\n".join(parts) or "No changes since this checkpoint."
        return text if len(text) <= MAX_DIFF_CHARS else text[:MAX_DIFF_CHARS] + "\n... (diff truncated)"

    def restore(self, cp_id: str) -> dict:
        ch = self.changes(cp_id)
        if not any(ch.values()):
            return {"restored_from": cp_id, "safety_checkpoint": None, **ch}
        # make restore itself undoable
        safety = self.create(f"pre-restore-{cp_id.split('-')[0]}")
        src = self._dir(cp_id) / "files"
        for rel in ch["modified"] + ch["deleted"]:
            (self.root / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src / rel, self.root / rel)
        for rel in ch["added"]:
            (self.root / rel).unlink()
        return {"restored_from": cp_id, "safety_checkpoint": safety, **ch}
