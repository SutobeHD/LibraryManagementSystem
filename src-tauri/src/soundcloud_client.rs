// soundcloud_client.rs
// SoundCloud OAuth 2.1 + PKCE Client for RB_Editor_Pro
// This module handles authentication, track searching, and playlist creation.
//
// Error type alias for convenience — uses Send + Sync so errors can cross
// thread boundaries (required by tokio::task::spawn_blocking).


use base64::engine::general_purpose::URL_SAFE_NO_PAD;
use base64::Engine;
use rand::RngCore;
use reqwest::Client;
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::io::{BufRead, BufReader, Write};
use std::net::TcpListener;
use url::Url;
use tauri::Emitter;

/// Convenience error type – Send + Sync so it can cross thread boundaries
/// (required by `tokio::task::spawn_blocking`).
type ScError = Box<dyn std::error::Error + Send + Sync>;

// ---------------------------------------------------------------------------
// Configuration
// ---------------------------------------------------------------------------
// SECURITY: Credentials are loaded from the user's environment at runtime.
// They never live in source code. Each user/tester registers their own
// SoundCloud app and provides their own values via .env (see .env.example).
//
// On a fresh checkout with no .env, the helpers below return Err and the
// auth flow refuses to start — we never silently fall back to a baked-in
// credential.
fn get_client_id() -> Result<String, String> {
    std::env::var("SOUNDCLOUD_CLIENT_ID").map_err(|_| {
        "SOUNDCLOUD_CLIENT_ID is not set. Copy .env.example to .env and \
         fill in your own SoundCloud app credentials."
            .to_string()
    })
}

fn get_client_secret() -> Result<String, String> {
    std::env::var("SOUNDCLOUD_CLIENT_SECRET").map_err(|_| {
        "SOUNDCLOUD_CLIENT_SECRET is not set. Copy .env.example to .env and \
         fill in your own SoundCloud app credentials."
            .to_string()
    })
}

// Localhost callback port. Override with SOUNDCLOUD_REDIRECT_URI if you
// registered a different redirect on your SoundCloud app.
fn get_redirect_uri() -> String {
    std::env::var("SOUNDCLOUD_REDIRECT_URI")
        .unwrap_or_else(|_| "http://127.0.0.1:5001/callback".to_string())
}
const AUTH_URL: &str = "https://secure.soundcloud.com/authorize";
const TOKEN_URL: &str = "https://secure.soundcloud.com/oauth/token";
const API_BASE: &str = "https://api.soundcloud.com";

// ---------------------------------------------------------------------------
// Data types
// ---------------------------------------------------------------------------

/// Represents a track to be searched on SoundCloud.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Track {
    pub artist: String,
    pub title: String,
    pub duration_ms: u64,
}

/// Response from the SoundCloud token endpoint.
#[derive(Debug, Deserialize)]
struct TokenResponse {
    access_token: String,
    #[allow(dead_code)]
    token_type: String,
    #[allow(dead_code)]
    expires_in: Option<u64>,
    #[allow(dead_code)]
    refresh_token: Option<String>,
}

/// A single track item returned by the SoundCloud search API.
#[derive(Debug, Deserialize)]
struct SearchResultItem {
    id: u64,
    duration: u64,
    title: Option<String>,
}

/// Request body for creating a SoundCloud playlist.
#[derive(Debug, Serialize)]
struct CreatePlaylistRequest {
    playlist: PlaylistData,
}

#[derive(Debug, Serialize)]
struct PlaylistData {
    pub title: String,
    pub sharing: String,
    pub tracks: Vec<TrackRef>,
}

#[derive(Debug, Serialize)]
struct TrackRef {
    pub id: String,
}

// ---------------------------------------------------------------------------
// PKCE helpers
// ---------------------------------------------------------------------------

/// Generates a cryptographically random code verifier (43-128 chars, base64url).
fn generate_code_verifier() -> String {
    let mut buf = [0u8; 96]; // 96 bytes → 128 base64url chars
    rand::rng().fill_bytes(&mut buf);
    URL_SAFE_NO_PAD.encode(buf)
}

/// Derives the code challenge from a code verifier using S256.
fn generate_code_challenge(verifier: &str) -> String {
    let mut hasher = Sha256::new();
    hasher.update(verifier.as_bytes());
    let hash = hasher.finalize();
    URL_SAFE_NO_PAD.encode(hash)
}

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

/// Generates the SoundCloud authorization URL and the associated PKCE code verifier.
///
/// # Returns
/// A tuple `(authorization_url, code_verifier)`.
/// The caller must store `code_verifier` and pass it to `exchange_code_for_token` later.
pub fn get_auth_url() -> Result<(String, String), String> {
    let cid = get_client_id()?;
    if cid.is_empty() {
        return Err(
            "SOUNDCLOUD_CLIENT_ID is empty. Copy .env.example to .env and \
             register your own SoundCloud app at https://soundcloud.com/you/apps."
                .to_string(),
        );
    }

    let redirect_uri = get_redirect_uri();
    let code_verifier = generate_code_verifier();
    let code_challenge = generate_code_challenge(&code_verifier);
    let state = generate_code_verifier()[..16].to_string(); // Random state string

    let mut url = Url::parse(AUTH_URL).expect("Invalid AUTH_URL constant");
    url.query_pairs_mut()
        .append_pair("response_type", "code")
        .append_pair("client_id", &cid)
        .append_pair("redirect_uri", &redirect_uri)
        .append_pair("code_challenge", &code_challenge)
        .append_pair("code_challenge_method", "S256")
        .append_pair("state", &state);

    let final_url = url.to_string();
    println!("[SoundCloud] Auth URL generated (state: {})", state);
    
    Ok((final_url, code_verifier))
}

/// Exchanges an authorization code for an access token using the PKCE code verifier.
///
/// # Arguments
/// * `code` – The authorization code received in the callback.
/// * `code_verifier` – The PKCE code verifier generated alongside the auth URL.
///
/// # Returns
/// The access token string on success.
pub async fn exchange_code_for_token(
    code: &str,
    code_verifier: &str,
) -> Result<String, ScError> {
    let client = Client::new();
    let cid = get_client_id().map_err(|e| -> ScError { e.into() })?;
    let csec = get_client_secret().map_err(|e| -> ScError { e.into() })?;
    let redirect_uri = get_redirect_uri();

    let params = [
        ("grant_type", "authorization_code"),
        ("client_id", &cid),
        ("client_secret", &csec),
        ("redirect_uri", &redirect_uri),
        ("code", code),
        ("code_verifier", code_verifier),
    ];

    let resp = client
        .post(TOKEN_URL)
        .form(&params)
        .send()
        .await?;

    if !resp.status().is_success() {
        let status = resp.status();
        let body = resp.text().await.unwrap_or_default();
        return Err(format!("Token exchange failed ({}): {}", status, body).into());
    }

    let token_resp: TokenResponse = resp.json().await?;
    Ok(token_resp.access_token)
}

/// Searches for a single track on SoundCloud by artist and title.
///
/// # Returns
/// `Some(track_id)` if a match is found, `None` otherwise.
pub async fn search_track(
    token: &str,
    query: &str,
    target_duration_ms: u64,
) -> Result<Option<u64>, ScError> {
    let client = Client::new();

    let url = format!("{}/tracks", API_BASE);
    let resp = client
        .get(&url)
        .query(&[("q", query), ("limit", "10")])
        .header("Authorization", format!("OAuth {}", token))
        .send()
        .await?;

    if !resp.status().is_success() {
        let status = resp.status();
        let body = resp.text().await.unwrap_or_default();
        return Err(format!("Track search failed ({}): {}", status, body).into());
    }

    let results: Vec<SearchResultItem> = resp.json().await?;
    
    // Find the best match by duration
    let mut best_match: Option<(u64, u64)> = None; // (id, abs_diff)
    let threshold_ms = 10000; // 10 seconds

    for item in results {
        let diff = if item.duration > target_duration_ms {
            item.duration - target_duration_ms
        } else {
            target_duration_ms - item.duration
        };

        if diff <= threshold_ms {
            match best_match {
                None => best_match = Some((item.id, diff)),
                Some((_, best_diff)) if diff < best_diff => best_match = Some((item.id, diff)),
                _ => {}
            }
        }
    }

    Ok(best_match.map(|(id, _)| id))
}

/// Result of the export operation
#[derive(Debug, Serialize)]
pub struct ExportResult {
    pub success_count: usize,
    pub failed_tracks: Vec<String>,
}

/// Searches for each track sequentially (to avoid rate-limiting) and creates
/// a SoundCloud playlist with the found tracks.
///
/// Tracks that cannot be found are silently skipped (a warning is printed).
pub async fn search_and_create_playlist(
    token: &str,
    playlist_name: &str,
    tracks: Vec<Track>,
    app_handle: Option<tauri::AppHandle>,
) -> Result<ExportResult, ScError> {
    let mut found_ids: Vec<u64> = Vec::new();
    let mut failed_tracks: Vec<String> = Vec::new();

    // Search sequentially to respect SoundCloud rate limits
    for (i, track) in tracks.iter().enumerate() {
        let query = format!("{} {}", track.artist, track.title);
        let progress_msg = format!("Searching ({}/{}): {}", i + 1, tracks.len(), query);
        println!("[SoundCloud] {}", progress_msg);
        
        // Emit progress event
        if let Some(ref app) = app_handle {
            let _ = app.emit("sc-export-progress", serde_json::json!({
                "stage": "searching",
                "current": i + 1,
                "total": tracks.len(),
                "message": progress_msg,
                "trackName": format!("{} - {}", track.artist, track.title)
            }));
        }

        match search_track(token, &query, track.duration_ms).await {
            Ok(Some(id)) => {
                println!("[SoundCloud]   ✓ Found track ID {}", id);
                found_ids.push(id);
            }
            Ok(None) => {
                println!("[SoundCloud]   ✗ Not found, skipping.");
                failed_tracks.push(format!("{} - {}", track.artist, track.title));
            }
            Err(e) => {
                println!("[SoundCloud]   ✗ Error: {}, skipping.", e);
                failed_tracks.push(format!("{} - {} (Error)", track.artist, track.title));
            }
        }

        // Small delay between requests to be extra safe with rate limits
        tokio::time::sleep(std::time::Duration::from_millis(300)).await;
    }

    if found_ids.is_empty() {
        return Err("No tracks were found on SoundCloud.".into());
    }

    let create_msg = format!("Creating playlist '{}' with {} tracks...", playlist_name, found_ids.len());
    println!("[SoundCloud] {}", create_msg);
    
    // Emit progress event for playlist creation
    if let Some(ref app) = app_handle {
        let _ = app.emit("sc-export-progress", serde_json::json!({
            "stage": "creating",
            "message": create_msg,
            "trackCount": found_ids.len()
        }));
    }

    // Build request body: Wrapper + Objects with String IDs
    let body = CreatePlaylistRequest {
        playlist: PlaylistData {
            title: playlist_name.to_string(),
            sharing: "private".to_string(),
            tracks: found_ids
                .iter()
                .map(|&id| TrackRef { id: id.to_string() })
                .collect(),
        },
    };

    let client = Client::builder()
        .user_agent("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
        .build()?;
        
    let url = format!("{}/playlists", API_BASE);
    let resp = client
        .post(&url)
        .header("Authorization", format!("OAuth {}", token))
        .header("Content-Type", "application/json") // Explicitly set it just in case
        .json(&body)
        .send()
        .await?;

    if !resp.status().is_success() {
        let status = resp.status();
        let body_text = resp.text().await.unwrap_or_default();
        return Err(format!("Playlist creation failed ({}): {}", status, body_text).into());
    }

    println!("[SoundCloud] ✓ Playlist '{}' created successfully!", playlist_name);
    Ok(ExportResult {
        success_count: found_ids.len(),
        failed_tracks,
    })
}

// ---------------------------------------------------------------------------
// Local callback listener (waits for the OAuth redirect)
// ---------------------------------------------------------------------------

/// Starts a temporary HTTP server on 127.0.0.1:5001, waits for the OAuth
/// callback, extracts the `code` query parameter, and returns it.
pub fn wait_for_callback() -> Result<String, ScError> {
    // Bind to the same port the redirect URI advertises. We parse it from the
    // env-driven URL so a custom SOUNDCLOUD_REDIRECT_URI keeps server + URL
    // in sync.
    let redirect = get_redirect_uri();
    let port = Url::parse(&redirect)
        .ok()
        .and_then(|u| u.port())
        .unwrap_or(5001);
    let bind_addr = format!("127.0.0.1:{}", port);
    let listener = TcpListener::bind(&bind_addr)?;
    println!("[SoundCloud] Waiting for OAuth callback on {}...", redirect);

    // Accept only the first connection
    let (mut stream, _) = listener.accept()?;

    let mut reader = BufReader::new(stream.try_clone()?);
    let mut request_line = String::new();
    reader.read_line(&mut request_line)?;

    // Parse the code from e.g. "GET /callback?code=abc123 HTTP/1.1"
    let code = request_line
        .split_whitespace()
        .nth(1) // "/callback?code=abc123"
        .and_then(|path| Url::parse(&format!("http://localhost{}", path)).ok())
        .and_then(|url| {
            url.query_pairs()
                .find(|(k, _)| k == "code")
                .map(|(_, v)| v.to_string())
        })
        .ok_or_else(|| -> ScError { "No 'code' parameter found in the callback URL".into() })?;

    // Friendly callback page. We send Content-Length in BYTES (not chars) and
    // declare charset=utf-8 so the checkmark glyph renders correctly across
    // browsers — without the charset declaration, the browser falls back to
    // its locale encoding (often Windows-1252 / ISO-8859-1) and the multibyte
    // UTF-8 sequence gets mangled (e.g. "✓" → "âœ"").
    let response_body = r#"<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Crate Sync</title>
  <style>
    body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif;
           text-align: center; padding: 80px 20px; background: #0a0e17; color: #fff;
           margin: 0; min-height: 100vh; box-sizing: border-box; }
    .card { max-width: 460px; margin: 0 auto; padding: 48px 32px; border-radius: 16px;
            background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.08); }
    h1 { color: #f59e0b; margin: 0 0 16px 0; font-size: 28px; font-weight: 600; }
    p { color: #94a3b8; line-height: 1.6; margin: 0; }
    .check { font-size: 48px; margin-bottom: 24px; }
  </style>
</head>
<body>
  <div class="card">
    <div class="check">✓</div>
    <h1>Authorisation Successful</h1>
    <p>You can close this tab and return to the app.</p>
  </div>
</body>
</html>"#;
    let response = format!(
        "HTTP/1.1 200 OK\r\nContent-Type: text/html; charset=utf-8\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{}",
        response_body.as_bytes().len(),
        response_body
    );
    stream.write_all(response.as_bytes())?;

    println!("[SoundCloud] ✓ Received authorization code.");
    Ok(code)
}

