# Smart Note Taker with MCP

A minimal web app for taking notes, built in cycles.

## Setup

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
```

Then put your OpenWeatherMap key in `.env`.

## How to run

```powershell
python app.py
```

Open http://127.0.0.1:5000. Debug mode is off unless you set `FLASK_DEBUG=1`.

## What each cycle added

### Cycle 1: Basic notes

- `notes_store.py` loads, creates, updates and deletes notes in `notes.json`.
  A missing file starts with an empty list. A damaged file is kept as
  `notes.json.corrupt` (or `notes.json.corrupt.1` and so on if that name is
  taken), so it can still be recovered:
  - If the file isn't valid JSON or isn't a list, it is renamed and the app
    starts with an empty list.
  - If it is a list with some bad entries, it is copied and the valid entries
    are kept.

  Each save writes a temp file and then replaces the real one, so a crash can't
  corrupt it.
- `app.py` serves the page and the notes API:
  - `GET /api/notes`
  - `POST /api/notes`
  - `PUT /api/notes/<id>`
  - `DELETE /api/notes/<id>`
- The page has a note list on the left and an editor on the right, with New,
  Save and Delete buttons. Delete asks for confirmation, and so does switching
  notes or clicking New when there are unsaved edits.
- A title is required. Titles can be up to 200 characters and bodies up to
  20,000.
