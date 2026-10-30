"""MCP server over stdio that wraps the free OpenWeatherMap API.

This is the only file that reads the API key. Failures return fixed friendly
messages and never include exception text, because a requests exception can
contain the full request URL, and that URL contains the key.
"""

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests
from dotenv import load_dotenv
from mcp.server.mcpserver import MCPServer

CURRENT_WEATHER_URL = "https://api.openweathermap.org/data/2.5/weather"
FORECAST_URL = "https://api.openweathermap.org/data/2.5/forecast"
REQUEST_TIMEOUT_SECONDS = 10
FORECAST_DAYS = 5

# Every failure message starts with this, so callers can tell failures apart
# from weather reports and from the "date out of range" message.
ERROR_PREFIX = "Weather error: "

# Find .env next to this file, whatever folder the server is started from.
load_dotenv(Path(__file__).resolve().parent / ".env")

# WARNING keeps request details out of the logs; debug logs can include URLs.
server = MCPServer("weather", log_level="WARNING")


def call_openweather(url: str, city: str) -> tuple[dict | None, str | None]:
    """Call an OpenWeatherMap endpoint; return (data, error message or None)."""
    api_key = os.getenv("OPENWEATHER_API_KEY", "").strip()
    if not api_key:
        return None, ERROR_PREFIX + "the API key is not set in .env."

    query_params = {"q": city, "appid": api_key, "units": "imperial"}
    try:
        response = requests.get(url, params=query_params, timeout=REQUEST_TIMEOUT_SECONDS)
    except requests.Timeout:
        return None, ERROR_PREFIX + "the weather service timed out. Please try again."
    except requests.RequestException:
        return None, ERROR_PREFIX + "could not reach the weather service."

    if response.status_code == 401:
        return None, ERROR_PREFIX + "the API key was rejected. It may be wrong or not active yet."
    if response.status_code == 404:
        return None, ERROR_PREFIX + f"city not found: {city}."
    if response.status_code == 429:
        return None, ERROR_PREFIX + "the free plan's rate limit was reached. Please try again later."
    if response.status_code != 200:
        return None, ERROR_PREFIX + "the weather service returned an unexpected response."

    try:
        return response.json(), None
    except ValueError:
        return None, ERROR_PREFIX + "the weather service returned an unreadable response."


def format_current_weather(data: dict) -> str:
    """Turn a Current Weather response into readable text."""
    conditions = data["main"]
    return (
        f"Current weather in {data['name']}, {data['sys']['country']}:\n"
        f"Temperature: {conditions['temp']:.0f}°F\n"
        f"Feels like: {conditions['feels_like']:.0f}°F\n"
        f"Description: {data['weather'][0]['description']}\n"
        f"Humidity: {conditions['humidity']}%\n"
        f"Wind speed: {data['wind']['speed']:.0f} mph"
    )


def parse_date(date_text: str) -> datetime.date:
    """Parse a strict YYYY-MM-DD date; raise ValueError for anything else."""
    parsed_date = datetime.strptime(date_text, "%Y-%m-%d").date()

    # strptime also accepts forms like 2026-1-5, so compare the text back.
    if parsed_date.isoformat() != date_text:
        raise ValueError("Date is not in YYYY-MM-DD form.")
    return parsed_date


def is_date_in_forecast_range(target_date: datetime.date) -> bool:
    """Return True if a date could be in the forecast in any time zone."""
    # The city's local date is unknown before the API call and can differ from
    # UTC by a day, so allow one extra day on each side. A date that passes but
    # has no forecast entries gets the same message from format_forecast.
    utc_today = datetime.now(timezone.utc).date()
    earliest_date = utc_today - timedelta(days=1)
    latest_date = utc_today + timedelta(days=FORECAST_DAYS + 1)
    return earliest_date <= target_date <= latest_date


def out_of_range_message(date_text: str) -> str:
    """Return the message for a date the forecast doesn't cover."""
    return f"No forecast is available for {date_text}. The forecast only covers the next {FORECAST_DAYS} days."


def find_entries_for_date(data: dict, target_date: datetime.date) -> list[dict]:
    """Return the 3-hour forecast entries that fall on a date in the city's time zone."""
    utc_offset_seconds = data["city"].get("timezone", 0)

    # Convert each entry's time to the city's local date and compare.
    matching_entries = []
    for entry in data["list"]:
        local_time = datetime.fromtimestamp(entry["dt"] + utc_offset_seconds, timezone.utc)
        if local_time.date() == target_date:
            matching_entries.append(entry)
    return matching_entries


def find_main_conditions(entries: list[dict]) -> str:
    """Return the most common weather condition in a list of forecast entries."""
    condition_counts = {}

    # Count how many entries report each condition.
    for entry in entries:
        condition = entry["weather"][0]["main"]
        condition_counts[condition] = condition_counts.get(condition, 0) + 1

    return max(condition_counts, key=condition_counts.get)


def format_forecast(data: dict, target_date: datetime.date) -> str:
    """Summarize a Forecast response for one day as high, low and main conditions."""
    entries = find_entries_for_date(data, target_date)
    if not entries:
        return out_of_range_message(target_date.isoformat())

    # Collect each 3-hour period's high and low to find the day's extremes.
    highs = []
    lows = []
    for entry in entries:
        highs.append(entry["main"]["temp_max"])
        lows.append(entry["main"]["temp_min"])

    city = data["city"]
    return (
        f"Forecast for {city['name']}, {city['country']} on {target_date.isoformat()}:\n"
        f"High: {max(highs):.0f}°F\n"
        f"Low: {min(lows):.0f}°F\n"
        f"Main conditions: {find_main_conditions(entries)}"
    )


@server.tool()
def get_current_weather(city: str) -> str:
    """Get the current weather for a city, in imperial units."""
    city = city.strip()
    if not city:
        return ERROR_PREFIX + "please enter a city."

    data, error = call_openweather(CURRENT_WEATHER_URL, city)
    if error:
        return error

    try:
        return format_current_weather(data)
    except (KeyError, IndexError, TypeError, ValueError, AttributeError):
        return ERROR_PREFIX + "the weather service returned an unexpected response."


@server.tool()
def get_forecast(city: str, date: str) -> str:
    """Get the high, low and main conditions for a date (YYYY-MM-DD) in the next 5 days."""
    city = city.strip()
    date = date.strip()
    if not city:
        return ERROR_PREFIX + "please enter a city."

    try:
        target_date = parse_date(date)
    except ValueError:
        return ERROR_PREFIX + "the date must be a real date in YYYY-MM-DD form."

    # Answer out-of-range dates without using an API call.
    if not is_date_in_forecast_range(target_date):
        return out_of_range_message(date)

    data, error = call_openweather(FORECAST_URL, city)
    if error:
        return error

    try:
        return format_forecast(data, target_date)
    except (KeyError, IndexError, TypeError, ValueError, AttributeError, OverflowError, OSError):
        return ERROR_PREFIX + "the weather service returned an unexpected response."


if __name__ == "__main__":
    server.run("stdio")
