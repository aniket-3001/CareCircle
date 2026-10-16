"""Turn the frequency a label SAYS into times a person can confirm. Nothing here decides when a medicine should be taken.

The label says "twice daily"; this proposes two clock times (08:00 and 20:00) as a starting point, flagged as suggested, and a carer sets the real ones
from the pack. Until someone confirms, nothing is scheduled and no reminder exists. Text it cannot read gives no times and says why: it never guesses.

  suggest("BD")                 -> {"times": ["08:00", "20:00"], "label": "twice a day", "as_needed": False, "ends_in_days": None, "understood": True}
  suggest("at night")           -> {"times": ["21:00"], ...}
  suggest("as needed")          -> {"times": [], "as_needed": True, ...}             (a medicine taken when needed has no slots to miss)
  suggest("every 3 days")       -> {"times": [], "understood": False, "why": "..."}   (not a daily pattern: set it by hand)
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

MAX_SLOTS = 6
HHMM = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")

# (pattern, times, label); the first pattern that matches wins, so the more specific ones come first
_PATTERNS: list[tuple[str, list[str], str]] = [
    (r"\b(qid|qds|four times|4 times|4x|four a day|every 6 (hours|hrs|h)|6 hourly|6 hrly)\b", ["06:00", "12:00", "18:00", "00:00"], "four times a day"),
    (r"\b(tds|tid|thrice|three times|3 times|3x|three a day|every 8 (hours|hrs|h)|8 hourly|8 hrly)\b", ["08:00", "14:00", "20:00"], "three times a day"),
    (r"\b(bd|bid|bds|twice|two times|2 times|2x|two a day|every 12 (hours|hrs|h)|12 hourly|12 hrly|din mein do baar|do baar)\b", ["08:00", "20:00"], "twice a day"),
    (r"\b(od|qd|once|one time|1 time|1x|daily|every day|each day|everyday|a day|per day|roz|din mein ek baar)\b", ["08:00"], "once a day"),
    (r"\b(at bedtime|bedtime|at night|each night|every night|nightly|hs|raat ko|raat mein|before bed|before sleep)\b", ["21:00"], "at night"),
    (r"\b(in the morning|each morning|every morning|morning|am|subah|before breakfast|after breakfast|with breakfast)\b", ["08:00"], "in the morning"),
    (r"\b(in the evening|each evening|every evening|evening|shaam)\b", ["18:00"], "in the evening"),
    (r"\b(at noon|midday|lunch|afternoon|dopahar)\b", ["13:00"], "at midday"),
]
_AS_NEEDED = re.compile(r"\b(as needed|when needed|if needed|prn|sos|only if|when required|jab zaroorat|zaroorat par)\b", re.I)
_NOT_DAILY = re.compile(r"\b(weekly|once a week|every week|every (\d+|two|three|four|other) days?|alternate days?|fortnight\w*|monthly|once a month|every other day|every \d+ weeks?)\b", re.I)
_FOR = re.compile(r"\bfor\s+(\d{1,3})\s*(day|days|week|weeks|month|months)\b", re.I)


def valid_time(t: str) -> bool:
    return isinstance(t, str) and HHMM.match(t) is not None


def suggest(freq_text: str) -> dict:
    """What the written frequency suggests. Never authoritative: the person confirms or changes it."""
    text = " ".join((freq_text or "").lower().split())
    out = {"times": [], "label": "", "as_needed": False, "ends_in_days": None, "understood": False, "why": "", "suggested": True}
    m = _FOR.search(text)
    if m:
        n, unit = int(m.group(1)), m.group(2).lower()
        days = n * (7 if unit.startswith("week") else 30 if unit.startswith("month") else 1)
        out["ends_in_days"] = days if 0 < days <= 366 else None
    if not text:
        out["why"] = "No frequency was written, so there is nothing to suggest. Set the times from the pack."
        return out
    if _AS_NEEDED.search(text):
        out.update(as_needed=True, understood=True, label="as needed", why="Taken only when needed: there are no fixed times to remind about.")
        return out
    if _NOT_DAILY.search(text):
        out["why"] = "That is not a once-a-day pattern, so no times are suggested. Set it by hand if you want it on the checklist."
        return out
    for pattern, times, label in _PATTERNS:
        if re.search(pattern, text):
            out.update(times=list(times), label=label, understood=True,
                       why=f"The label says {label}. These times are only a starting point: set the ones on the pack.")
            return out
    out["why"] = "The frequency could not be read, so no times are suggested. Set them by hand."
    return out


def clean_times(times: list) -> list[str]:
    """The confirmed times: valid, distinct, in clock order, at most MAX_SLOTS. Refuses anything else rather than fixing it quietly."""
    if not isinstance(times, list):
        raise ValueError("times must be a list of HH:MM")
    if len(times) > MAX_SLOTS:
        raise ValueError(f"at most {MAX_SLOTS} times a day")
    bad = [t for t in times if not valid_time(t)]
    if bad:
        raise ValueError(f"times look like 08:00 (24-hour); not understood: {bad[:3]}")
    if len(set(times)) != len(times):
        raise ValueError("the same time is listed twice")
    return sorted(times)


def zone(name: Optional[str]) -> ZoneInfo:
    try:
        return ZoneInfo(name or "Asia/Kolkata")
    except (ZoneInfoNotFoundError, ValueError, KeyError):
        raise ValueError(f"unknown time zone {name!r}; use a name like Asia/Kolkata") from None


def local_date(now_ms: int, tz: str) -> date:
    return datetime.fromtimestamp(now_ms / 1000, tz=timezone.utc).astimezone(zone(tz)).date()


def slot_moment_ms(day: date, hhmm: str, tz: str) -> int:
    """When `hhmm` on local `day` happens, in epoch milliseconds."""
    h, m = int(hhmm[:2]), int(hhmm[3:])
    return int(datetime(day.year, day.month, day.day, h, m, tzinfo=zone(tz)).timestamp() * 1000)


def end_date(start_ms: int, days: int, tz: str) -> str:
    """The last day a short course covers: it starts on its first day and runs `days` days (7 days from the 1st ends on the 7th)."""
    return (local_date(start_ms, tz) + timedelta(days=days - 1)).isoformat()


# how a slot reads against the clock. Wording is about the RECORD ("not marked given"), never about the person's health.
EARLY_MIN, GRACE_MIN = 60, 90


def slot_state(now_ms: int, moment_ms: int, given: bool) -> str:
    """given | upcoming | due | not_marked. 'due' runs from an hour before to 90 minutes after; later it is 'not marked given yet'."""
    if given:
        return "given"
    delta = (now_ms - moment_ms) / 60000
    if delta < -EARLY_MIN:
        return "upcoming"
    return "due" if delta <= GRACE_MIN else "not_marked"
