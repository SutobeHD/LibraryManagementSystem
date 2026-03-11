use lofty::prelude::*;
use lofty::file::{AudioFile, TaggedFileExt};
use lofty::tag::{Tag, TagExt, ItemKey, TagType};
use lofty::config::WriteOptions;

pub fn copy_metadata(source_path: &str, dest_path: &str) -> Result<(), String> {
    // 1. Read source file tags
    let source_tagged_file = lofty::probe::Probe::open(source_path)
        .map_err(|e| format!("Lofty open error: {}", e))?
        .read()
        .map_err(|e| format!("Lofty read error: {}", e))?;

    let source_tag = source_tagged_file.primary_tag()
        .or_else(|| source_tagged_file.first_tag())
        .ok_or("No tags found in source file")?;

    // 2. Open generated WAV file for tagging
    let mut dest_file = std::fs::OpenOptions::new()
        .read(true)
        .write(true)
        .open(dest_path)
        .map_err(|e| format!("Could not open dest file: {}", e))?;

    // 3. Create a new ID3v2 tag for the WAV
    let mut dest_tag = Tag::new(TagType::Id3v2);

    // 4. Clone key Metadata
    if let Some(artist) = source_tag.artist() {
        dest_tag.insert_text(ItemKey::TrackArtist, artist.into_owned());
    }
    if let Some(title) = source_tag.title() {
        dest_tag.insert_text(ItemKey::TrackTitle, title.into_owned());
    }
    if let Some(album) = source_tag.album() {
        dest_tag.insert_text(ItemKey::AlbumTitle, album.into_owned());
    }

    // 5. Clone existing Cover Art (APIC)
    for picture in source_tag.pictures() {
        dest_tag.push_picture(picture.clone());
        break; // Just take the first cover art
    }

    // 6. Save back to the WAV file
    dest_tag.save_to(&mut dest_file, WriteOptions::default())
        .map_err(|e| format!("Could not save tags to WAV: {}", e))?;

    Ok(())
}
