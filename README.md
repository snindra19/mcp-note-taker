# Smart Note Taker with MCP

A minimal local web app for taking notes, which uses MCP servers to add outside
information to them:

- **Weather** for places and dates mentioned in a note
- **Link content** for URLs pasted into a note, trimmed to about 500 characters

The app suggests these from the note's text using simple rules, with no AI model
involved. Nothing is added to a note until you click Insert.

Built with Python, Flask and the official MCP Python SDK. The page is one HTML
template with plain JavaScript and inline CSS. Notes are stored in a local
`notes.json` file.

## How MCP is used

The Flask app is the MCP client. `mcp_client.py` starts a server as a child
process, talks to it over stdio, makes one call and shuts it down.

| Server | Source | Started with | Tools |
|---|---|---|---|
| Weather | `weather_server.py`, written for this app with the SDK's `MCPServer` class | `python weather_server.py` | `get_current_weather(city)`, `get_forecast(city, date)` |
| Fetch | The official `mcp-server-fetch` package | `python -m mcp_server_fetch` | `fetch(url)` |

`MCPServer` is the name of FastMCP in `mcp` 2.x, the version this project pins.

The weather server wraps two free OpenWeatherMap endpoints: Current Weather
(`/data/2.5/weather`) and the 5 day / 3 hour Forecast (`/data/2.5/forecast`).

Weather failures carry a stable code, such as
`Weather error [city_not_found]: City not found: X.`, and `app.py` sets its status
code from that code. Requests to OpenWeatherMap time out after 10 seconds, and each
MCP call has a 20 second overall timeout.

### API key safety

- The key lives only in `.env`, which is never committed.
- Only `weather_server.py` reads it. The Flask app and the MCP client don't load
  it, and it isn't passed to the fetch server.
- It never reaches the browser and isn't included in tool results or logs.

## Get a free OpenWeatherMap key

1. Create a free account at https://home.openweathermap.org/users/sign_up.
2. Copy your key from the **API keys** tab of your account.

A new key can take a while to start working, sometimes a couple of hours. Until
then, weather requests report that the key was rejected.

## Setup

You need Python 3.10 or newer. These commands are for PowerShell:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
```

Then open `.env` and replace `your_key_here` with your key.

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

To check suggestion detection, with no servers, API calls or network:

```powershell
python -m unittest test_suggestions
```

## Using the app

The page has a note list on the left and an editor on the right. Delete asks for
confirmation, and so does leaving a note with unsaved edits. Titles are required
and can be up to 200 characters. Bodies can be up to 20,000.

### Enhancing a note

- **Add weather:** enter a city and an optional date. Without a date you get
  current weather. With a date in the next 5 days you get its high, low and main
  conditions.
- **Summarize link:** enter a URL or pick one found in the note.

Results appear in a preview box, where you choose Insert or Discard. Insert adds
the result to an `## Enhancements` section at the end of the note body, with its
source and the time added. Click Save to keep it.

Links must be http or https. The app resolves the hostname and refuses localhost,
loopback, private and link-local addresses, so a note can't reach local services.
The fetch server also refuses these addresses itself, including on redirects.

### Suggestions

`suggestions.py` scans the note body with rules, leaving out the Enhancements
section. It looks for:

- **URLs:** http and https
- **Cities:** a built-in list of about 100 major cities in any letter case, plus
  anything written as `City, ST` with a capitalized name and a US state code
- **Dates:** today, tomorrow, weekday names (the next occurrence, never today),
  `YYYY-MM-DD`, and `Nov 3` or `November 3`

It produces up to 5 suggestions, in the order they appear in the note:

| Suggestion | When |
|---|---|
| `Add weather for Chicago on Nov 3` | A city with a date in the next 5 days |
| `Add current weather for Chicago` | A city with no usable date |
| `Summarize link example.com` | Each URL |

- A city uses the nearest date in its own sentence or line, or current weather if
  that date is out of range. If the sentence has no date, it uses the first usable
  date elsewhere in the note.
- Anything already in the Enhancements section isn't suggested again.
- The page asks for suggestions after you stop typing for 1.5 seconds, and shows
  them as chips under the editor.
- Clicking a chip runs that enhancement into the preview box, where it still needs
  Insert.
- Clicking × dismisses a chip for that note.

Building suggestions never calls an MCP server. Only a click does.

### Templates

The "New from template" dropdown starts a note with a template's headings. The New
button starts a Blank note.

| Template | Sections | Suggestions |
|---|---|---|
| Blank | none | weather and links |
| Meeting notes | Date, Attendees, Agenda, Notes, Action items | links |
| Travel plan | Destination, Dates, Itinerary, Packing list | weather and links |
| Project idea | Summary, Links, Next steps | links |

Each note stores its template name, shown in a small `Template: <name>` label next
to the title, and its suggestions are filtered by that template's types. This only
affects suggestions: **Add weather** and **Summarize link** work in every note.

Templates are defined only in `templates_config.py`. The page receives them from
the server when it is rendered.

## Free-plan limits

OpenWeatherMap's free tier ("Free for everyone" on
[their pricing page](https://openweathermap.org/price)) allows **60 calls per
minute and 1,000,000 calls per month**, and includes both endpoints this app uses.
These figures were checked on November 1, 2026 and may change.

- Each Add weather click uses one call.
- A `City, ST` search that isn't found as a US city uses a second call, because it
  is then tried as written.
- Forecast dates outside the range and building suggestions use no calls.
- If the limit is reached, the app shows a rate limit message.
- The free forecast only covers about 5 days, so later dates get a clear message
  instead of a forecast.

The fetch server needs no key or plan.

## Known limitations

**Weather**

- A forecast for today only covers the 3-hour periods still ahead, so its high and
  low can differ from the full day's. The same applies to the last day in range,
  which may be only partly covered.

**Links**

- A "summary" is the start of the page's text, trimmed to about 500 characters. No
  AI model is involved, so it isn't a real summary.
- The fetch server respects `robots.txt`, so some sites refuse automated fetching.
- Looking up a hostname has no timeout of its own, so a very slow DNS server can
  hold up a link request beyond the 20 second limit.

**Suggestions**

- Detection is rule-based, so it can be wrong:
  - `Smith, MD` reads as a city.
  - A capitalized word before a city can be taken as part of its name unless it's
    on the skip list. `Visit` and `Flying` are on it, for example.
  - `Charlotte` and `Austin` can be people, not cities.
- `Friday` written on a Friday means next week, which is out of range, so that note
  gets current weather.
- In `Nov 3: Chicago; Nov 4: Dallas`, Chicago pairs with Nov 4, because an exact tie
  goes to the date after the city.
- Local links still get a chip, because suggestions don't look up addresses. Clicking
  the chip gets the link refused.
- Dismissed chips are stored in the browser, so they don't carry over to another
  browser and are lost if its site data is cleared.

**Timing**

- Each call starts a server, which adds a couple of seconds.
- A timed-out call can take about 22 seconds to return, because the SDK spends up to
  2 seconds shutting down the server after the 20 second timeout.

**Notes**

- Insert only changes the editor. The result isn't kept until you click Save.
- A note's template can't be changed after it's created.
- If `notes.json` isn't valid JSON or isn't a list, the app renames it to
  `notes.json.corrupt` (or `notes.json.corrupt.1` and so on) and starts with an empty
  list. If only some entries are bad, it copies the file to that name and keeps the
  valid notes. In both cases, recovering anything else from the backup is manual.

**General**

- This is a single-user local app on Flask's development server. It has no accounts
  and isn't meant to be exposed to a network.

## What each cycle added

1. **Basic notes:** note storage, the notes API and the page.
2. **MCP server connection:** the weather server, the MCP client and its command-line
   check.
3. **Enhance notes:** Add weather, Summarize link, the preview box and link safety.
4. **Smart suggestions:** rule-based detection, chips and stable weather error codes.
5. **Templates:** the template dropdown, stored template names and filtered
   suggestions.
