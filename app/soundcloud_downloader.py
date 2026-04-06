import subprocess
import os
import logging
import threading
import time
import re
import atexit
import tempfile
import shutil
from pathlib import Path
from typing import Dict, Optional, Callable
from .config import MUSIC_DIR

logger = logging.getLogger(__name__)

class SoundCloudDownloader:
    def __init__(self):
        self.tasks: Dict[str, Dict] = {}
        self._lock = threading.Lock()
        self._running_processes = set()
        atexit.register(self.cleanup_processes)

    def cleanup_processes(self):
        """Req 9: Kill zombie processes on application exit."""
        for p in list(self._running_processes):
            try:
                if p.poll() is None:
                    p.terminate()
            except Exception as e:
                logger.error(f"[SC] Failed to terminate zombie process: {e}")

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

    def download_content(self, url: str, auth_token: Optional[str] = None, callback: Optional[Callable] = None, sc_title: Optional[str] = None):
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
                "sc_title": sc_title,
                "status": "Starting",
                "progress": 0,
                "startTime": time.time(),
                "error": None
            }

        def _run():
            try:
                # Req 10: Insecure Temporary Files -> use short-lived secure temp directory
                with tempfile.TemporaryDirectory(prefix="scdl_tmp_") as safe_temp_dir:
                    cmd = ["scdl", "-l", url, "--path", safe_temp_dir, "--addtimestamp"]
                    
                    # Priority: Original File
                    cmd.append("--opus")
                    
                    if auth_token:
                        os.environ["SCDL_AUTH_TOKEN"] = auth_token
                    
                    logger.info(f"Running scdl command: {' '.join(cmd)} in {safe_temp_dir}")
                    
                    process = subprocess.Popen(
                        cmd,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT,
                        text=True,
                        bufsize=1,
                        universal_newlines=True
                    )
                    
                    # Req 9: Track process to avoid zombies
                    self._running_processes.add(process)

                    try:
                        if process.stdout:
                            for line in process.stdout:
                                logger.debug(f"scdl: {line.strip()}")
                                self._parse_progress(line, task_id)
                        
                        process.wait()
                    finally:
                        if process in self._running_processes:
                            self._running_processes.remove(process)
                        if process.poll() is None:
                            logger.warning(f"[SC] Thread exited early, killing leftover process {process.pid}")
                            process.terminate()
                    
                    if process.returncode == 0:
                        downloaded_files = []
                        # Move successfully completed files to the final destination
                        for f in Path(safe_temp_dir).glob("*"):
                            if f.is_file():
                                target = download_dir / f.name
                                shutil.copy(f, target)
                                downloaded_files.append(target)
                                
                        with self._lock:
                            if task_id in self.tasks:
                                self.tasks[task_id]['status'] = "Completed"
                                self.tasks[task_id]['progress'] = 100
                        logger.info(f"SoundCloud download completed: {url}")
                        if callback:
                            callback(task_id, True, downloaded_files)
                    else:
                        error_msg = f"scdl failed with return code {process.returncode}"
                        with self._lock:
                            if task_id in self.tasks:
                                self.tasks[task_id]['status'] = "Failed"
                                self.tasks[task_id]['error'] = error_msg
                        logger.error(error_msg)
                        if callback:
                            callback(task_id, False, [])

            except Exception as e:
                with self._lock:
                    if task_id in self.tasks:
                        self.tasks[task_id]['status'] = "Error"
                        self.tasks[task_id]['error'] = str(e)
                logger.error(f"Download thread error: {e}")
                if callback:
                    callback(task_id, False, [])

        thread = threading.Thread(target=_run, daemon=True)
        thread.start()
        
        return task_id

    def get_task_status(self, task_id: str):
        with self._lock:
            return self.tasks.get(task_id)

sc_downloader = SoundCloudDownloader()
