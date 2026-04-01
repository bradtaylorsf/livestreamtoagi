from pathlib import Path

REQUIRED_DIRS = ["agents", "core", "tools", "frontend", "website"]


def test_directories_exist():
    root = Path(__file__).parent.parent.parent
    for d in REQUIRED_DIRS:
        assert (root / d).is_dir(), f"Missing directory: {d}"
