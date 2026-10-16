"""The frequency parser and the clock rules. Everything it returns is a suggestion for a person to confirm; none of it is advice."""
from datetime import date

import pytest

from carecircle import schedule as s


@pytest.mark.parametrize("text,times", [
    ("once daily", ["08:00"]), ("OD", ["08:00"]), ("1 time a day", ["08:00"]), ("daily", ["08:00"]), ("every day", ["08:00"]),
    ("twice daily", ["08:00", "20:00"]), ("BD", ["08:00", "20:00"]), ("bid", ["08:00", "20:00"]), ("2 times a day", ["08:00", "20:00"]),
    ("every 12 hours", ["08:00", "20:00"]), ("twice a day with food", ["08:00", "20:00"]), ("TWICE DAILY WITH MEALS", ["08:00", "20:00"]),
    ("TDS", ["08:00", "14:00", "20:00"]), ("three times a day", ["08:00", "14:00", "20:00"]), ("thrice daily", ["08:00", "14:00", "20:00"]),
    ("every 8 hours", ["08:00", "14:00", "20:00"]), ("QID", ["06:00", "12:00", "18:00", "00:00"]), ("four times daily", ["06:00", "12:00", "18:00", "00:00"]),
    ("at bedtime", ["21:00"]), ("at night", ["21:00"]), ("every night", ["21:00"]), ("HS", ["21:00"]),
    ("each morning, empty stomach", ["08:00"]), ("once daily in the morning", ["08:00"]), ("before breakfast", ["08:00"]),
    ("every evening", ["18:00"]), ("din mein do baar", ["08:00", "20:00"]), ("raat ko", ["21:00"]), ("subah", ["08:00"]),
    ("twice daily for 7 days", ["08:00", "20:00"]),
])
def test_written_frequencies_become_suggested_times(text, times):
    r = s.suggest(text)
    assert r["times"] == times and r["understood"] and r["suggested"] is True, (text, r)
    assert not r["as_needed"]


@pytest.mark.parametrize("text", ["as needed", "when needed", "PRN", "SOS", "take one if needed for itching", "once daily as needed"])
def test_a_medicine_taken_when_needed_has_no_slots_to_miss(text):
    r = s.suggest(text)
    assert r["as_needed"] and r["times"] == [] and r["understood"]


@pytest.mark.parametrize("text", ["weekly", "once a week", "every 3 days", "every other day", "alternate days", "monthly", "every 2 weeks"])
def test_a_pattern_that_is_not_daily_is_not_guessed(text):
    r = s.suggest(text)
    assert r["times"] == [] and not r["understood"] and "by hand" in r["why"]


@pytest.mark.parametrize("text", ["", "   ", "as directed", "xyz", "see leaflet", None])
def test_unreadable_or_missing_frequency_suggests_nothing_and_says_why(text):
    r = s.suggest(text)
    assert r["times"] == [] and not r["understood"] and r["why"]


@pytest.mark.parametrize("text,days", [("twice daily for 7 days", 7), ("once a day for 2 weeks", 14), ("for 1 month", 30), ("daily for 400 days", None), ("twice daily", None)])
def test_a_short_course_is_noticed(text, days):
    assert s.suggest(text)["ends_in_days"] == days


def test_confirmed_times_are_checked_and_ordered_not_quietly_fixed():
    assert s.clean_times(["20:00", "08:00"]) == ["08:00", "20:00"]
    for bad in (["8:00"], ["24:00"], ["08:60"], ["08:00", "08:00"], ["8am"], [f"0{i}:00" for i in range(7)], "08:00", [800]):
        with pytest.raises(ValueError):
            s.clean_times(bad)


def test_the_circles_time_zone_decides_the_day_a_slot_belongs_to():
    # 2026-10-16 20:00 UTC is already the 17th in India (01:30 IST) but still the 16th in New York
    ms = int(__import__("datetime").datetime(2026, 10, 16, 20, 0, tzinfo=__import__("datetime").timezone.utc).timestamp() * 1000)
    assert s.local_date(ms, "Asia/Kolkata") == date(2026, 10, 17)
    assert s.local_date(ms, "America/New_York") == date(2026, 10, 16)
    assert s.local_date(ms, "UTC") == date(2026, 10, 16)
    with pytest.raises(ValueError):
        s.zone("Mars/Olympus")
    assert s.slot_moment_ms(date(2026, 10, 17), "08:00", "Asia/Kolkata") == int(__import__("datetime").datetime(2026, 10, 17, 2, 30, tzinfo=__import__("datetime").timezone.utc).timestamp() * 1000)


def test_a_course_of_seven_days_ends_on_the_seventh_day():
    start = s.slot_moment_ms(date(2026, 10, 1), "09:00", "Asia/Kolkata")
    assert s.end_date(start, 7, "Asia/Kolkata") == "2026-10-07"
    assert s.end_date(start, 1, "Asia/Kolkata") == "2026-10-01"


def test_slot_states_follow_the_clock_and_never_judge_the_person():
    m = s.slot_moment_ms(date(2026, 10, 17), "08:00", "Asia/Kolkata")
    mins = lambda n: m + n * 60000  # noqa: E731
    assert s.slot_state(mins(-61), m, False) == "upcoming"
    assert s.slot_state(mins(-60), m, False) == "due" and s.slot_state(mins(0), m, False) == "due" and s.slot_state(mins(90), m, False) == "due"
    assert s.slot_state(mins(91), m, False) == "not_marked"
    assert s.slot_state(mins(-300), m, True) == "given" and s.slot_state(mins(600), m, True) == "given"
