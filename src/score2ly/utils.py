from pathlib import Path


def relative(path: Path, base: Path) -> Path:
    return path.resolve().relative_to(base.resolve(), walk_up=True)
