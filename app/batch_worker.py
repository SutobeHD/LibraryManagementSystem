import argparse

# Setup logging
import logging

from rbox import MasterDb

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("BatchWorker")

def run_batch_update(db_path, source_id, action, find_text, replace_text):
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
            if not item: continue

            original_comment = getattr(item, 'commnt', '') or ""
            new_comment = original_comment

            if action == "set":
                new_comment = replace_text
            elif action == "append":
                if replace_text and replace_text not in original_comment:
                    new_comment = f"{original_comment} {replace_text}".strip()
            elif action == "remove":
                if find_text:
                    new_comment = original_comment.replace(find_text, "").strip()
            elif action == "replace":
                if find_text:
                    new_comment = original_comment.replace(find_text, replace_text).strip()

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
