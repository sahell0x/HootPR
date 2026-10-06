import tarfile
from pathlib import Path


def extract(archive: str, dest: str) -> None:
    root = Path(dest).resolve()
    with tarfile.open(archive) as tar:
        for member in tar.getmembers():
            target = (root / member.name).resolve()
            if root not in target.parents and target != root:
                raise ValueError(f"unsafe path in archive: {member.name}")
        tar.extractall(root)
