import json
import unittest
from contextlib import ExitStack
from pathlib import Path
from tempfile import TemporaryDirectory
from datetime import datetime
from unittest.mock import patch

from bs4 import BeautifulSoup

import refresh


def soup(markup):
    return BeautifulSoup(markup, "html.parser")


class CalendarParsingTests(unittest.TestCase):
    def test_shortened_date_ranges(self):
        self.assertEqual(
            refresh.academic_dates("13 - 16/12/2026"), ("2026-12-13", "2026-12-16")
        )
        self.assertEqual(
            refresh.academic_dates("30/11 - 2/12/2026"), ("2026-11-30", "2026-12-02")
        )

    def test_union_times_follow_london_clock(self):
        self.assertEqual(
            refresh.split_date("2027-05-10T18:30:00+00:00"), ("2027-05-10", "19:30")
        )

    def test_careers_date_only_has_no_invented_start_time(self):
        index = soup('<a href="/careers/students/events/workshops.aspx">Workshops</a>')
        listing = soup(
            '<ul class="sys_rss"><li><a href="https://studentlife.nottingham.ac.uk/event/1">Workshop</a>'
            '<div class="ch-startdate"><strong>Starts:</strong> 10 Dec 2026</div></li></ul>'
        )
        with patch.object(refresh, "page", side_effect=[index, listing]):
            _, events = refresh.careers({}, datetime.now(refresh.UK))
        self.assertEqual(events[0]["date"], "2026-12-10")
        self.assertEqual(events[0]["time"], "")
        self.assertEqual(events[0]["price"], refresh.UNKNOWN)

    def test_psychology_news_does_not_become_an_event(self):
        news = soup(
            '<div class="sys_subitem"><h2>Publication news</h2></div>'
            '<a href="?NewsListing_GoToPage=2">Next</a><p>No events to display</p>'
        )
        with patch.object(refresh, "page", return_value=news) as fetch:
            orgs, events = refresh.university(
                {}, datetime.now(refresh.UK), "psychology"
            )
        self.assertEqual(orgs[0]["name"], "School of Psychology")
        self.assertEqual(events, [])
        fetch.assert_called_once()


class RefreshFailureTests(unittest.TestCase):
    def setUp(self):
        stack = ExitStack()
        self.addCleanup(stack.close)
        self.output = Path(stack.enter_context(TemporaryDirectory())) / "data.json"
        stack.enter_context(patch.object(refresh, "OUTPUT", self.output))
        self.cached = {
            "organisers": [{"id": "resx", "source": "living"}],
            "events": [self.row("Old event", "living")],
            "sources": {"living": {"lastSuccess": "2026-11-18T12:00:00+00:00"}},
        }
        self.output.write_text(json.dumps(self.cached))
        self.loaders = {
            name: stack.enter_context(
                patch.object(refresh, name, side_effect=ValueError("unavailable"))
            )
            for name in ("union", "living", "lakeside", "careers", "university")
        }

    def row(self, title, source):
        return {
            "date": "2099-01-01",
            "time": "17:00",
            "url": "https://example.com/" + source,
            "title": title,
            "source": source,
        }

    def test_partial_refresh_publishes_fresh_and_cached_sources(self):
        self.loaders["union"].side_effect = None
        self.loaders["union"].return_value = ([], [self.row("New event", "union")])
        refresh.main()
        result = json.loads(self.output.read_text())
        self.assertEqual(
            {item["title"] for item in result["events"]}, {"Old event", "New event"}
        )
        self.assertTrue(result["sources"]["union"]["ok"])
        self.assertFalse(result["sources"]["living"]["ok"])
        self.assertEqual(
            result["sources"]["living"]["lastSuccess"],
            self.cached["sources"]["living"]["lastSuccess"],
        )

    def test_total_failure_leaves_the_previous_snapshot_intact(self):
        before = self.output.read_bytes()
        with self.assertRaisesRegex(RuntimeError, "Every source failed"):
            refresh.main()
        self.assertEqual(self.output.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
