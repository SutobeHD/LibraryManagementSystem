import sys
from pathlib import Path
import xml.etree.ElementTree as ET

# Add app to path
sys.path.append(str(Path(__file__).parent.parent))

from app.xml_generator import RekordboxXML

def test_xml_generation():
    print("Testing Rekordbox XML Generation...")
    
    mock_tracks = [
        {
            "Title": "Test Track 1",
            "Artist": "Antigravity",
            "path": "c:/Music/test1.wav",
            "BPM": 124.0,
            "TotalTime": 300,
            "beatGrid": [
                {"time": 1.0, "bpm": 124.0, "beat": 1, "metro": "4/4"},
                {"time": 1.483, "bpm": 124.0, "beat": 2, "metro": "4/4"}
            ],
            "positionMarks": [
                {"Name": "Intro", "Type": "0", "Start": "1.0", "Num": "1"}
            ],
            "dropTime": 45.0
        }
    ]
    
    output_path = Path("test_export.xml")
    RekordboxXML.generate(mock_tracks, output_path)
    
    if not output_path.exists():
        print("FAIL: XML file not generated.")
        return False
        
    # Validate structure
    tree = ET.parse(output_path)
    root = tree.getroot()
    
    if root.tag != "DJ_PLAYLISTS":
        print("FAIL: Root tag is not DJ_PLAYLISTS")
        return False
        
    track = root.find("COLLECTION/TRACK")
    if track is None:
        print("FAIL: No TRACK found in COLLECTION")
        return False
        
    if track.get("Name") != "Test Track 1":
        print("FAIL: Track name mismatch")
        return False
        
    tempo = track.find("TEMPO")
    if tempo is None or tempo.get("Bpm") != "124.0":
        print("FAIL: TEMPO/BPM mismatch")
        return False
        
    marks = track.findall("POSITION_MARK")
    # Should have 2: The manual one and the DROP
    if len(marks) != 2:
        print(f"FAIL: Expected 2 marks, found {len(marks)}")
        return False
        
    print("SUCCESS: XML structure and data verified.")
    return True

if __name__ == "__main__":
    if test_xml_generation():
        sys.exit(0)
    else:
        sys.exit(1)
