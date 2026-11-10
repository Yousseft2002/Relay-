from pathlib import Path

UPLOAD_DIR = Path("/srv/uploads")


def list_files():
    return sorted(p.name for p in UPLOAD_DIR.iterdir())


def read_upload(request):
    """GET /download?name=<file>"""
    name = request.args["name"]
    with open(UPLOAD_DIR / name, "rb") as fh:
        return fh.read()
