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
  return a friendly message with a stable code, such as
  `Weather error [city_not_found]: City not found: X.` Requests time out after
  10 seconds.
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

### Cycle 4: Smart suggestions

- `suggestions.py` scans the note body, leaving out the Enhancements section,
  using rules only:
  - URLs (http and https)
  - cities: a built-in list of about 100 major cities in any letter case, plus
    anything written as `City, ST` with a capitalized name and a US state code
  - dates: today, tomorrow, weekday names (the next occurrence, never today),
    `YYYY-MM-DD` and `Nov 3` or `November 3`
- It produces up to 5 suggestions, in the order they appear in the note:
  - `Add weather for Chicago on Nov 3` for a city with a date in the next 5 days
  - `Add current weather for Chicago` for a city with no usable date
  - `Summarize link example.com` for each URL
- A city uses the nearest date in its own sentence or line, or current weather
  if that date is out of range. If the sentence has no date, it uses the first
  usable date elsewhere in the note.
- Anything already in the Enhancements section isn't suggested again.
- `POST /api/suggestions` returns suggestions for the given text. The page asks
  after you stop typing for 1.5 seconds.
- Suggestions appear as chips under the editor. Clicking one runs the enhancement
  into the preview box, where it still needs Insert. Clicking × dismisses the
  chip for that note, and this browser remembers it. Only a click calls an MCP
  server; building suggestions never does.
- The weather endpoint now sets its status code from a stable code in the tool
  result instead of reading the message text. `City, ST` searches are sent to
  OpenWeatherMap as `City,ST,US`, then as written if that city isn't found.

Check detection with (no servers, API calls or network):

```powershell
python -m unittest test_suggestions
```

### Cycle 5: Templates

- The "New from template" dropdown starts a note with a template's headings:

  | Template | Sections | Suggestions |
  |---|---|---|
  | Blank | none | weather and links |
  | Meeting notes | Date, Attendees, Agenda, Notes, Action items | links |
  | Travel plan | Destination, Dates, Itinerary, Packing list | weather and links |
  | Project idea | Summary, Links, Next steps | links |

- The New button starts a Blank note.
- A small `Template: <name>` label next to the title shows the note's template.
- Each note stores its template name, and suggestions are filtered by that
  template's types. Filtered types don't use up any of the 5 suggestion slots.
  This only affects suggestions: **Add weather** and **Summarize link** work in
  every note.
- Templates are defined only in `templates_config.py`. The page receives them
  from the server when it is rendered.
