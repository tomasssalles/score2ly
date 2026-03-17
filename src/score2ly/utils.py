from pathlib import Path


def relative(path: Path, base: Path) -> Path:
    return path.absolute().relative_to(base.absolute(), walk_up=True)
