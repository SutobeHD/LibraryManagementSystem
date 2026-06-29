import argparse

# Setup logging
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("BatchWorker")


def compute_new_comment(action: str, original: str, find_text: str, replace_text: str) -> str:
    """Pure comment transform for one track — mirrors the four batch actions.

    Returns the new comment string (equal to ``original`` when the action is a
    no-op or unknown). Extracted so the action semantics are unit-testable
    without rbox / a real master.db.
    """
    original = original or ""
    if action == "set":
        return replace_text
    if action == "append":
        if replace_text and replace_text not in original:
            return f"{original} {replace_text}".strip()
        return original
    if action == "remove":
        if find_text:
            return original.replace(find_text, "").strip()
        return original
    if action == "replace":
        if find_text:
            return original.replace(find_text, replace_text).strip()
        return original
    return original


def run_batch_update(db_path, source_id, action, find_text, replace_text):
    from rbox import MasterDb  # lazy: keeps the module importable without rbox

    logger.info(f"Connecting to DB: {db_path}")
    try:
        db = MasterDb(db_path)
    except Exception as e:
        logger.error(f"Failed to connect to DB: {e}")
        return

    # 1. Resolve tracks
    target_ids = []
    if source_id == "LIB":
        tracks = db.get_tracks()
        target_ids = [t.id for t in tracks]
    else:
        try:
            # Need to handle playlist ID types if necessary, but string usually works
            items = db.get_playlist_contents(source_id)
            target_ids = [item.id for item in items]
        except Exception as e:
            logger.error(f"Failed to get playlist contents: {e}")
            return

    logger.info(f"Targeting {len(target_ids)} tracks.")

    count = 0
    for tid in target_ids:
        try:
            item = db.get_content_by_id(int(tid))
            if not item:
                continue

            original_comment = getattr(item, "commnt", "") or ""
            new_comment = compute_new_comment(action, original_comment, find_text, replace_text)

            if new_comment != original_comment:
                item.commnt = new_comment
                db.update_content(item)
                count += 1
        except Exception as e:
            logger.warning(f"Error updating track {tid}: {e}")
            continue

    logger.info(f"Updated {count} tracks.")
    print(f"COUNT:{count}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", required=True)
    parser.add_argument("--source", required=True)
    parser.add_argument("--action", required=True)
    parser.add_argument("--find", default="")
    parser.add_argument("--replace", default="")
    args = parser.parse_args()

    run_batch_update(args.db, args.source, args.action, args.find, args.replace)
