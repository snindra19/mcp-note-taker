"""Flask app for the Smart Note Taker: serves the page and the notes API."""

import os

from flask import Flask, jsonify, render_template, request

import notes_store

MAX_TITLE_LENGTH = 200
MAX_BODY_LENGTH = 20000

app = Flask(__name__)


def validate_note_input(data: object) -> tuple[str, str, str | None]:
    """Check a note request; return (title, body, error message or None)."""
    if not isinstance(data, dict):
        return "", "", "Request body must be a JSON object."

    title = data.get("title", "")
    body = data.get("body", "")

    if not isinstance(title, str) or not isinstance(body, str):
        return "", "", "Title and body must be text."

    title = title.strip()
    if not title:
        return "", "", "Title is required."
    if len(title) > MAX_TITLE_LENGTH:
        return "", "", f"Title must be at most {MAX_TITLE_LENGTH} characters."
    if len(body) > MAX_BODY_LENGTH:
        return "", "", f"Body must be at most {MAX_BODY_LENGTH} characters."

    return title, body, None


@app.route("/")
def index():
    """Render the single page of the app."""
    return render_template(
        "index.html",
        max_title_length=MAX_TITLE_LENGTH,
        max_body_length=MAX_BODY_LENGTH,
    )


@app.route("/api/notes", methods=["GET"])
def list_notes():
    """Return every note."""
    return jsonify(notes_store.load_notes())


@app.route("/api/notes", methods=["POST"])
def create_note():
    """Validate the request and create a note."""
    title, body, error = validate_note_input(request.get_json(silent=True))
    if error:
        return jsonify({"error": error}), 400

    new_note = notes_store.create_note(title, body)
    return jsonify(new_note), 201


@app.route("/api/notes/<note_id>", methods=["PUT"])
def update_note(note_id: str):
    """Validate the request and update an existing note."""
    title, body, error = validate_note_input(request.get_json(silent=True))
    if error:
        return jsonify({"error": error}), 400

    updated_note = notes_store.update_note(note_id, title, body)
    if updated_note is None:
        return jsonify({"error": "Note not found."}), 404
    return jsonify(updated_note)


@app.route("/api/notes/<note_id>", methods=["DELETE"])
def delete_note(note_id: str):
    """Delete a note."""
    was_deleted = notes_store.delete_note(note_id)
    if not was_deleted:
        return jsonify({"error": "Note not found."}), 404
    return "", 204


if __name__ == "__main__":
    # Debug stays off unless FLASK_DEBUG=1 is set explicitly.
    debug_enabled = os.getenv("FLASK_DEBUG") == "1"
    app.run(host="127.0.0.1", port=5000, debug=debug_enabled)
