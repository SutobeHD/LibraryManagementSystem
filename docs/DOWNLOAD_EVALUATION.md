# 📥 SOUNDCLOUD INTEGRATION

Evaluation and documentation of SoundCloud download and sync capabilities in LibraryManagementSystem.

## 1. Current Implementation

### Overview
- **OAuth 2.1 + PKCE** — Official authentication via Tauri OAuth handler in `src-tauri/src/soundcloud_client.rs`
- **Track Matching** — Fuzzy title/artist matching with ISRC fallback in `app/soundcloud_api.py`
- **Download** — Two-stage acquisition in `app/soundcloud_downloader.py`:
  1. Official `/tracks/{id}/download` endpoint when `downloadable=true`
  2. Fallback to v2 media transcodings (same streams the web player uses)
- **Legal Gates:**
  - Skip preview-only tracks (duration < 15s)
  - Honor 401/403 responses (user/DRM restrictions)
  - Respect uploader's `downloadable` flag
- **Dedup** — Registry via SHA-256 content hash in `app/download_registry.py`
- **Analysis** — Auto-analyze via madmom RNN beats + essentia key detection

### Technical Details
- Rate limiting: Exponential backoff with jitter for 429/503 responses
- Network errors: Graceful retry logic with user feedback
- File organization: Auto-organize into artist/track structure
- Metadata: Post-download tag write via lofty (MP3/FLAC/ALAC support)

## 2. Sync Features

### What's Supported
- **Playlist Sync** — SoundCloud → Rekordbox with fuzzy track matching
- **Metadata Sync** — Pull track metadata (BPM, key, artist) from SoundCloud  
- **Play Count Sync** — Bi-directional sync of play counts between PC and USB
- **Analysis Integration** — Tracks auto-analyzed upon download with beatgrid/key data written to Rekordbox DB

## 3. Limitations & Edge Cases

### Known Limitations
- **Rate Limiting:** SoundCloud V2 API heavily rate-limits. 429 responses are retried with backoff.
- **Authentication:** OAuth tokens can expire. Re-authentication required when 401/403 received.
- **Preview vs Downloadable:** Some tracks are preview-only (no official download link). These are skipped in batch operations.
- **Regional Restrictions:** Some content is geo-blocked; download will fail with 403.

## 4. File Organization

Downloaded tracks are organized into:
```
Music/
  SoundCloud Downloads/
    [Artist Name]/
      [Track Title].mp3
```

Registry prevents re-downloading via SHA-256 content hash matching.
