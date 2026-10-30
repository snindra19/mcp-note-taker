"""Unit checks for suggestion detection. Run with: python -m unittest test_suggestions

These are pure: they use fixed dates and plain text, with no MCP servers, API
calls or network. Network access is blocked below, so any attempt fails.
"""

import socket
import subprocess
import sys
import unittest
from datetime import date
from unittest import mock

import suggestions as s

# A Sunday, so weekday results are easy to check by hand.
TODAY = date(2026, 11, 1)


def setUpModule() -> None:
    """Make any network use fail for the whole test run."""
    blocked = RuntimeError("Suggestion tests must not use the network.")
    unittest.addModuleCleanup(mock.patch.stopall)
    mock.patch("socket.socket", side_effect=blocked).start()
    mock.patch("socket.getaddrinfo", side_effect=blocked).start()


def labels_for(body: str, today: date = TODAY, dismissed_ids: list[str] | None = None) -> list[str]:
    """Return only the labels of the suggestions for a note body."""
    results = s.build_suggestions(body, today=today, dismissed_ids=dismissed_ids)
    labels = []
    for suggestion in results:
        labels.append(suggestion["label"])
    return labels


class PurityTests(unittest.TestCase):
    def test_module_imports_nothing_that_could_call_out(self) -> None:
        """Importing suggestions must not load MCP, HTTP or key-reading modules."""
        code = (
            "import sys, suggestions\n"
            "suspects = ['mcp', 'mcp_client', 'requests', 'httpx', 'dotenv', 'flask', 'weather_server', 'socket']\n"
            "print([name for name in suspects if name in sys.modules])\n"
        )
        result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=30)
        self.assertEqual(result.stdout.strip(), "[]", result.stderr)

    def test_building_suggestions_uses_no_network(self) -> None:
        """Detection works with sockets blocked, including for links."""
        self.assertTrue(labels_for("Chicago tomorrow https://example.com Rogers, AR"))


class CityTests(unittest.TestCase):
    def test_city_detection(self) -> None:
        cases = {
            "": [],
            "   \n\n": [],
            "Nothing of interest here.": [],
            "chicago": ["Add current weather for Chicago"],
            "CHICAGO": ["Add current weather for Chicago"],
            "cHiCaGo is nice": ["Add current weather for Chicago"],
            "Chicago's lakefront": ["Add current weather for Chicago"],
            "new york": ["Add current weather for New York"],
            "New  York": ["Add current weather for New York"],
            "salt lake city": ["Add current weather for Salt Lake City"],
            "st. louis": ["Add current weather for St. Louis"],
            "rio de janeiro": ["Add current weather for Rio de Janeiro"],
            "Paris-based team": ["Add current weather for Paris"],
            "(Tokyo)": ["Add current weather for Tokyo"],
            "Romeo and Parisian Detroiters": [],
            "Chicago and chicago and CHICAGO": ["Add current weather for Chicago"],
            "Chicago then Dallas": ["Add current weather for Chicago", "Add current weather for Dallas"],
        }
        for body, expected in cases.items():
            with self.subTest(body=body):
                self.assertEqual(labels_for(body), expected)

    def test_about_100_built_in_cities(self) -> None:
        self.assertTrue(90 <= len(s.BUILT_IN_CITIES) <= 110)
        self.assertEqual(len(s.BUILT_IN_CITIES), len(set(s.BUILT_IN_CITIES)))

    def test_every_built_in_city_is_detected(self) -> None:
        for city in s.BUILT_IN_CITIES:
            with self.subTest(city=city):
                self.assertEqual(labels_for(f"going to {city.lower()} soon"), [f"Add current weather for {city}"])

    def test_city_state_detection(self) -> None:
        cases = {
            "Rogers, AR": ["Add current weather for Rogers, AR"],
            "Rogers,AR": ["Add current weather for Rogers, AR"],
            "Meet in Rogers, AR soon": ["Add current weather for Rogers, AR"],
            "Visit Rogers, AR": ["Add current weather for Rogers, AR"],
            "Destination: Fort Smith, AR": ["Add current weather for Fort Smith, AR"],
            "Winston-Salem, NC": ["Add current weather for Winston-Salem, NC"],
            "O'Fallon, IL": ["Add current weather for O'Fallon, IL"],
            "Coeur D'Alene, ID": ["Add current weather for Coeur D'Alene, ID"],
            "Chicago, IL": ["Add current weather for Chicago, IL"],
            "Chicago, IL and Chicago": ["Add current weather for Chicago, IL", "Add current weather for Chicago"],
            "Rogers, ZZ": [],
            "rogers, ar": [],
            "Rogers, Ar": [],
            "Rogers, ARK": [],
            "Rogers,\nAR": [],
            "To, AR": [],
        }
        for body, expected in cases.items():
            with self.subTest(body=body):
                self.assertEqual(labels_for(body), expected)


class DateTests(unittest.TestCase):
    def test_date_forms(self) -> None:
        current = ["Add current weather for Chicago"]
        cases = {
            "Chicago today": ["Add weather for Chicago on Nov 1"],
            "Chicago TODAY": ["Add weather for Chicago on Nov 1"],
            "today's Chicago trip": ["Add weather for Chicago on Nov 1"],
            "Chicago tomorrow": ["Add weather for Chicago on Nov 2"],
            "Tomorrow: Chicago": ["Add weather for Chicago on Nov 2"],
            # Weekdays: the next occurrence, counted from Sunday Nov 1
            "Chicago on Monday": ["Add weather for Chicago on Nov 2"],
            "Chicago on wednesday": ["Add weather for Chicago on Nov 4"],
            "Chicago on FRIDAY": ["Add weather for Chicago on Nov 6"],
            "Chicago on Saturday": current,
            "Chicago on Sunday": current,
            # YYYY-MM-DD
            "Chicago on 2026-11-01": ["Add weather for Chicago on Nov 1"],
            "Chicago on 2026-11-06": ["Add weather for Chicago on Nov 6"],
            "Chicago on 2026-11-07": current,
            "Chicago on 2026-10-31": current,
            "Chicago on 2026-13-45": current,
            "Chicago on 2026-02-30": current,
            # Month day
            "Chicago on Nov 3": ["Add weather for Chicago on Nov 3"],
            "Chicago on nov 3": ["Add weather for Chicago on Nov 3"],
            "Chicago on November 3": ["Add weather for Chicago on Nov 3"],
            "Chicago on NOVEMBER 3": ["Add weather for Chicago on Nov 3"],
            "Chicago on Nov 3rd": ["Add weather for Chicago on Nov 3"],
            "Chicago on Nov 3, 2026": ["Add weather for Chicago on Nov 3"],
            "Chicago on Nov 3 2026": ["Add weather for Chicago on Nov 3"],
            "Chicago on Nov 3, 2027": current,
            "Chicago on Nov 6": ["Add weather for Chicago on Nov 6"],
            "Chicago on Nov 7": current,
            "Chicago on Oct 31": current,
            "Chicago on Feb 30": current,
            "Chicago on Nov 99": current,
            "Chicago on Nov 300": current,
            "Chicago in November": current,
            # Not dates
            "Chicago 11/03": current,
            "Chicago on Someday": current,
        }
        for body, expected in cases.items():
            with self.subTest(body=body):
                self.assertEqual(labels_for(body), expected)

    def test_every_month_name_form(self) -> None:
        months = {
            "Jan": 1, "January": 1, "Feb": 2, "February": 2, "Mar": 3, "March": 3, "Apr": 4, "April": 4,
            "May": 5, "Jun": 6, "June": 6, "Jul": 7, "July": 7, "Aug": 8, "August": 8, "Sep": 9, "Sept": 9,
            "September": 9, "Oct": 10, "October": 10, "Nov": 11, "November": 11, "Dec": 12, "December": 12,
        }
        for month_text, month_number in months.items():
            with self.subTest(month=month_text):
                results = s.build_suggestions(f"Chicago on {month_text} 10", today=date(2026, month_number, 9))
                self.assertEqual(results[0]["date"], date(2026, month_number, 10).isoformat())

    def test_month_day_rolls_over_to_next_year(self) -> None:
        results = s.build_suggestions("Chicago on Jan 2", today=date(2026, 12, 30))
        self.assertEqual(results[0]["date"], "2027-01-02")
        self.assertEqual(results[0]["label"], "Add weather for Chicago on Jan 2")

    def test_weekday_when_today_is_that_weekday(self) -> None:
        # Wednesday Nov 4: "Wednesday" is next week, "Thursday" is tomorrow.
        wednesday = date(2026, 11, 4)
        self.assertEqual(labels_for("Chicago on Wednesday", today=wednesday), ["Add current weather for Chicago"])
        self.assertEqual(labels_for("Chicago on Thursday", today=wednesday), ["Add weather for Chicago on Nov 5"])

    def test_range_crosses_month_and_leap_day(self) -> None:
        self.assertEqual(labels_for("Chicago on Dec 2", today=date(2026, 11, 30)), ["Add weather for Chicago on Dec 2"])
        self.assertEqual(labels_for("Chicago on Feb 29", today=date(2028, 2, 27)), ["Add weather for Chicago on Feb 29"])
        self.assertEqual(labels_for("Chicago on Feb 29", today=date(2027, 2, 27)), ["Add current weather for Chicago"])


class PairingTests(unittest.TestCase):
    def test_city_and_date_pairing(self) -> None:
        cases = {
            "Chicago on Nov 3. Dallas on Nov 4.": ["Add weather for Chicago on Nov 3", "Add weather for Dallas on Nov 4"],
            "Chicago Nov 3\nDallas Nov 4": ["Add weather for Chicago on Nov 3", "Add weather for Dallas on Nov 4"],
            "Destination: Chicago\nDates: Nov 3": ["Add weather for Chicago on Nov 3"],
            "Dates: Nov 3\nDestination: Chicago": ["Add weather for Chicago on Nov 3"],
            "Chicago on Dec 25. Dallas tomorrow.": ["Add current weather for Chicago", "Add weather for Dallas on Nov 2"],
            # The nearest date in the sentence decides, even when it's out of range
            "Chicago tomorrow, then Rogers, AR on Dec 25": ["Add weather for Chicago on Nov 2", "Add current weather for Rogers, AR"],
            "Chicago on Dec 25, then Dallas tomorrow": ["Add current weather for Chicago", "Add weather for Dallas on Nov 2"],
            "Nov 3 Chicago and Nov 4 Dallas": ["Add weather for Chicago on Nov 3", "Add weather for Dallas on Nov 4"],
            "Chicago on Nov 3, Dallas on Nov 4, Tokyo on Nov 5": [
                "Add weather for Chicago on Nov 3", "Add weather for Dallas on Nov 4", "Add weather for Tokyo on Nov 5",
            ],
            "Tomorrow: Chicago. Friday: Dallas.": ["Add weather for Chicago on Nov 2", "Add weather for Dallas on Nov 6"],
            "Chicago on Dec 25 or Nov 3": ["Add current weather for Chicago"],
            "Chicago on Nov 3 and Nov 4": ["Add weather for Chicago on Nov 3"],
            "Chicago and Dallas on Nov 3": ["Add weather for Chicago on Nov 3", "Add weather for Dallas on Nov 3"],
            "Rogers, AR on Nov 3": ["Add weather for Rogers, AR on Nov 3"],
            "Chicago, Nov 3": ["Add weather for Chicago on Nov 3"],
            "Chicago: Nov 3; Dallas: Nov 4": ["Add weather for Chicago on Nov 3", "Add weather for Dallas on Nov 4"],
            # Two different days for a city are two different forecasts
            "Chicago today, Chicago tomorrow": ["Add weather for Chicago on Nov 1", "Add weather for Chicago on Nov 2"],
            "Chicago tomorrow. Chicago tomorrow.": ["Add weather for Chicago on Nov 2"],
        }
        for body, expected in cases.items():
            with self.subTest(body=body):
                self.assertEqual(labels_for(body), expected)


class LinkTests(unittest.TestCase):
    def test_link_detection(self) -> None:
        cases = {
            "https://example.com": ["Summarize link example.com"],
            "http://example.com": ["Summarize link example.com"],
            "HTTPS://EXAMPLE.COM": ["Summarize link example.com"],
            "https://example.com/": ["Summarize link example.com"],
            "see https://example.com/a/b/ now": ["Summarize link example.com/a/b"],
            "See https://example.com.": ["Summarize link example.com"],
            "Really https://example.com?!": ["Summarize link example.com"],
            "(https://example.com)": ["Summarize link example.com"],
            "[docs](https://example.com/docs)": ["Summarize link example.com/docs"],
            "<https://example.com>": ["Summarize link example.com"],
            '"https://example.com"': ["Summarize link example.com"],
            "https://en.example.org/wiki/A_(b)": ["Summarize link en.example.org/wiki/A_(b)"],
            "https://example.com https://example.com/": ["Summarize link example.com"],
            "https://a.example https://b.example": ["Summarize link a.example", "Summarize link b.example"],
            "https://example.com/a https://example.com/b": ["Summarize link example.com/a", "Summarize link example.com/b"],
            "ftp://example.com": [],
            "file:///c:/x": [],
            "javascript:alert(1)": [],
            "www.example.com": [],
            "https://": [],
            "http://[bad": [],
        }
        for body, expected in cases.items():
            with self.subTest(body=body):
                self.assertEqual(labels_for(body), expected)

    def test_link_fields(self) -> None:
        results = s.build_suggestions("Read https://example.com/page?a=1#top, please.", today=TODAY)
        self.assertEqual(results[0]["type"], "link")
        self.assertEqual(results[0]["url"], "https://example.com/page?a=1#top")

    def test_long_link_label_is_shortened(self) -> None:
        url = "https://example.com/" + "a" * 100
        results = s.build_suggestions(url, today=TODAY)
        self.assertEqual(results[0]["url"], url)
        self.assertLessEqual(len(results[0]["label"]), len("Summarize link ") + s.MAX_LINK_LABEL_LENGTH)

    def test_words_inside_urls_are_not_cities_or_dates(self) -> None:
        cases = {
            "https://chicago.example/": ["Summarize link chicago.example"],
            "https://example.com/paris/2026-11-03/today": ["Summarize link example.com/paris/2026-11-03/today"],
            "Chicago https://example.com/2026-11-03": ["Add current weather for Chicago", "Summarize link example.com/2026-11-03"],
        }
        for body, expected in cases.items():
            with self.subTest(body=body):
                self.assertEqual(labels_for(body), expected)


class LimitAndOrderTests(unittest.TestCase):
    def test_limit_of_five_in_text_order(self) -> None:
        body = "Tokyo https://a.example Paris https://b.example London https://c.example Rome"
        self.assertEqual(
            labels_for(body),
            [
                "Add current weather for Tokyo",
                "Summarize link a.example",
                "Add current weather for Paris",
                "Summarize link b.example",
                "Add current weather for London",
            ],
        )

    def test_repeats_do_not_use_up_the_limit(self) -> None:
        body = "Tokyo Tokyo Tokyo Tokyo Tokyo Tokyo Paris"
        self.assertEqual(labels_for(body), ["Add current weather for Tokyo", "Add current weather for Paris"])


class EnhancementsTests(unittest.TestCase):
    def test_text_inside_the_section_is_not_scanned(self) -> None:
        body = "My note\n\n## Enhancements\n\n### Link: https://a.example\nSource: link | Added: x\n\nPage about Tokyo tomorrow https://b.example"
        self.assertEqual(labels_for(body), [])

    def test_dates_inside_the_section_do_not_pair_with_cities(self) -> None:
        body = "Chicago\n\n## Enhancements\n\nSomething about Nov 3"
        self.assertEqual(labels_for(body), ["Add current weather for Chicago"])

    def test_heading_must_be_on_its_own_line(self) -> None:
        self.assertEqual(labels_for("see ## Enhancements Chicago"), ["Add current weather for Chicago"])
        self.assertEqual(labels_for("### Enhancements\nChicago"), ["Add current weather for Chicago"])

    def test_already_added_results_are_not_suggested(self) -> None:
        section = "\n\n## Enhancements\n\n"
        cases = [
            ("Chicago" + section + "### Weather: Chicago\nSource: weather", []),
            ("chicago" + section + "### Weather: CHICAGO\nSource: weather", []),
            ("Chicago on Nov 3" + section + "### Weather: Chicago on 2026-11-03\nSource: weather", []),
            ("Rogers, AR" + section + "### Weather: Rogers, AR\nSource: weather", []),
            ("https://example.com" + section + "### Link: https://example.com\nSource: link", []),
            ("https://example.com" + section + "### Link: https://example.com/\nSource: link", []),
            ("https://example.com/" + section + "### Link: HTTPS://EXAMPLE.COM\nSource: link", []),
            # Different results are still suggested
            ("Chicago on Nov 3" + section + "### Weather: Chicago\nSource: weather", ["Add weather for Chicago on Nov 3"]),
            ("Chicago" + section + "### Weather: Chicago on 2026-11-03\nSource: weather", ["Add current weather for Chicago"]),
            ("Chicago on Nov 4" + section + "### Weather: Chicago on 2026-11-03\nSource: weather", ["Add weather for Chicago on Nov 4"]),
            ("https://example.com/a" + section + "### Link: https://example.com/b\nSource: link", ["Summarize link example.com/a"]),
            ("https://example.com/?a=1" + section + "### Link: https://example.com/?a=2\nSource: link", ["Summarize link example.com"]),
        ]
        for body, expected in cases:
            with self.subTest(body=body):
                self.assertEqual(labels_for(body), expected)

    def test_added_results_free_up_slots(self) -> None:
        body = "Tokyo Paris London Rome Madrid Berlin\n\n## Enhancements\n\n### Weather: Tokyo\nSource: weather"
        labels = labels_for(body)
        self.assertEqual(len(labels), 5)
        self.assertNotIn("Add current weather for Tokyo", labels)
        self.assertIn("Add current weather for Berlin", labels)

    def test_garbled_link_heading_is_ignored(self) -> None:
        self.assertEqual(labels_for("Chicago\n\n## Enhancements\n\n### Link: http://[bad\n"), ["Add current weather for Chicago"])


class SuggestionFieldTests(unittest.TestCase):
    def test_forecast_fields(self) -> None:
        result = s.build_suggestions("Chicago on Nov 3", today=TODAY)[0]
        self.assertEqual(result, {
            "id": "weather|chicago|2026-11-03",
            "type": "weather",
            "label": "Add weather for Chicago on Nov 3",
            "city": "Chicago",
            "date": "2026-11-03",
        })

    def test_current_weather_fields(self) -> None:
        result = s.build_suggestions("Chicago", today=TODAY)[0]
        self.assertEqual(result["id"], "weather|chicago|current")
        self.assertEqual(result["date"], "")

    def test_ids_ignore_spelling_differences(self) -> None:
        first = s.build_suggestions("chicago", today=TODAY)[0]["id"]
        second = s.build_suggestions("CHICAGO", today=TODAY)[0]["id"]
        self.assertEqual(first, second)
        first = s.build_suggestions("https://example.com", today=TODAY)[0]["id"]
        second = s.build_suggestions("HTTPS://EXAMPLE.COM/", today=TODAY)[0]["id"]
        self.assertEqual(first, second)

    def test_dismissed_ids_are_left_out_before_the_limit(self) -> None:
        body = "Tokyo Paris London Rome Madrid Berlin"
        labels = labels_for(body, dismissed_ids=["weather|tokyo|current"])
        self.assertEqual(len(labels), 5)
        self.assertNotIn("Add current weather for Tokyo", labels)
        self.assertIn("Add current weather for Berlin", labels)

    def test_today_defaults_to_the_current_date(self) -> None:
        self.assertEqual(s.build_suggestions("Chicago today")[0]["date"], date.today().isoformat())


if __name__ == "__main__":
    unittest.main()
