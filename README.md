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

To check the MCP server connections from the command line:

```powershell
python mcp_client.py tools
python mcp_client.py weather "Chicago"
python mcp_client.py fetch "https://example.com"
```

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

### Cycle 2: MCP server connection

- `weather_server.py` is an MCP server over stdio that wraps the free
  OpenWeatherMap API. It is built with the SDK's `MCPServer` class, which is
  the new name for FastMCP in `mcp` 2.x. It has two tools:
  - `get_current_weather(city)`: temperature, feels like, description, humidity
    and wind speed, in imperial units
  - `get_forecast(city, date)`: high, low and main conditions for a YYYY-MM-DD
    date in the next 5 days; a date outside that range gets a clear message
- Weather failures (city not found, bad key, timeout, rate limit and others)
  return a friendly message starting with `Weather error:`. Requests time out
  after 10 seconds.
- `mcp_client.py` starts a server over stdio, lists its tools and calls them,
  with a 20 second overall timeout per call. It also starts the ready-made
  `mcp-server-fetch` server with `python -m mcp_server_fetch`.
- Only `weather_server.py` reads `OPENWEATHER_API_KEY`. The client doesn't pass
  it to either server, and it never appears in tool results or logs.

### Cycle 3: Enhance notes

- The editor has two new actions:
  - **Add weather:** enter a city and an optional date. Without a date you get
    current weather; with one you get that day's forecast.
  - **Summarize link:** enter a URL or pick one found in the note. You get the
    page's text, trimmed to about 500 characters.
- Results appear in a preview box, and nothing changes until you click Insert
  or Discard. Insert adds the result to an `## Enhancements` section at the end
  of the note body, with its source and the time added. Click Save to keep it.
- `POST /api/enhance/weather` and `POST /api/enhance/link` call the MCP client
  and return JSON. Errors return a short message and a matching status code,
  never a stack trace.
- `link_safety.py` allows only http and https links. It resolves the hostname
  and refuses localhost, loopback, private and link-local addresses, so a note
  can't reach local services. The fetch server also refuses these addresses
  itself, including on redirects.
- `python app.py` no longer loads `.env`, so the API key stays out of the Flask
  process.

Try it: run `python app.py`, open a note, enter a city and click **Add weather**,
then click **Insert** and **Save**.
