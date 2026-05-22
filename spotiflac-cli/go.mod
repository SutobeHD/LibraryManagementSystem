module spotiflac-cli

go 1.26

// The SpotiFLAC v7 download engine. Its module path (github.com/afkarxyz/
// SpotiFLAC) does not match any fetchable repo URL, so it is vendored under
// spotiflac-src/ and wired in with a local replace directive.
require github.com/afkarxyz/SpotiFLAC v0.0.0

require (
	github.com/bogem/id3v2/v2 v2.1.4 // indirect
	github.com/boombuler/barcode v1.0.1-0.20190219062509-6c824513bacc // indirect
	github.com/go-flac/flacpicture v0.3.0 // indirect
	github.com/go-flac/flacvorbis v0.2.0 // indirect
	github.com/go-flac/go-flac v1.0.0 // indirect
	github.com/leaanthony/slicer v1.6.0 // indirect
	github.com/leaanthony/u v1.1.1 // indirect
	github.com/pquerna/otp v1.5.0 // indirect
	github.com/ulikunitz/xz v0.5.15 // indirect
	github.com/wailsapp/wails/v2 v2.12.0 // indirect
	go.etcd.io/bbolt v1.4.3 // indirect
	golang.org/x/image v0.12.0 // indirect
	golang.org/x/sys v0.38.0 // indirect
	golang.org/x/text v0.31.0 // indirect
)

replace github.com/afkarxyz/SpotiFLAC => ./spotiflac-src
