import os

DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///local.db")
DATABASE_PASSWORD = os.environ.get("DATABASE_PASSWORD", "")
