import tarfile
from pathlib import Path


def extract(archive: str, dest: str) -> None:
    with tarfile.open(archive) as tar:
        tar.extractall(Path(dest))
