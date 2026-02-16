import xml.etree.ElementTree as ET
from pathlib import Path
from datetime import datetime

class RekordboxXML:
    @staticmethod
    def generate_for_track(track_data: dict, output_path: Path):
        root = ET.Element("DJ_PLAYLISTS", Version="1.0.0")
        collection = ET.SubElement(root, "COLLECTION", Entries="1")
        track = ET.SubElement(collection, "TRACK")
        track.set("TrackID", "1")
        track.set("Name", track_data.get("filename", "Unknown"))
        track.set("Artist", track_data.get("artist", "Unknown Artist"))
        
        abs_path = str(Path(track_data["path"]).absolute()).replace("\\", "/")
        location = f"file://localhost/{abs_path}"
        track.set("Location", location)
        track.set("Kind", "WAV File")
        track.set("DateAdded", datetime.now().strftime("%Y-%m-%d"))

        tree = ET.ElementTree(root)
        ET.indent(tree, space="  ", level=0)
        xml_out = output_path.with_suffix(".xml")
        tree.write(xml_out, encoding="utf-8", xml_declaration=True)
        return str(xml_out)
