import logging
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import List, Dict, Optional
from .database import db
from .xml_generator import RekordboxXML

logger = logging.getLogger(__name__)

class RekordboxBridge:
    @staticmethod
    def export_collection(track_ids: List[str], output_path: Path) -> str:
        """Exports selected tracks to a Rekordbox-compatible XML."""
        tracks_to_export = []
        for tid in track_ids:
            track = db.get_track_details(tid)
            if track:
                tracks_to_export.append(track)
        
        if not tracks_to_export:
            raise ValueError("No tracks found for export.")
            
        return RekordboxXML.generate(tracks_to_export, output_path)

    @staticmethod
    def import_library(xml_path: str) -> Dict:
        """Imports data from a Rekordbox XML and updates the local database."""
        results = {"added": 0, "updated": 0, "errors": []}
        try:
            tree = ET.parse(xml_path)
            root = tree.getroot()
            collection = root.find("COLLECTION")
            if collection is None:
                raise ValueError("Invalid Rekordbox XML: No COLLECTION found.")

            for track_el in collection.findall("TRACK"):
                try:
                    # Extract basic info
                    location = track_el.get("Location", "")
                    # Convert file://localhost/C:/... to C:/...
                    clean_path = location.replace("file://localhost/", "").replace("/", "\\")
                    
                    track_data = {
                        "Title": track_el.get("Name"),
                        "Artist": track_el.get("Artist"),
                        "Album": track_el.get("Album"),
                        "BPM": float(track_el.get("AverageBpm", 120)),
                        "path": clean_path,
                        "TotalTime": float(track_el.get("TotalTime", 0)),
                        "beatGrid": [],
                        "positionMarks": []
                    }

                    # Extract Beatgrid
                    for tempo in track_el.findall("TEMPO"):
                        track_data["beatGrid"].append({
                            "time": float(tempo.get("Inizio", 0)),
                            "bpm": float(tempo.get("Bpm", 0)),
                            "beat": int(tempo.get("Battuta", 1)),
                            "metro": tempo.get("Metro", "4/4")
                        })

                    # Extract Cues
                    for mark in track_el.findall("POSITION_MARK"):
                        track_data["positionMarks"].append({
                            "Name": mark.get("Name", ""),
                            "Type": mark.get("Type", "0"),
                            "Start": mark.get("Start", "0"),
                            "Num": mark.get("Num", "-1")
                        })

                    # Update or Add to local DB
                    # We match by path as the primary key for external sync
                    existing_id = None
                    for tid, t in db.tracks.items():
                        if t.get("path") == clean_path:
                            existing_id = tid
                            break
                    
                    if existing_id:
                        db.update_track(existing_id, track_data)
                        results["updated"] += 1
                    else:
                        db.add_track(track_data)
                        results["added"] += 1

                except Exception as e:
                    results["errors"].append(str(e))
            
            db.save()
            return results
        except Exception as e:
            logger.error(f"Import failed: {e}")
            raise
