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
    def test_hacksoc_skips_an_undated_archived_event(self):
        rows = [
            {"date": "<no value>", "title": "HackNotts 2021"},
            {
                "date": "2026-11-19",
                "title": "Lecture Slide Karaoke",
                "permalink": "/events/karaoke",
                "time": "18:30",
            },
        ]
        with patch.object(refresh, "get") as fetch:
            fetch.return_value.json.return_value = {"data": rows}
            _, events = refresh.hacksoc({}, datetime(2026, 11, 19))
        self.assertEqual([e["title"] for e in events], ["Lecture Slide Karaoke"])

    def test_robotics_keeps_inclusive_local_end_dates(self):
        dates = [
            (
                "all-day",
                "DTSTART;VALUE=DATE:20261118",
                "DTEND;VALUE=DATE:20261121",
                "2026-11-20",
            ),
            (
                "midnight",
                "DTSTART:20261118T170000Z",
                "DTEND:20261120T000000Z",
                "2026-11-19",
            ),
            (
                "overnight",
                "DTSTART:20261118T170000Z",
                "DTEND:20261120T010000Z",
                "2026-11-20",
            ),
            (
                "summer",
                "DTSTART:20270501T180000Z",
                "DTEND:20270502T230000Z",
                "2027-05-02",
            ),
        ]
        lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//test//EN"]
        for name, begin, end, _ in dates:
            lines.extend(
                [
                    "BEGIN:VEVENT",
                    "UID:" + name,
                    "SUMMARY:" + name,
                    begin,
                    end,
                    "END:VEVENT",
                ]
            )
        with patch.object(refresh, "get") as fetch:
            fetch.return_value.content = "\r\n".join(lines + ["END:VCALENDAR"]).encode()
            _, result = refresh.robotics({}, datetime(2026, 11, 19, tzinfo=refresh.UK))
        self.assertEqual(
            {e["title"]: e["endDate"] for e in result}, {r[0]: r[3] for r in dates}
        )

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
            for name in (
                "union",
                "living",
                "lakeside",
                "careers",
                "university",
                "hacksoc",
                "newtheatre",
                "robotics",
            )
        }

    def row(self, title, source):
        return {
            "date": "2099-01-01",
            "time": "17:00",
            "url": "https://example.com/" + source,
            "title": title,
            "organiser": "resx",
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

    def test_sources_keep_independent_copies_of_crosslisted_events(self):
        self.output.unlink()
        for source in ("union", "hacksoc"):
            row = dict(
                self.row("Society talk", source),
                organiser="su-213",
                url="https://example.com/shared",
            )
            self.loaders[source].side_effect = None
            self.loaders[source].return_value = ([], [row])
        refresh.main()
        result = json.loads(self.output.read_text())
        self.assertEqual({e["source"] for e in result["events"]}, {"union", "hacksoc"})

    def test_calendar_uses_shared_organiser_if_union_is_unavailable(self):
        self.output.unlink()
        self.loaders["hacksoc"].side_effect = None
        record = dict(self.row("Talk", "hacksoc"), organiser="su-213")
        self.loaders["hacksoc"].return_value = ([], [record])
        refresh.main()
        result = json.loads(self.output.read_text())
        self.assertEqual(
            result["organisers"][0]["id"], result["events"][0]["organiser"]
        )
        self.assertEqual(result["organisers"][0]["source"], "union")

    def test_total_failure_leaves_the_previous_snapshot_intact(self):
        before = self.output.read_bytes()
        with self.assertRaisesRegex(RuntimeError, "Every source failed"):
            refresh.main()
        self.assertEqual(self.output.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
