import os
from pathlib import Path

REKORDBOX_ROOT = Path(os.environ.get('APPDATA', '')) / "Pioneer" / "rekordbox"
DB_FILENAME = "master.db"
FFMPEG_BIN = "ffmpeg"
BACKUP_DIR = Path("./backups")
EXPORT_DIR = Path("./exports")
LOG_DIR = Path("./logs")
TEMP_DIR = Path("./temp_uploads") # NEU
MUSIC_DIR = Path("./music") # NEU

DB_KEY = os.getenv("REKORDBOX_DB_KEY", "")

BACKUP_DIR.mkdir(exist_ok=True)
EXPORT_DIR.mkdir(exist_ok=True)
LOG_DIR.mkdir(exist_ok=True)
TEMP_DIR.mkdir(exist_ok=True)
MUSIC_DIR.mkdir(exist_ok=True)
