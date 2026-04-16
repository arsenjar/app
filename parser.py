"""
Natural language date + task-type extraction.

Examples:
  "buy milk tomorrow 6pm"        -> text="buy milk", due=<tomorrow 18:00>, type="task"
  "meeting with Alex Friday 3pm" -> text="meeting with Alex", due=<friday 15:00>, type="meeting"
  "deadline report Monday"       -> text="deadline report", due=<monday 00:00>, type="deadline"
"""

import re
from datetime import datetime

try:
    import dateparser
    HAS_DATEPARSER = True
except ImportError:
    HAS_DATEPARSER = False

MEETING_KEYWORDS = {"meeting", "call", "zoom", "sync", "interview", "standup", "скайп", "встреча", "звонок"}
DEADLINE_KEYWORDS = {"deadline", "дедлайн", "сдать", "submit", "due"}

# Patterns that look like date/time hints — we'll try to extract them
DATE_HINT_PATTERN = re.compile(
    r'\b('
    r'today|tomorrow|yesterday|'
    r'monday|tuesday|wednesday|thursday|friday|saturday|sunday|'
    r'понедельник|вторник|среда|четверг|пятница|суббота|воскресенье|'
    r'сегодня|завтра|послезавтра|'
    r'\d{1,2}[:/]\d{2}(?:\s*(?:am|pm))?|'     # 3:00, 15:00, 3pm
    r'\d{1,2}\s*(?:am|pm)|'                    # 3pm, 10am
    r'\d{1,2}\s+(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\w*|'  # 15 march
    r'next\s+\w+'                               # next week, next monday
    r')',
    re.IGNORECASE
)


def detect_type(text: str) -> str:
    lower = text.lower()
    for kw in MEETING_KEYWORDS:
        if kw in lower:
            return "meeting"
    for kw in DEADLINE_KEYWORDS:
        if kw in lower:
            return "deadline"
    return "task"


def parse_task(raw: str) -> dict:
    """
    Returns dict with keys: text, due_at (datetime|None), task_type (str), duration_min (int)
    """
    task_type = detect_type(raw)
    due_at = None

    if HAS_DATEPARSER:
        # Try to parse the whole string as containing a date
        settings = {
            "PREFER_DATES_FROM": "future",
            "RETURN_AS_TIMEZONE_AWARE": False,
            "DATE_ORDER": "DMY",
        }
        parsed = dateparser.parse(raw, settings=settings)
        if parsed and parsed > datetime.now():
            due_at = parsed
            # Strip the date part from the text (best-effort)
            clean = DATE_HINT_PATTERN.sub("", raw).strip(" ,;-")
            text = clean if len(clean) > 3 else raw
        else:
            text = raw
    else:
        text = raw

    # Duration hint: "1h", "90min", "2 hours"
    duration_min = 0
    dur_match = re.search(r'(\d+)\s*(h|hour|час|min|minute|минут)', text, re.IGNORECASE)
    if dur_match:
        val = int(dur_match.group(1))
        unit = dur_match.group(2).lower()
        duration_min = val * 60 if unit.startswith('h') or unit.startswith('ч') else val
        text = text[:dur_match.start()].strip() + text[dur_match.end():].strip()

    return {
        "text": text.strip() or raw.strip(),
        "due_at": due_at,
        "task_type": task_type,
        "duration_min": duration_min,
    }
