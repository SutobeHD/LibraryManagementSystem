import os
import rbox
from pathlib import Path

def find_rekordbox_anlz_root():
    paths = [
        os.path.expandvars(r"%APPDATA%\Pioneer\rekordbox\share\PIONEER\USBANLZ"),
        os.path.expandvars(r"%APPDATA%\Pioneer\rekordbox6\share\PIONEER\USBANLZ")
    ]
    for p in paths:
        if os.path.exists(p):
            return Path(p)
    return None

def inspect_sample_anlz():
    anlz_root = find_rekordbox_anlz_root()
    if not anlz_root:
        print("Rekordbox ANLZ root not found.")
        return

    print(f"ANLZ Root: {anlz_root}")
    
    # Find the first .2EX file we can find
    ex_files = list(anlz_root.glob("**/*.2EX"))
    if not ex_files:
        print("No .2EX files found.")
        return
    
    sample_path = ex_files[0]
    print(f"Inspecting: {sample_path}")
    
    try:
        anlz = rbox.Anlz(str(sample_path))
        
        # 1. 3-Band Waveform
        # get_waveform_3band_detail returns a list of bytes [L, M, H, L, M, H, ...]
        wf_3band = anlz.get_waveform_3band_detail()
        print(f"\n3-Band Waveform Detail Type: {type(wf_3band)}")
        print(f"  Available members: {[m for m in dir(wf_3band) if not m.startswith('__')]}")
        
        # Try to access as bytes if possible, or check for 'data' / 'entries'
        if hasattr(wf_3band, 'data'):
             data = wf_3band.data
             print(f"  Found 'data' attribute (len={len(data)})")
             print(f"  First 12 values: {data[:12]}")
        elif hasattr(wf_3band, 'get_data'):
             data = wf_3band.get_data()
             print(f"  Found 'get_data()' method (len={len(data)})")
             print(f"  First 12 values: {data[:12]}")
        else:
             print("  Could not find directly accessible data field. Trying to iterate.")
             count = 0
             first_few = []
             try:
                 for entry in wf_3band:
                     first_few.append(entry)
                     count += 1
                     if count >= 10: break
                 print(f"  Iterated {count} columns.")
                 dump_path = str(Path(r"<user_dir>\Documents\Appp\RB_Editor_Pro") / "analysis_dump.txt")
                 with open(dump_path, "w") as f:
                     for i, col in enumerate(first_few):
                         h = getattr(col, 'high', 'N/A')
                         m = getattr(col, 'mid', 'N/A')
                         l = getattr(col, 'low', 'N/A')
                         line = f"Col {i}: H={h}, M={m}, L={l}"
                         print(line)
                         f.write(line + "\n")
                 print("Results saved to analysis_dump.txt")
             except Exception as e:
                 print(f"  Iteration failed: {e}")

        # 2. Song Structure
        structure = anlz.get_song_structure()
        print(f"\nSong Structure:")
        if structure:
            for part in structure[:5]: # Show first 5 parts
                print(f"  Part: {part}")
        else:
             print("  None found.")

        # 3. Beatgrid (if in .DAT file, usually in the same folder)
        dat_path = sample_path.with_suffix(".DAT")
        if dat_path.exists():
            print(f"\nInspecting .DAT: {dat_path}")
            anlz_dat = rbox.Anlz(str(dat_path))
            # Note: rbox might not expose beatgrid directly as 'beatgrid'
            # Let's check available methods on 'anlz_dat'
            print(f"  DAT methods: {[m for m in dir(anlz_dat) if not m.startswith('__')]}")
            
    except Exception as e:
        print(f"Error inspecting ANLZ: {e}")

if __name__ == "__main__":
    inspect_sample_anlz()
