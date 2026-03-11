import xml.etree.ElementTree as ET
from pathlib import Path
from datetime import datetime

class RekordboxXML:
    @staticmethod
    def generate(tracks_data: list, output_path: Path):
        """
        Generates a Rekordbox-compatible XML collection.
        tracks_data: list of dicts containing track info, beatGrid, and cues.
        """
        root = ET.Element("DJ_PLAYLISTS", Version="1.0.0")
        collection = ET.SubElement(root, "COLLECTION", Entries=str(len(tracks_data)))
        
        for i, data in enumerate(tracks_data):
            track = ET.SubElement(collection, "TRACK")
            track.set("TrackID", str(i + 1))
            track.set("Name", data.get("Title", data.get("filename", "Unknown")))
            track.set("Artist", data.get("Artist", "Unknown Artist"))
            track.set("Album", data.get("Album", ""))
            track.set("Genre", data.get("Genre", ""))
            track.set("Kind", data.get("Kind", "WAV File"))
            track.set("TotalTime", str(int(data.get("TotalTime", 0))))
            
            abs_path = str(Path(data["path"]).absolute()).replace("\\", "/")
            location = f"file://localhost/{abs_path}"
            track.set("Location", location)
            track.set("DateAdded", datetime.now().strftime("%Y-%m-%d"))
            track.set("AverageBpm", str(data.get("BPM", "120.00")))

            # 1. Beatgrid (TEMPO Tags)
            # Rekordbox XML uses <TEMPO Inizio="..." Bpm="..." Metro="..." Battuta="..." />
            # Support for Dynamic Grids: Use tempoAnchors if available, otherwise fallback to beatGrid
            tempo_anchors = data.get("tempoAnchors")
            if tempo_anchors:
                # DYNAMIC GRID: Export the structural tempo shifts
                for anchor in tempo_anchors:
                    tempo = ET.SubElement(track, "TEMPO")
                    tempo.set("Inizio", str(anchor["time"]))
                    tempo.set("Bpm", str(anchor["bpm"]))
                    tempo.set("Metro", anchor.get("metro", "4/4"))
                    tempo.set("Battuta", str(anchor.get("beat", 1)))
            else:
                # STATIC GRID (Fallback): Export the standard beat markers
                beat_grid = data.get("beatGrid", [])
                for beat in beat_grid:
                    tempo = ET.SubElement(track, "TEMPO")
                    tempo.set("Inizio", str(beat["time"]))
                    tempo.set("Bpm", str(beat["bpm"]))
                    tempo.set("Metro", beat.get("metro", "4/4"))
                    tempo.set("Battuta", str(beat["beat"]))

            # 2. Cues & Markers (POSITION_MARK Tags)
            # Rekordbox XML POSITION_MARK attributes:
            # Type: 0=Cue/HotCue/MemoryCue, 1=FadeIn, 2=FadeOut, 3=Load, 4=Loop
            # Num: -1=MemoryCue/Loop, 0-7=HotCue A-H
            cues = data.get("positionMarks", [])
            
            # Add detected drop as a specific Memory Cue if available
            if "dropTime" in data:
                cues.append({"Name": "DROP", "Type": "0", "Start": str(data["dropTime"]), "Num": "-1"})

            for cue in cues:
                mark = ET.SubElement(track, "POSITION_MARK")
                mark.set("Name", cue.get("Name", ""))
                mark.set("Type", str(cue.get("Type", "0")))
                mark.set("Start", str(cue.get("Start", "0")))
                mark.set("Num", str(cue.get("Num", "-1")))
                
                # Support for Loops (Type 4)
                if str(cue.get("Type")) == "4" and "End" in cue:
                    mark.set("End", str(cue["End"]))
                
                # Colors (Optional in XML but supported)
                if "Red" in cue:
                    mark.set("Red", str(cue.get("Red", 0)))
                    mark.set("Green", str(cue.get("Green", 0)))
                    mark.set("Blue", str(cue.get("Blue", 0)))

        # Playlists (Empty structure to satisfy Rekordbox)
        ET.SubElement(root, "PLAYLISTS").append(ET.Element("NODE", Type="0", Name="ROOT"))

        tree = ET.ElementTree(root)
        ET.indent(tree, space="  ", level=0)
        xml_out = output_path.with_suffix(".xml")
        tree.write(xml_out, encoding="utf-8", xml_declaration=True)
        return str(xml_out)

    @staticmethod
    def generate_for_track(track_data: dict, output_path: Path):
        """Legacy wrapper for single track generation."""
        return RekordboxXML.generate([track_data], output_path)
