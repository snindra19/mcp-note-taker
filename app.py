"""Flask app for the Smart Note Taker: serves the page and the notes API."""

import os

from flask import Flask, jsonify, render_template, request

import link_safety
import mcp_client
import notes_store

MAX_TITLE_LENGTH = 200
MAX_BODY_LENGTH = 20000
MAX_CITY_LENGTH = 100
LINK_TEXT_LENGTH = 500

# Weather tool failures start with this. It is repeated here because importing
# weather_server would load the API key into this process.
WEATHER_ERROR_PREFIX = "Weather error: "
NO_FORECAST_PREFIX = "No forecast is available"

# Which status code each kind of weather failure gets; anything else is a 502.
WEATHER_ERROR_STATUSES = (
    ("please enter a city", 400),
    ("the date must be", 400),
    ("city not found", 404),
    ("rate limit", 429),
    ("timed out", 504),
    ("did not answer within", 504),
    ("did not start within", 504),
)

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


def weather_error_status(message: str) -> int:
    """Return the status code for a weather failure message."""
    lowered_message = message.lower()

    # Use the first kind of failure that the message mentions.
    for fragment, status in WEATHER_ERROR_STATUSES:
        if fragment in lowered_message:
            return status
    return 502


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

    if error:
        return jsonify({"error": error}), weather_error_status(error)
    if text.startswith(WEATHER_ERROR_PREFIX):
        return jsonify({"error": text}), weather_error_status(text)
    # There's no weather to insert for an out-of-range date, so don't preview it.
    if text.startswith(NO_FORECAST_PREFIX):
        return jsonify({"error": text}), 400

    return jsonify({"source": "weather", "label": label, "text": text})


def fetch_error_response(error: str) -> tuple[str, int]:
    """Turn a fetch failure into a short fixed message and a status code."""
    # The fetch server's own text can be long and include page or request
    # details, so it is only used to pick one of these messages.
    if "autonomous fetching" in error:
        return "This site doesn't allow automated fetching.", 403
    if "not a public address" in error:
        return link_safety.REFUSED_MESSAGE, 400
    if "did not answer within" in error or "did not start within" in error:
        return "The link took too long to fetch.", 504
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
