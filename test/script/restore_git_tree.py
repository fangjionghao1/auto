"""Restore missing project files from a Git tree without overwriting local files.

Usage: python test/script/restore_git_tree.py TREE gen/artifacts/ID/VERSION/PROJECT
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import subprocess
import sys


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    tree, prefix = sys.argv[1:]
    prefix = prefix.replace("\\", "/").rstrip("/")
    if not prefix.startswith("gen/artifacts/") or ".." in PurePosixPath(prefix).parts:
        raise SystemExit("Refusing path outside gen/artifacts")

    root = Path(__file__).resolve().parents[2]
    raw = subprocess.check_output(
        ["git", "ls-tree", "-r", "-z", tree, "--", prefix], cwd=root
    )
    if not raw:
        raise SystemExit(f"No files under {prefix} in {tree}")

    restored = []
    skipped = []
    for entry in raw.split(b"\0"):
        if not entry:
            continue
        metadata, raw_path = entry.split(b"\t", 1)
        _, kind, object_id = metadata.decode("ascii").split()
        if kind != "blob":
            raise SystemExit(f"Unexpected Git object type: {kind}")
        relative = PurePosixPath(raw_path.decode("utf-8"))
        if relative.as_posix() != prefix and not relative.as_posix().startswith(prefix + "/"):
            raise SystemExit(f"Unexpected file path: {relative}")
        destination = (root / Path(*relative.parts)).resolve()
        if not destination.is_relative_to(root):
            raise SystemExit(f"Path escape: {destination}")
        if destination.exists():
            skipped.append(str(relative))
            continue
        data = subprocess.check_output(["git", "cat-file", "blob", object_id], cwd=root)
        destination.parent.mkdir(parents=True, exist_ok=True)
        with os.fdopen(os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o666), "wb") as out:
            out.write(data)
        restored.append({
            "path": str(relative),
            "git_blob": object_id,
            "sha256": hashlib.sha256(data).hexdigest(),
            "bytes": len(data),
        })
    print(json.dumps({"tree": tree, "restored": restored, "skipped_existing": skipped}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
