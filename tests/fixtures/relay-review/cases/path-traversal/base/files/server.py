from pathlib import Path

UPLOAD_DIR = Path("/srv/uploads")


def list_files():
    return sorted(p.name for p in UPLOAD_DIR.iterdir())
