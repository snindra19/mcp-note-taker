"""Load, create, update and delete notes stored in a local JSON file."""

import json
import os
import shutil
import tempfile
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

from templates_config import DEFAULT_TEMPLATE

NOTES_FILE = Path(__file__).resolve().parent / "notes.json"
REQUIRED_NOTE_FIELDS = ("id", "title", "body", "template", "created_at", "updated_at")

# Flask handles requests on several threads, so each read-change-write
# sequence holds this lock to stop two saves from overwriting each other.
# It is reentrant because create, update and delete call load_notes while
# already holding it. Reads hold it too, so one never overlaps a file replace.
notes_lock = threading.RLock()


def current_timestamp() -> str:
    """Return the current UTC time as an ISO 8601 string."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def is_valid_note(note: object) -> bool:
    """Return True if a value loaded from the file is a complete note."""
    if not isinstance(note, dict):
        return False

    # Every required field must be present and be text.
    for field in REQUIRED_NOTE_FIELDS:
        if not isinstance(note.get(field), str):
            return False
    return True


def find_backup_path() -> Path:
    """Return the first unused backup name for a corrupt notes file."""
    backup_path = NOTES_FILE.with_name(NOTES_FILE.name + ".corrupt")

    # Keep any earlier backup by moving on to the next free numbered name.
    backup_number = 1
    while backup_path.exists():
        backup_path = NOTES_FILE.with_name(f"{NOTES_FILE.name}.corrupt.{backup_number}")
        backup_number += 1
    return backup_path


def set_aside_corrupt_file() -> None:
    """Rename an unreadable notes file so the next save can't overwrite it."""
    os.rename(NOTES_FILE, find_backup_path())


def keep_valid_entries(loaded_entries: list) -> list[dict]:
    """Return the complete notes; if any entry is bad, back up the file first."""
    valid_notes = []

    # Separate the complete notes from any bad entries.
    for entry in loaded_entries:
        if is_valid_note(entry):
            valid_notes.append(entry)

    if len(valid_notes) == len(loaded_entries):
        return valid_notes

    # Copy first, so the original stays in place until the backup exists. The
    # rewrite removes the bad entries, so the next load doesn't back up again.
    shutil.copyfile(NOTES_FILE, find_backup_path())
    save_notes(valid_notes)
    return valid_notes


def load_notes() -> list[dict]:
    """Return all notes, handling a missing or damaged file.

    A missing file gives an empty list. An unreadable file is renamed and gives
    an empty list. A list with some bad entries is backed up, and its valid
    entries are kept. Any other failure raises instead, so a later save can't
    overwrite the file.
    """
    with notes_lock:
        try:
            with open(NOTES_FILE, "r", encoding="utf-8") as notes_file:
                loaded_data = json.load(notes_file)
        except FileNotFoundError:
            return []
        except (ValueError, RecursionError):
            # The file is closed by now, which Windows requires for a rename.
            set_aside_corrupt_file()
            return []

        # Valid JSON that isn't a list has no entries to recover.
        if not isinstance(loaded_data, list):
            set_aside_corrupt_file()
            return []
        return keep_valid_entries(loaded_data)


def save_notes(notes: list[dict]) -> None:
    """Write notes to a temp file, then replace the real file in one step."""
    # The temp file must be in the same folder for the replace to be atomic.
    file_descriptor, temp_path = tempfile.mkstemp(
        dir=NOTES_FILE.parent, prefix=".notes-", suffix=".tmp"
    )
    try:
        with os.fdopen(file_descriptor, "w", encoding="utf-8") as temp_file:
            json.dump(notes, temp_file, indent=2, ensure_ascii=False)
            temp_file.flush()
            os.fsync(temp_file.fileno())
        os.replace(temp_path, NOTES_FILE)
    except BaseException:
        # Remove the leftover temp file; the real notes file is untouched.
        if os.path.exists(temp_path):
            os.remove(temp_path)
        raise


def create_note(title: str, body: str, template: str = DEFAULT_TEMPLATE) -> dict:
    """Create a note, save it and return it."""
    timestamp = current_timestamp()
    new_note = {
        "id": uuid.uuid4().hex,
        "title": title,
        "body": body,
        "template": template,
        "created_at": timestamp,
        "updated_at": timestamp,
    }
    with notes_lock:
        notes = load_notes()
        notes.append(new_note)
        save_notes(notes)
    return new_note


def update_note(note_id: str, title: str, body: str) -> dict | None:
    """Update a note's title and body; return it, or None if not found."""
    with notes_lock:
        notes = load_notes()

        # Find the matching note and change it.
        for note in notes:
            if note["id"] == note_id:
                note["title"] = title
                note["body"] = body
                note["updated_at"] = current_timestamp()
                save_notes(notes)
                return note
    return None


def delete_note(note_id: str) -> bool:
    """Delete a note; return True if it existed."""
    with notes_lock:
        notes = load_notes()

        # Copy every note except the one being deleted.
        remaining_notes = []
        for note in notes:
            if note["id"] != note_id:
                remaining_notes.append(note)

        if len(remaining_notes) == len(notes):
            return False
        save_notes(remaining_notes)
    return True
