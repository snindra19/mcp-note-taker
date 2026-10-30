"""Flask app for the Smart Note Taker: serves the page and the notes API."""

import os

from flask import Flask, jsonify, render_template, request

import link_safety
import mcp_client
import notes_store
import suggestions

MAX_TITLE_LENGTH = 200
MAX_BODY_LENGTH = 20000
MAX_CITY_LENGTH = 100
LINK_TEXT_LENGTH = 500

# The status code for each weather or client code; any other code is a 502.
STATUS_FOR_CODE = {
    "missing_city": 400,
    "invalid_date": 400,
    "date_out_of_range": 400,
    "city_not_found": 404,
    "rate_limited": 429,
    "timeout": 504,
    "server_timeout": 504,
    "server_start_timeout": 504,
}

# Client codes that mean a server took too long, for link requests.
TIMEOUT_CODES = ("server_timeout", "server_start_timeout")

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
        max_city_length=MAX_CITY_LENGTH,
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


@app.route("/api/enhance/weather", methods=["POST"])
def enhance_weather():
    """Get current weather, or a forecast if a date is given, from the weather server."""
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "Request body must be a JSON object."}), 400

    city = data.get("city", "")
    date = data.get("date") or ""
    if not isinstance(city, str) or not isinstance(date, str):
        return jsonify({"error": "City and date must be text."}), 400

    city = city.strip()
    date = date.strip()
    if not city:
        return jsonify({"error": "City is required."}), 400
    if len(city) > MAX_CITY_LENGTH:
        return jsonify({"error": f"City must be at most {MAX_CITY_LENGTH} characters."}), 400

    if date:
        text, error = mcp_client.call_tool("weather", "get_forecast", {"city": city, "date": date})
        label = f"{city} on {date}"
    else:
        text, error = mcp_client.call_tool("weather", "get_current_weather", {"city": city})
        label = city

    # A code means there's no weather to insert, including for an out-of-range
    # date, so the message is returned as an error and never reaches the preview.
    code, message = mcp_client.split_message_code(error or text)
    if code:
        return jsonify({"error": message}), STATUS_FOR_CODE.get(code, 502)
    if error:
        return jsonify({"error": error}), 502

    return jsonify({"source": "weather", "label": label, "text": text})


def fetch_error_response(error: str) -> tuple[str, int]:
    """Turn a fetch failure into a short fixed message and a status code."""
    code, _ = mcp_client.split_message_code(error)
    if code in TIMEOUT_CODES:
        return "The link took too long to fetch.", 504

    # mcp-server-fetch is third-party and has no codes, so its text is matched
    # here. That text can be long and include page or request details, so it
    # only picks one of these fixed messages and is never shown.
    if "autonomous fetching" in error:
        return "This site doesn't allow automated fetching.", 403
    if "not a public address" in error:
        return link_safety.REFUSED_MESSAGE, 400
    return "Could not fetch that link.", 502


def extract_page_text(fetched_text: str) -> str:
    """Remove the header lines the fetch server puts before the page text."""
    lines = fetched_text.split("\n")

    # Non-HTML pages get a content type line before the "Contents of" line.
    if lines[0].startswith("Content type "):
        lines = lines[1:]
    if lines and lines[0].startswith("Contents of "):
        lines = lines[1:]

    page_text = "\n".join(lines).strip()
    # The server reports a page with no content using an <error> tag.
    if page_text.startswith("<error>"):
        return ""
    return page_text


def trim_text(text: str, max_length: int) -> str:
    """Shorten text to about max_length characters, ending on a whole word."""
    if len(text) <= max_length:
        return text

    trimmed_text = text[:max_length]
    last_space = trimmed_text.rfind(" ")
    # Only cut at a space if that keeps most of the text.
    if last_space > max_length // 2:
        trimmed_text = trimmed_text[:last_space]
    return trimmed_text.rstrip() + "..."


@app.route("/api/enhance/link", methods=["POST"])
def enhance_link():
    """Check a link, get its content from the fetch server and trim it."""
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "Request body must be a JSON object."}), 400

    url = data.get("url", "")
    if not isinstance(url, str):
        return jsonify({"error": "The link must be text."}), 400

    url = url.strip()
    if not url:
        return jsonify({"error": "A link is required."}), 400

    # Nothing is sent to the fetch server unless the link passes this check.
    link_error = link_safety.check_link(url)
    if link_error:
        return jsonify({"error": link_error}), 400

    fetched_text, error = mcp_client.call_tool("fetch", "fetch", {"url": url})
    if error:
        message, status = fetch_error_response(error)
        return jsonify({"error": message}), status

    page_text = extract_page_text(fetched_text)
    if not page_text:
        return jsonify({"error": "That link has no readable text."}), 502

    return jsonify({"source": "link", "label": url, "text": trim_text(page_text, LINK_TEXT_LENGTH)})


@app.route("/api/suggestions", methods=["POST"])
def get_suggestions():
    """Return suggestions for the given text; this never calls an MCP server."""
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "Request body must be a JSON object."}), 400

    text = data.get("text", "")
    dismissed_ids = data.get("dismissed", [])
    if not isinstance(text, str):
        return jsonify({"error": "Text must be text."}), 400
    if len(text) > MAX_BODY_LENGTH:
        return jsonify({"error": f"Text must be at most {MAX_BODY_LENGTH} characters."}), 400
    if not isinstance(dismissed_ids, list):
        return jsonify({"error": "Dismissed must be a list."}), 400

    # Check each dismissed id, because they come from the browser's storage.
    for dismissed_id in dismissed_ids:
        if not isinstance(dismissed_id, str):
            return jsonify({"error": "Dismissed must be a list of text."}), 400

    return jsonify({"suggestions": suggestions.build_suggestions(text, dismissed_ids=dismissed_ids)})


@app.errorhandler(500)
def handle_server_error(error: Exception):
    """Return a short message for unexpected failures, never a stack trace."""
    return jsonify({"error": "Something went wrong on the server."}), 500


if __name__ == "__main__":
    # Debug stays off unless FLASK_DEBUG=1 is set explicitly.
    debug_enabled = os.getenv("FLASK_DEBUG") == "1"
    # By default app.run loads .env into this process. Only the weather server
    # may read the API key, so that is turned off.
    app.run(host="127.0.0.1", port=5000, debug=debug_enabled, load_dotenv=False)
