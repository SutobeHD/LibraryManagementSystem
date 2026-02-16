import json
import os
from pathlib import Path

DATA_FILE = Path("app_data.json")

class SidecarStorage:
    def __init__(self):
        self.data = self._load()

    def _load(self):
        if not DATA_FILE.exists():
            return {"artists": {}}
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            return {"artists": {}}

    def _save(self):
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(self.data, f, indent=2)

    def get_artist_link(self, artist_name: str):
        return self.data.get("artists", {}).get(artist_name, {}).get("soundcloud", "")

    def set_artist_link(self, artist_name: str, link: str):
        if "artists" not in self.data: self.data["artists"] = {}
        if artist_name not in self.data["artists"]: self.data["artists"][artist_name] = {}
        self.data["artists"][artist_name]["soundcloud"] = link
        self._save()

storage = SidecarStorage()
