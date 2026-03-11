import subprocess
import os
import logging
import threading
import time
import re
from pathlib import Path
from typing import Dict, Optional, Callable
from .config import MUSIC_DIR, TEMP_DIR

logger = logging.getLogger(__name__)

class SoundCloudDownloader:
    def __init__(self):
        self.tasks: Dict[str, Dict] = {}
        self._lock = threading.Lock()

    def _parse_progress(self, line: str, task_id: str):
        """
        Parses scdl output to update progress.
        Example output: [####################] 100%
        """
        # Search for percentages
        match = re.search(r'(\d+)%', line)
        if match:
            percent = int(match.group(1))
            with self._lock:
                if task_id in self.tasks:
                    self.tasks[task_id]['progress'] = percent
                    if "Downloading" in line:
                        self.tasks[task_id]['status'] = "Downloading"

    def download_content(self, url: str, auth_token: Optional[str] = None, callback: Optional[Callable] = None):
        """
        Downloads a track or playlist from SoundCloud.
        """
        task_id = f"scdl_{int(time.time())}"
        
        # Ensure download directory exists
        download_dir = MUSIC_DIR / "SoundCloud"
        download_dir.mkdir(parents=True, exist_ok=True)

        with self._lock:
            self.tasks[task_id] = {
                "id": task_id,
                "url": url,
                "status": "Starting",
                "progress": 0,
                "startTime": time.time(),
                "error": None
            }

        def _run():
            try:
                cmd = ["scdl", "-l", url, "--path", str(download_dir), "--addtimestamp"]
                
                # Priority: Original File
                # Note: scdl defaults to high quality if available, but --only-original forces it
                # We want to TRY original, but fallback if not available.
                # scdl doesn't have a perfect "prefer" but --opus helps for Go+
                cmd.append("--opus")
                
                if auth_token:
                    # Some versions of scdl use credentials file, others take --auth-token
                    # Based on research, passing it via environment or arg is safest.
                    os.environ["SCDL_AUTH_TOKEN"] = auth_token
                    # Some versions might need: cmd.extend(["--auth-token", auth_token])
                
                logger.info(f"Running scdl command: {' '.join(cmd)}")
                
                process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,
                    universal_newlines=True
                )

                if process.stdout:
                    for line in process.stdout:
                        logger.debug(f"scdl: {line.strip()}")
                        self._parse_progress(line, task_id)
                
                process.wait()
                
                if process.returncode == 0:
                    with self._lock:
                        if task_id in self.tasks:
                            self.tasks[task_id]['status'] = "Completed"
                            self.tasks[task_id]['progress'] = 100
                    logger.info(f"SoundCloud download completed: {url}")
                    if callback:
                        callback(task_id, True)
                else:
                    error_msg = f"scdl failed with return code {process.returncode}"
                    with self._lock:
                        if task_id in self.tasks:
                            self.tasks[task_id]['status'] = "Failed"
                            self.tasks[task_id]['error'] = error_msg
                    logger.error(error_msg)
                    if callback:
                        callback(task_id, False)

            except Exception as e:
                with self._lock:
                    if task_id in self.tasks:
                        self.tasks[task_id]['status'] = "Error"
                        self.tasks[task_id]['error'] = str(e)
                logger.error(f"Download thread error: {e}")
                if callback:
                    callback(task_id, False)

        thread = threading.Thread(target=_run, daemon=True)
        thread.start()
        
        return task_id

    def get_task_status(self, task_id: str):
        with self._lock:
            return self.tasks.get(task_id)

sc_downloader = SoundCloudDownloader()
