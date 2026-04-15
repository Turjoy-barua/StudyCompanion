from __future__ import annotations

import os
import sqlite3
from collections import defaultdict
from datetime import date, datetime, timedelta
from functools import lru_cache
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "database.db"
KAGGLE_QUOTES_DATASET = "mattimansha/inspirational-quotes"
KAGGLE_QUOTES_FILE_PATH = os.environ.get("KAGGLE_QUOTES_FILE_PATH", "")

TITLE_THRESHOLDS = [
    (0, "Beginner"),
    (300, "Focused Learner"),
    (900, "Study Beast"),
    (1800, "Master of Consistency"),
]

FALLBACK_QUOTES = [
    {
        "text": "Success is the sum of small efforts, repeated day in and day out.",
        "author": "Robert Collier",
    },
    {
        "text": "The expert in anything was once a beginner.",
        "author": "Helen Hayes",
    },
    {
        "text": "It always seems impossible until it is done.",
        "author": "Nelson Mandela",
    },
    {
        "text": "Do not wait to strike till the iron is hot, but make it hot by striking.",
        "author": "William Butler Yeats",
    },
    {
        "text": "A little progress each day adds up to big results.",
        "author": "Satya Nani",
    },
]


def get_connection() -> sqlite3.Connection:
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def init_db() -> None:
    with get_connection() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS study_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                subject TEXT NOT NULL,
                duration_minutes INTEGER NOT NULL CHECK(duration_minutes > 0),
                session_date TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )


def add_session(subject: str, duration_minutes: int, session_date: str | None = None) -> None:
    normalized_subject = " ".join(subject.strip().split())
    if not normalized_subject:
        raise ValueError("Subject is required.")
    if duration_minutes <= 0:
        raise ValueError("Duration must be greater than zero.")

    session_day = session_date or date.today().isoformat()
    try:
        datetime.strptime(session_day, "%Y-%m-%d")
    except ValueError as exc:
        raise ValueError("Session date must use YYYY-MM-DD format.") from exc

    created_at = datetime.now().isoformat(timespec="seconds")
    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO study_sessions (subject, duration_minutes, session_date, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (normalized_subject, duration_minutes, session_day, created_at),
        )


def fetch_sessions(limit: int | None = None) -> list[sqlite3.Row]:
    query = """
        SELECT id, subject, duration_minutes, session_date, created_at
        FROM study_sessions
        ORDER BY session_date DESC, created_at DESC, id DESC
    """
    params: tuple[int, ...] = ()
    if limit is not None:
        query += " LIMIT ?"
        params = (limit,)

    with get_connection() as connection:
        return connection.execute(query, params).fetchall()


def _calculate_streak(session_dates: set[date]) -> int:
    streak = 0
    cursor = date.today()
    if cursor not in session_dates and (cursor - timedelta(days=1)) not in session_dates:
        return 0
    if cursor not in session_dates:
        cursor -= timedelta(days=1)

    while cursor in session_dates:
        streak += 1
        cursor -= timedelta(days=1)
    return streak


def _resolve_title(xp: int) -> str:
    current_title = TITLE_THRESHOLDS[0][1]
    for threshold, title in TITLE_THRESHOLDS:
        if xp >= threshold:
            current_title = title
    return current_title


def _pick_daily_item(items: list[dict[str, str]]) -> dict[str, str]:
    if not items:
        return {"text": "", "author": ""}
    day_index = date.today().toordinal() % len(items)
    return items[day_index]


def _extract_quote_records(dataframe) -> list[dict[str, str]]:
    quote_columns = ("quote", "text", "quotation", "quotes")
    author_columns = ("author", "name", "speaker", "person")

    normalized_columns = {str(column).strip().lower(): column for column in dataframe.columns}
    quote_column = next((normalized_columns[name] for name in quote_columns if name in normalized_columns), None)
    author_column = next((normalized_columns[name] for name in author_columns if name in normalized_columns), None)

    if quote_column is None:
        return []

    records: list[dict[str, str]] = []
    for _, row in dataframe.iterrows():
        quote_text = " ".join(str(row[quote_column]).split()).strip()
        if not quote_text or quote_text.lower() == "nan":
            continue

        author_text = ""
        if author_column is not None:
            author_text = " ".join(str(row[author_column]).split()).strip()
            if author_text.lower() == "nan":
                author_text = ""

        records.append({"text": quote_text, "author": author_text})
    return records


@lru_cache(maxsize=1)
def _load_kaggle_quotes() -> list[dict[str, str]]:
    if not KAGGLE_QUOTES_FILE_PATH:
        return []

    try:
        import kagglehub
        from kagglehub import KaggleDatasetAdapter
    except ImportError:
        return []

    try:
        dataframe = kagglehub.load_dataset(
            KaggleDatasetAdapter.PANDAS,
            KAGGLE_QUOTES_DATASET,
            KAGGLE_QUOTES_FILE_PATH,
        )
    except Exception:
        return []

    return _extract_quote_records(dataframe)


def get_daily_motivation() -> dict[str, str]:
    quotes = _load_kaggle_quotes() or FALLBACK_QUOTES
    quote = _pick_daily_item(quotes)
    return {
        "text": quote["text"],
        "author": quote["author"] or "Study Companion",
        "source": "kaggle" if quotes is not FALLBACK_QUOTES else "fallback",
    }


def get_dashboard_data() -> dict:
    sessions = fetch_sessions()
    today = date.today()
    today_iso = today.isoformat()
    current_month = today.month
    current_year = today.year

    total_minutes = 0
    today_minutes = 0
    today_sessions = 0
    subject_totals: dict[str, int] = defaultdict(int)
    session_dates: set[date] = set()
    activity_map: dict[str, int] = {}

    for offset in range(6, -1, -1):
        day = today - timedelta(days=offset)
        activity_map[day.isoformat()] = 0

    recent_sessions = []
    for session in sessions:
        duration = int(session["duration_minutes"])
        session_day = datetime.strptime(session["session_date"], "%Y-%m-%d").date()
        if session_day.year == current_year and session_day.month == current_month:
            total_minutes += duration
        subject_totals[session["subject"]] += duration
        session_dates.add(session_day)

        if session["session_date"] == today_iso:
            today_minutes += duration
            today_sessions += 1

        if session["session_date"] in activity_map:
            activity_map[session["session_date"]] += duration

        if len(recent_sessions) < 10:
            recent_sessions.append(
                {
                    "id": session["id"],
                    "subject": session["subject"],
                    "duration_minutes": duration,
                    "session_date": session["session_date"],
                    "created_at": session["created_at"],
                }
            )

    xp = total_minutes * 10
    level = (xp // 500) + 1 if xp else 1
    subject_breakdown = [
        {"subject": subject, "minutes": minutes}
        for subject, minutes in sorted(subject_totals.items(), key=lambda item: item[1], reverse=True)
    ]
    weekly_activity = [
        {
            "date": session_date,
            "label": datetime.strptime(session_date, "%Y-%m-%d").strftime("%a"),
            "minutes": minutes,
        }
        for session_date, minutes in activity_map.items()
    ]
    motivation = get_daily_motivation()

    return {
        "today_minutes": today_minutes,
        "today_sessions": today_sessions,
        "total_minutes": total_minutes,
        "streak": _calculate_streak(session_dates),
        "xp": xp,
        "level": level,
        "title": _resolve_title(xp),
        "subject_breakdown": subject_breakdown,
        "weekly_activity": weekly_activity,
        "recent_sessions": recent_sessions,
        "motivation": motivation,
    }
