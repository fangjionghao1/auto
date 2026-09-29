"""Finish the 6-0928/V1 snapshot recovery from verified Git blobs and ZIP entries."""

from __future__ import annotations

import hashlib
from pathlib import Path
import subprocess
import zipfile


ROOT = Path(__file__).resolve().parents[2]
PROJECT = ROOT / "gen/artifacts/6-0928/V1/基于图神经网络的新能源场站同步调相机小干扰稳定评估"

# Git's text normalization changed the standalone CSV byte endings. The
# original, report-hashed copies survive unmodified inside the simulation ZIP.
CSV = {
    "raw_results.csv": ("2cba85be7351c809f4c21570aab84650d285e900735c9047c6852c3ca12de0a5", "e8785db30a2f1f6fe606183f8f496a28784745b432a92248e964e414e21e9608"),
    "metrics.csv": ("dcb0b13966ca141b2af641e27a520b20eda9fda276372a0f04e1ef7fb2aea744", "85b346368f84b3a3764020bf7a9f039de15c5129ef95608252e79f87123ecc7e"),
    "variant_metrics.csv": ("b8f54d42ff410d3b2524a6b18b01e9617f96318defe50c54d1ab40dd05f3e10d", "0afd9bc0b525156465c296da1a8ef1d13246234dc7a084d56559c890e36f64b2"),
    "damping_scan.csv": ("408ec01508af998f775b714634d9ccd8792d1b15bfc5f900d77e4830c0a41d41", "e1188e05046cb691d85368f1e27fd057bb0ebb7ac6b03a69ecfe019859ebaec3"),
}

# (destination, Git blob, expected current SHA-256 or None, final SHA-256)
BLOBS = [
    ("P3_自检.md", "a271bd9be9739ab18e5112f62a72cffa37e605ae", "91aa807c830ea60a3f6c9366d5dcc453f4989cc79874e2f654e08a4885aed375", "52d18d8fe6149d69ee0778cd6d82db7b75ea6ae3c72b226b3a515c79761a4ad3"),
    ("目标配置卡.md", "9bd0195d0cd397b56bd290597c9e3f942f6fcc39", None, "2097983148724020f0440dbdc35d6751048ab3e2926f3e6626d80519939ea911"),
    ("交付说明.md", "07cae330975810ce919c62d4bc1dbf606816a16e", "c7a92736a8e41c549f9982d04115a4e0b0f05c3ce76ecf055b1015db490aca97", "49b28146796e9a551e4b60107fb286296efc07e1cd63ec4a31a922afe853b5ff"),
    ("排版核验/论文_中文.pdf", "b4a4cebbff3ed049bc463f3932dba11325dcbde7", None, "94248cc2369722498b146aa51be09d5b9b5460059148c2b0ad940cc1c7f18cac"),
    ("排版核验/论文_英文.pdf", "4503a88e3e764ab6167bee15b1f4803e84522549", None, "581241ba770e61d3c718d0e220ddfefda8f94c95f49e9c6936c681abff916d94"),
]


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> None:
    with zipfile.ZipFile(PROJECT / "仿真/仿真打包.zip") as archive:
        for name, (old_hash, final_hash) in CSV.items():
            target = PROJECT / "仿真" / name
            old = target.read_bytes()
            if sha256(old) == final_hash:
                print("Already final:", target.relative_to(ROOT))
                continue
            if sha256(old) != old_hash:
                raise SystemExit(f"Unexpected current CSV content: {target}")
            data = archive.read(name)
            if sha256(data) != final_hash:
                raise SystemExit(f"ZIP content hash mismatch: {name}")
            target.write_bytes(data)
            print("Restored CSV:", target.relative_to(ROOT))

    for relative, object_id, old_hash, final_hash in BLOBS:
        target = PROJECT / relative
        if target.exists():
            current_hash = sha256(target.read_bytes())
            if current_hash == final_hash:
                print("Already final:", target.relative_to(ROOT))
                continue
            if current_hash != old_hash:
                raise SystemExit(f"Unexpected current content: {target}")
        elif old_hash is not None:
            raise SystemExit(f"Expected existing historical file: {target}")
        data = subprocess.check_output(["git", "cat-file", "blob", object_id], cwd=ROOT)
        if sha256(data) != final_hash:
            raise SystemExit(f"Git blob hash mismatch: {relative}")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        print("Restored blob:", target.relative_to(ROOT))


if __name__ == "__main__":
    main()
