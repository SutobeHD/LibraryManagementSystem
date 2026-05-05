import xml.etree.ElementTree as ET
import xml.dom.minidom as minidom
import os
import time
from typing import Dict, Any, List

def format_time_ms_to_sec(ms: int) -> str:
    """Format milliseconds to seconds with 3 decimal places."""
    return f"{ms / 1000:.3f}"

def format_tempo_int_to_str(tempo: int) -> str:
    """Format Rekordbox integer tempo (BPM*100) to string with 2 decimal places."""
    return f"{tempo / 100:.2f}"

def analysis_to_xml_track(track_id: str, analysis_result: Dict[str, Any], metadata: Dict[str, str]) -> ET.Element:
    """
    Convert an AnalysisEngine result into a Rekordbox XML <TRACK> element.
    """
    track = ET.Element("TRACK")
    
    # Track Metadata (required fields)
    track.set("TrackID", str(track_id))
    track.set("Name", metadata.get("title", os.path.basename(analysis_result.get("file", "Unknown"))))
    track.set("Artist", metadata.get("artist", ""))
    track.set("Composer", "")
    track.set("Album", metadata.get("album", ""))
    track.set("Grouping", "")
    track.set("Genre", metadata.get("genre", ""))
    track.set("Kind", "MP3 File" if analysis_result.get("file", "").lower().endswith(".mp3") else "WAV File")
    track.set("Size", str(os.path.getsize(analysis_result.get("file", "")) if analysis_result.get("file") and os.path.exists(analysis_result.get("file")) else 0))
    track.set("TotalTime", str(int(analysis_result.get("duration", 0))))
    track.set("DiscNumber", "0")
    track.set("TrackNumber", "0")
    track.set("Year", metadata.get("year", ""))
    track.set("AverageBpm", f"{analysis_result.get('bpm', 120.0):.2f}")
    track.set("DateAdded", time.strftime("%Y-%m-%d"))
    track.set("BitRate", "320") # Assumption or pass actual
    track.set("SampleRate", str(analysis_result.get("sample_rate", 44100)))
    track.set("Comments", "Analyzed by LibraryManagementSystem")
    track.set("PlayCount", "0")
    track.set("Rating", "0")
    track.set("Location", f"file://localhost/{analysis_result.get('file', '').replace(os.sep, '/')}")
    track.set("Remixer", "")
    track.set("Tonality", analysis_result.get("key", ""))
    track.set("Label", "")
    track.set("Mix", "")

    # Embed TEMPO (Beatgrid)
    # Rekordbox XML tempo nodes describe *changes* in BPM.
    # We only have 1 global BPM for now from our analysis, so we write a single TEMPO tag.
    bpm_str = f"{analysis_result.get('bpm', 120.0):.2f}"
    
    # We must set the 'Inizio' (Start time of beat 1) to align the grid!
    # Our downbeat_index tells us which beat is beat 1.
    downbeat_idx = analysis_result.get("downbeat_index", 0)
    beats = analysis_result.get("beats", [])
    
    inizio_ms = 0
    if len(beats) > downbeat_idx:
        inizio_ms = beats[downbeat_idx].get("time_ms", 0)
    
    tempo_node = ET.SubElement(track, "TEMPO")
    tempo_node.set("Inizio", format_time_ms_to_sec(inizio_ms))
    tempo_node.set("Bpm", bpm_str)
    tempo_node.set("Metro", "4/4")
    tempo_node.set("Battito", "1") # Beat 1

    # Insert memory cue on the first beat (Inizio)
    cue_node = ET.SubElement(track, "POSITION_MARK")
    cue_node.set("Name", "")
    cue_node.set("Type", "0")  # 0 = memory cue
    cue_node.set("Start", format_time_ms_to_sec(inizio_ms))
    cue_node.set("Num", "-1")

    return track

def create_rekordbox_xml(tracks_xml: List[ET.Element], output_path: str) -> None:
    """
    Wrap track elements in the root DJ_PLAYLISTS Rekordbox XML structure and save.
    """
    root = ET.Element("DJ_PLAYLISTS")
    root.set("Version", "1.0.0")
    
    prod = ET.SubElement(root, "PRODUCT")
    prod.set("Name", "rekordbox")
    prod.set("Version", "6.6.4") # Use a modern version number
    prod.set("Company", "Pioneer DJ")

    collection = ET.SubElement(root, "COLLECTION")
    collection.set("Entries", str(len(tracks_xml)))
    
    for track in tracks_xml:
        collection.append(track)
        
    playlists = ET.SubElement(root, "PLAYLISTS")
    node = ET.SubElement(playlists, "NODE")
    node.set("Type", "0")
    node.set("Name", "ROOT")
    node.set("Count", "0") # We don't export playlists here, just the collection

    # Format XML nicely
    xml_str = ET.tostring(root, 'utf-8')
    parsed = minidom.parseString(xml_str)
    pretty_xml = parsed.toprettyxml(indent="  ")
    
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(pretty_xml)
