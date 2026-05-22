// Command spotiflac-cli is a headless wrapper around the SpotiFLAC v7 backend
// download engine. Given a Spotify track ID and a service (Tidal, Qobuz or
// Amazon Music) it downloads one lossless track and prints a JSON result on
// stdout.
//
// It exists because the real SpotiFLAC (github.com/spotbye/SpotiFLAC, v7.x) is
// a Wails desktop app, not a library — and the similarly named PyPI package
// "SpotiFLAC" (0.x) is an abandoned, non-functional predecessor. The Music
// Library Manager's Python downloader subprocesses this binary instead; see
// app/downloader/providers/spotiflac.py.
//
// Backend state (history / ISRC cache / provider priority DBs, config) lives
// under ~/.spotiflac/ — the CLI is safe to run from any working directory.
package main

import (
	"encoding/json"
	"flag"
	"fmt"
	"os"
	"strings"

	"github.com/afkarxyz/SpotiFLAC/backend"
)

// result is the JSON object printed on stdout — the only thing the Python
// caller parses. Backend logs / diagnostics go to stderr.
type result struct {
	Success bool   `json:"success"`
	Service string `json:"service"`
	File    string `json:"file,omitempty"`
	Error   string `json:"error,omitempty"`
}

func emit(r result) {
	b, _ := json.Marshal(r)
	fmt.Fprintln(os.Stdout, string(b))
}

func main() {
	os.Exit(run())
}

func run() (code int) {
	service := flag.String("service", "", "tidal | qobuz | amazon")
	spotifyID := flag.String("spotify-id", "", "Spotify track ID (22-char base62)")
	outDir := flag.String("out", ".", "output directory")
	quality := flag.String("quality", "", "service quality (default: best available)")
	tidalAPI := flag.String("tidal-api", "", "Tidal API instance URL — required for --service tidal")
	title := flag.String("title", "", "track title (for filename + tags)")
	artist := flag.String("artist", "", "track artist (for filename + tags)")
	album := flag.String("album", "", "album name (for tags)")
	flag.Parse()

	if *service == "" || *spotifyID == "" {
		emit(result{Success: false, Service: *service, Error: "missing --service or --spotify-id"})
		return 2
	}

	// A SpotiFLAC backend call can panic (reverse-engineered mirror code) —
	// never let that escape as a bare crash; emit a JSON failure instead.
	defer func() {
		if rec := recover(); rec != nil {
			emit(result{Success: false, Service: *service, Error: fmt.Sprintf("panic: %v", rec)})
			code = 1
		}
	}()

	// Backend state init — mirrors SpotiFLAC's app.startup().
	backend.InitHistoryDB("SpotiFLAC")
	backend.InitISRCCacheDB()
	backend.InitProviderPriorityDB()
	backend.CleanupLegacyTidalPublicAPIState()
	backend.SanitizePersistedConfigSettings()
	defer backend.CloseHistoryDB()
	defer backend.CloseISRCCacheDB()
	defer backend.CloseProviderPriorityDB()

	spotifyURL := "https://open.spotify.com/track/" + *spotifyID
	const fnFormat = "title-artist"
	const sep = ", "

	var filename string
	var err error

	switch *service {
	case "amazon":
		q := *quality
		if q == "" {
			q = "LOSSLESS"
		}
		filename, err = backend.NewAmazonDownloader().DownloadBySpotifyID(
			*spotifyID, *outDir, q, fnFormat, "", "", false, 0,
			*title, *artist, *album, "", "", "", 0, 0, 0, false, 0,
			"", "", "", sep, "", spotifyURL, false, false, false)

	case "tidal":
		if !strings.HasPrefix(strings.TrimSpace(*tidalAPI), "https://") {
			emit(result{Success: false, Service: *service,
				Error: "tidal requires --tidal-api https://..."})
			return 1
		}
		q := *quality
		if q == "" {
			q = "HI_RES_LOSSLESS" // best Tidal tier; backend falls back to LOSSLESS
		}
		filename, err = backend.NewTidalDownloader(*tidalAPI).Download(
			*spotifyID, *outDir, q, fnFormat, false, 0,
			*title, *artist, *album, "", "", false, "", false, 0, 0, 0, 0,
			"", "", "", sep, "", spotifyURL, true, false, false, false)

	case "qobuz":
		isrc, ierr := backend.NewSongLinkClient().GetISRCDirect(*spotifyID)
		if ierr != nil || strings.TrimSpace(isrc) == "" {
			emit(result{Success: false, Service: *service,
				Error: fmt.Sprintf("qobuz: could not resolve ISRC: %v", ierr)})
			return 1
		}
		q := *quality
		if q == "" {
			q = "27" // Hi-Res 24-bit; backend falls back 27 -> 7 -> 6
		}
		filename, err = backend.NewQobuzDownloader().DownloadTrackWithISRC(
			strings.TrimSpace(isrc), *outDir, q, fnFormat, false, 0,
			*title, *artist, *album, "", "", false, "", false, 0, 0, 0, 0,
			"", "", "", sep, spotifyURL, true, false, false, false)

	default:
		emit(result{Success: false, Service: *service, Error: "unknown service: " + *service})
		return 2
	}

	if err != nil {
		emit(result{Success: false, Service: *service, Error: err.Error()})
		return 1
	}

	// The backend prefixes an already-on-disk file with "EXISTS:".
	filename = strings.TrimPrefix(filename, "EXISTS:")
	emit(result{Success: true, Service: *service, File: filename})
	return 0
}
