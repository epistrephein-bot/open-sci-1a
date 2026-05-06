import os
import sys
import sqlite3
from pathlib import Path
from dotenv import load_dotenv

# Root directory of the project
ROOT_DIR = Path(__file__).resolve().parent.parent

# Load ENV variables
load_dotenv(ROOT_DIR / ".env")
DATA_PATH = os.environ.get("DATA_PATH")

if not DATA_PATH:
    raise RuntimeError("Missing DATA_PATH environment variable")

# Define paths
DATA_DIR = Path(DATA_PATH)
DB_PATH = DATA_DIR / "oc_index.sqlite3"

omid = sys.argv[1]

conn = sqlite3.connect(DB_PATH)
conn.row_factory = sqlite3.Row

row = conn.execute("SELECT * FROM meta WHERE omid = ?", (omid,)).fetchone()

if row is None:
    print("Not found")
else:
    print(dict(row))

conn.close()
