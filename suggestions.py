"""Rule-based suggestions from a note's text.

Everything here is plain text processing. Nothing in this file calls an MCP
server, an API or the network; only a click on a suggestion does that.
"""

import re
from datetime import date, timedelta
from urllib.parse import urlsplit

MAX_SUGGESTIONS = 5
FORECAST_DAYS = 5
MAX_LINK_LABEL_LENGTH = 40

BUILT_IN_CITIES = (
    # United States
    "New York", "Los Angeles", "Chicago", "Houston", "Phoenix", "Philadelphia",
    "San Antonio", "San Diego", "Dallas", "San Jose", "Austin", "Jacksonville",
    "Fort Worth", "Columbus", "Charlotte", "San Francisco", "Indianapolis",
    "Seattle", "Denver", "Washington", "Boston", "Nashville", "Detroit",
    "Portland", "Las Vegas", "Memphis", "Baltimore", "Milwaukee", "Albuquerque",
    "Tucson", "Sacramento", "Kansas City", "Atlanta", "Miami", "Minneapolis",
    "New Orleans", "Tampa", "Orlando", "Cleveland", "Pittsburgh", "St. Louis",
    "Salt Lake City", "Honolulu", "Anchorage", "Raleigh",
    # Rest of the world
    "London", "Paris", "Berlin", "Madrid", "Rome", "Amsterdam", "Brussels",
    "Vienna", "Zurich", "Geneva", "Stockholm", "Oslo", "Copenhagen", "Helsinki",
    "Dublin", "Lisbon", "Prague", "Warsaw", "Budapest", "Athens", "Istanbul",
    "Moscow", "Cairo", "Lagos", "Nairobi", "Johannesburg", "Cape Town", "Dubai",
    "Tel Aviv", "Riyadh", "Mumbai", "Delhi", "Bangalore", "Kolkata", "Chennai",
    "Karachi", "Dhaka", "Bangkok", "Singapore", "Hong Kong", "Beijing",
    "Shanghai", "Seoul", "Tokyo", "Osaka", "Taipei", "Manila", "Jakarta",
    "Sydney", "Melbourne", "Auckland", "Toronto", "Vancouver", "Montreal",
    "Mexico City", "Sao Paulo", "Rio de Janeiro", "Buenos Aires", "Lima",
    "Bogota", "Santiago",
)

US_STATE_CODES = frozenset({
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA", "HI", "ID", "IL",
    "IN", "IA", "KS", "KY", "LA", "ME", "MD", "MA", "MI", "MN", "MS", "MO", "MT",
    "NE", "NV", "NH", "NJ", "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI",
    "SC", "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY", "DC",
})

# Capitalized words that can come before a city but aren't part of its name.
WORDS_BEFORE_CITY = frozenset({
    "a", "and", "at", "destination", "fly", "flying", "for", "from", "go", "going",
    "in", "meeting", "near", "on", "the", "to", "today", "tomorrow", "travel",
    "traveling", "trip", "visit", "visiting", "monday", "tuesday", "wednesday",
    "thursday", "friday", "saturday", "sunday",
})

WEEKDAY_NAMES = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")

# Maps the first three letters of a month's name to its number.
MONTH_NUMBERS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}

ENHANCEMENTS_PATTERN = re.compile(r"^## Enhancements[ \t\r]*$", re.MULTILINE)
EXISTING_WEATHER_PATTERN = re.compile(
    r"^### Weather: (.+?)(?: on (\d{4}-\d{2}-\d{2}))?[ \t\r]*$", re.MULTILINE
)
EXISTING_LINK_PATTERN = re.compile(r"^### Link: (\S+)[ \t\r]*$", re.MULTILINE)
URL_PATTERN = re.compile(r"https?://[^\s<>\"`]+", re.IGNORECASE)
CITY_STATE_PATTERN = re.compile(
    r"(?<![\w'-])([A-Z][\w.'-]*(?:[ \t]+[A-Z][\w.'-]*){0,2}),[ \t]*([A-Z]{2})\b"
)
ISO_DATE_PATTERN = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
RELATIVE_DAY_PATTERN = re.compile(r"\b(today|tomorrow)\b", re.IGNORECASE)
WEEKDAY_PATTERN = re.compile(r"\b(" + "|".join(WEEKDAY_NAMES) + r")\b", re.IGNORECASE)
MONTH_DAY_PATTERN = re.compile(
    r"\b(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?"
    r"|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\.?[ \t]+"
    r"(\d{1,2})(?:st|nd|rd|th)?\b(?:,?[ \t]+(\d{4})\b)?",
    re.IGNORECASE,
)
SENTENCE_END_PATTERN = re.compile(r"\n|[.!?](?=\s)")


def build_city_pattern() -> re.Pattern:
    """Build a pattern matching any built-in city, trying longer names first."""
    names_longest_first = sorted(BUILT_IN_CITIES, key=len, reverse=True)

    # Allow any amount of space between the words of a city's name.
    name_patterns = []
    for city_name in names_longest_first:
        name_patterns.append(re.escape(city_name).replace(r"\ ", r"\s+"))
    return re.compile(r"\b(" + "|".join(name_patterns) + r")\b", re.IGNORECASE)


CITY_PATTERN = build_city_pattern()


def build_canonical_city_names() -> dict[str, str]:
    """Map each built-in city's lowercase name to its normal spelling."""
    canonical_names = {}
    for city_name in BUILT_IN_CITIES:
        canonical_names[city_name.lower()] = city_name
    return canonical_names


CANONICAL_CITY_NAMES = build_canonical_city_names()


def split_enhancements(body: str) -> tuple[str, str]:
    """Split a note body into (the user's own text, the Enhancements section)."""
    match = ENHANCEMENTS_PATTERN.search(body)
    if match is None:
        return body, ""
    return body[:match.start()], body[match.end():]


def clean_url(url: str) -> str:
    """Remove punctuation from the end of a URL that belongs to the sentence."""
    while url:
        last_character = url[-1]
        has_unmatched_bracket = last_character == ")" and url.count(")") > url.count("(")
        if last_character not in ".,;:!?'\"]}" and not has_unmatched_bracket:
            break
        url = url[:-1]
    return url


def normalize_url(url: str) -> str:
    """Return a URL in a form where equivalent spellings compare as equal."""
    parts = urlsplit(url)
    path = parts.path.rstrip("/")
    normalized = f"{parts.scheme.lower()}://{parts.netloc.lower()}{path}"
    if parts.query:
        normalized += "?" + parts.query
    return normalized


def build_link_label(url: str) -> str:
    """Return a short name for a link, such as example.com/page."""
    parts = urlsplit(url)
    label = parts.hostname + parts.path.rstrip("/")
    if len(label) > MAX_LINK_LABEL_LENGTH:
        label = label[:MAX_LINK_LABEL_LENGTH - 3] + "..."
    return label


def find_urls(text: str) -> list[tuple[int, str]]:
    """Return (position, URL) for each usable http or https URL in the text."""
    found_urls = []
    for match in URL_PATTERN.finditer(text):
        url = clean_url(match.group())
        # A URL that can't be parsed or has no host can't become a suggestion.
        try:
            has_host = urlsplit(url).hostname is not None
        except ValueError:
            has_host = False
        if has_host:
            found_urls.append((match.start(), url))
    return found_urls


def blank_out_urls(text: str) -> str:
    """Replace URLs with spaces, so words inside them aren't read as cities or dates."""
    # Keep the length the same, so positions in the result still match the text.
    def replace_with_spaces(match: re.Match) -> str:
        return " " * len(match.group())

    return URL_PATTERN.sub(replace_with_spaces, text)


def find_city_state_names(text: str) -> list[tuple[int, int, str]]:
    """Return (start, end, name) for each name written like "Rogers, AR"."""
    found_names = []
    for match in CITY_STATE_PATTERN.finditer(text):
        state_code = match.group(2)
        if state_code not in US_STATE_CODES:
            continue

        # Drop leading words that aren't part of the name, as in "Visit Rogers".
        words = match.group(1).split()
        while words and words[0].lower() in WORDS_BEFORE_CITY:
            words = words[1:]
        if words:
            found_names.append((match.start(), match.end(), " ".join(words) + ", " + state_code))
    return found_names


def find_cities(text: str) -> list[tuple[int, int, str]]:
    """Return (start, end, city name) for each "City, ST" name and built-in city."""
    found_cities = []
    remaining_text = text

    # Handle "City, ST" first, then blank it so "Chicago, IL" isn't found twice.
    for start, end, name in find_city_state_names(text):
        found_cities.append((start, end, name))
        remaining_text = remaining_text[:start] + " " * (end - start) + remaining_text[end:]

    for match in CITY_PATTERN.finditer(remaining_text):
        spaced_name = " ".join(match.group().split())
        found_cities.append((match.start(), match.end(), CANONICAL_CITY_NAMES[spaced_name.lower()]))
    return found_cities


def resolve_month_day(month_text: str, day: int, year: int | None, today: date) -> date | None:
    """Return the date for a "Month day" form, or None if there isn't one."""
    month = MONTH_NUMBERS[month_text[:3].lower()]

    # With no year, use this year's date unless it has passed, then next year's.
    candidate_years = [year] if year is not None else [today.year, today.year + 1]
    for candidate_year in candidate_years:
        try:
            candidate_date = date(candidate_year, month, day)
        except ValueError:
            continue
        if year is not None or candidate_date >= today:
            return candidate_date
    return None


def find_dates(text: str, today: date) -> list[tuple[int, int, date]]:
    """Return (start, end, date) for each date in the text, in order of position."""
    found_dates = []

    for match in RELATIVE_DAY_PATTERN.finditer(text):
        days_ahead = 0 if match.group(1).lower() == "today" else 1
        found_dates.append((match.start(), match.end(), today + timedelta(days=days_ahead)))

    # A weekday name means its next occurrence, which is never today.
    for match in WEEKDAY_PATTERN.finditer(text):
        days_ahead = WEEKDAY_NAMES.index(match.group(1).lower()) - today.weekday()
        if days_ahead <= 0:
            days_ahead += 7
        found_dates.append((match.start(), match.end(), today + timedelta(days=days_ahead)))

    for match in ISO_DATE_PATTERN.finditer(text):
        try:
            found_date = date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
        except ValueError:
            continue
        found_dates.append((match.start(), match.end(), found_date))

    for match in MONTH_DAY_PATTERN.finditer(text):
        year = int(match.group(3)) if match.group(3) else None
        found_date = resolve_month_day(match.group(1), int(match.group(2)), year, today)
        if found_date is not None:
            found_dates.append((match.start(), match.end(), found_date))

    found_dates.sort(key=lambda found: found[0])
    return found_dates


def is_usable_date(candidate_date: date, today: date) -> bool:
    """Return True if a date is within the forecast's range."""
    return today <= candidate_date <= today + timedelta(days=FORECAST_DAYS)


def find_first_usable_date(dates: list[tuple[int, int, date]], today: date) -> date | None:
    """Return the first usable date in a list of found dates, or None."""
    for _, _, candidate_date in dates:
        if is_usable_date(candidate_date, today):
            return candidate_date
    return None


def rank_date_for_city(
    text: str, date_start: int, date_end: int, city_start: int, city_end: int
) -> tuple[bool, int, bool]:
    """Return a date's closeness to a city; lower values are closer.

    A date with a comma, semicolon or colon between it and the city ranks behind
    any date without one, so in "Chicago on Nov 3, Dallas on Nov 4" Dallas gets
    Nov 4. Next, the date with the fewest characters in between wins. An exact
    tie goes to the date after the city, the usual way of writing it.
    """
    is_before_city = date_start < city_end
    if is_before_city:
        text_between = text[date_end:city_start]
    else:
        text_between = text[city_end:date_start]

    has_separator = False
    for character in text_between:
        if character in ",;:":
            has_separator = True
    return has_separator, len(text_between), is_before_city


def find_sentence_bounds(text: str, position: int) -> tuple[int, int]:
    """Return the start and end of the sentence or line around a position."""
    sentence_start = 0
    for match in SENTENCE_END_PATTERN.finditer(text):
        if match.end() <= position:
            sentence_start = match.end()
        else:
            return sentence_start, match.start()
    return sentence_start, len(text)


def choose_date_for_city(
    text: str, city_start: int, city_end: int, dates: list[tuple[int, int, date]], today: date
) -> date | None:
    """Return the date to pair with a city, or None if there is no usable one."""
    sentence_start, sentence_end = find_sentence_bounds(text, city_start)

    # Find the date closest to the city within its own sentence.
    nearest_date = None
    nearest_rank = None
    for date_start, date_end, found_date in dates:
        if not sentence_start <= date_start < sentence_end:
            continue
        rank = rank_date_for_city(text, date_start, date_end, city_start, city_end)
        if nearest_rank is None or rank < nearest_rank:
            nearest_date = found_date
            nearest_rank = rank

    # The nearest date decides it, even when that date is out of range, so
    # "Rogers, AR on Dec 25" never borrows another city's date from the sentence.
    if nearest_date is not None:
        return nearest_date if is_usable_date(nearest_date, today) else None

    # With no date in the sentence, use one from elsewhere, as when dates are on
    # their own line.
    return find_first_usable_date(dates, today)


def build_weather_id(city: str, weather_date: str | None) -> str:
    """Return the stable id for a weather suggestion."""
    return f"weather|{city.lower()}|{weather_date or 'current'}"


def build_link_id(url: str) -> str:
    """Return the stable id for a link suggestion."""
    return "link|" + normalize_url(url)


def find_existing_ids(enhancements_text: str) -> set[str]:
    """Return the ids of everything already in the Enhancements section."""
    existing_ids = set()

    for match in EXISTING_WEATHER_PATTERN.finditer(enhancements_text):
        existing_ids.add(build_weather_id(match.group(1), match.group(2)))

    # A heading that can't be parsed as a URL can't match a suggestion anyway.
    for match in EXISTING_LINK_PATTERN.finditer(enhancements_text):
        try:
            existing_ids.add(build_link_id(match.group(1)))
        except ValueError:
            continue
    return existing_ids


def build_weather_suggestion(city: str, weather_date: date | None) -> dict:
    """Return a weather suggestion, for a date or for current weather."""
    if weather_date is None:
        return {
            "id": build_weather_id(city, None),
            "type": "weather",
            "label": f"Add current weather for {city}",
            "city": city,
            "date": "",
        }

    date_text = weather_date.isoformat()
    return {
        "id": build_weather_id(city, date_text),
        "type": "weather",
        "label": f"Add weather for {city} on {weather_date.strftime('%b')} {weather_date.day}",
        "city": city,
        "date": date_text,
    }


def build_link_suggestion(url: str) -> dict:
    """Return a link suggestion."""
    return {
        "id": build_link_id(url),
        "type": "link",
        "label": f"Summarize link {build_link_label(url)}",
        "url": url,
    }


def build_suggestions(
    body: str,
    today: date | None = None,
    dismissed_ids: list[str] | None = None,
    enabled_types: list[str] | None = None,
) -> list[dict]:
    """Return up to MAX_SUGGESTIONS suggestions for a note body, in text order.

    If enabled_types is given, only suggestions of those types are returned.
    """
    if today is None:
        today = date.today()

    user_text, enhancements_text = split_enhancements(body)
    text_without_urls = blank_out_urls(user_text)
    dates = find_dates(text_without_urls, today)

    # Collect every candidate with its position in the text.
    candidates = []
    for position, url in find_urls(user_text):
        candidates.append((position, build_link_suggestion(url)))
    for city_start, city_end, city in find_cities(text_without_urls):
        weather_date = choose_date_for_city(text_without_urls, city_start, city_end, dates, today)
        candidates.append((city_start, build_weather_suggestion(city, weather_date)))
    candidates.sort(key=lambda candidate: candidate[0])

    # These are skipped before the limit, so hidden ones don't use up a slot.
    skipped_ids = find_existing_ids(enhancements_text)
    skipped_ids.update(dismissed_ids or [])

    # Keep the first of each suggestion, up to the limit.
    suggestions = []
    for _, suggestion in candidates:
        if enabled_types is not None and suggestion["type"] not in enabled_types:
            continue
        if suggestion["id"] in skipped_ids:
            continue
        skipped_ids.add(suggestion["id"])
        suggestions.append(suggestion)
        if len(suggestions) == MAX_SUGGESTIONS:
            break
    return suggestions
