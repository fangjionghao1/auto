"""Restore the verified 7-0928/V2 final snapshot from the Windows Recycle Bin.

Current src.md and speek.md are preserved. Only four agent-created drafts may
be overwritten; all other unexpected conflicts abort the restore.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
import shutil


WORKSPACE = Path(r"D:\wkplace\auto").resolve(strict=True)
RECYCLE = Path(
    r"D:\$RECYCLE.BIN\S-1-5-21-2271682461-3423110399-3263917966-500\$RANGO6Q"
).resolve(strict=True)
PROJECT_NAME = "基于注意力机制的新能源场站同步调相机功角稳定预测"
SOURCE = (RECYCLE / PROJECT_NAME).resolve(strict=True)
DESTINATION = (
    WORKSPACE / "gen" / "artifacts" / "7-0928" / "V2" / PROJECT_NAME
).resolve(strict=True)

EXPECTED = {
    "论文_中文.md": "8e5785c28da946b6fc3edc958ea8720fec468c2bee126b09e8c1df4ffbb8e839",
    "论文_英文.md": "9d4dba005f270a0d64af3d0f89704542eacfcd892ddf38d3cc43a565d153578c",
    "论文_中文.docx": "4a5029de01e256ae2150daacdaf5103d60dc2f7ed157ddbd75a9d3cba86df216",
    "论文_英文.docx": "9ee53a1d0b4c7dc063708af119b5425e39638e374dfcd1cb15b949a568efd04d",
    "仿真/仿真打包.zip": "76236ebef00f563e78389ab04cebeefeef2b9b690b8e6917f71c2197133cfb29",
    "仿真/simulation_cases.mat": "9be06560311e65806081d5c3e4a32fa34cac6f46405b3b1a3dcaaee3d1494950",
    "仿真/trajectory_points.csv": "a26ed36289f967534e19d57c09b8e544f410dbe12f7da0c6e5edd74fdf87ec81",
    "仿真/observations.csv": "ed2b3b6bb67ddad79b233b95fe30b510749d5f1ef98da5662108ba2eb237b0da",
}
PRESERVE = {"src.md", "speek.md"}
OVERWRITE_DRAFTS = {
    "框架.md",
    "仿真/params.m",
    "仿真/functions/pcc_model.m",
    "仿真/functions/solve_equilibrium.m",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> None:
    if not SOURCE.is_relative_to(RECYCLE) or not DESTINATION.is_relative_to(WORKSPACE):
        raise SystemExit("Resolved project paths are outside their intended roots")
    for relative, expected in EXPECTED.items():
        source = SOURCE / relative
        if not source.is_file() or sha256(source) != expected:
            raise SystemExit(f"Source preflight hash mismatch: {relative}")

    files = sorted(path for path in SOURCE.rglob("*") if path.is_file())
    if len(files) != 121:
        raise SystemExit(f"Unexpected source file count: {len(files)}")
    copied = skipped = overwritten = 0
    for source in files:
        source = source.resolve(strict=True)
        if not source.is_relative_to(SOURCE):
            raise SystemExit(f"Source path escape: {source}")
        relative = source.relative_to(SOURCE)
        relative_key = relative.as_posix()
        destination = (DESTINATION / relative).resolve()
        if not destination.is_relative_to(DESTINATION):
            raise SystemExit(f"Destination path escape: {destination}")
        if relative_key in PRESERVE:
            skipped += 1
            continue
        if destination.exists():
            if sha256(destination) == sha256(source):
                skipped += 1
                continue
            if relative_key not in OVERWRITE_DRAFTS:
                raise SystemExit(f"Unexpected destination conflict: {destination}")
            overwritten += 1
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        copied += 1

    for relative, expected in EXPECTED.items():
        if sha256(DESTINATION / relative) != expected:
            raise SystemExit(f"Post-restore hash mismatch: {relative}")
    print(f"source_files={len(files)} copied={copied} overwritten_drafts={overwritten} skipped={skipped}")
    print("Critical source and destination SHA-256 values match the historical final report.")


if __name__ == "__main__":
    main()
