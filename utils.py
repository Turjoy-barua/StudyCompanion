from __future__ import annotations

import csv
import os
import random
import sqlite3
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

from supabase_client import get_supabase_client


BASE_DIR = Path(__file__).resolve().parent
DB_PATH = Path("/tmp/study-companion.db") if os.environ.get("VERCEL") else BASE_DIR / "database.db"
QUOTES_CSV_PATH = BASE_DIR / "insparation.csv"
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

DEFAULT_PLAN_SUBJECTS = [
    "Mathematics",
    "Physics",
    "Chemistry",
]

SessionRecord = dict[str, object]
AcademicItemRecord = dict[str, object]


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
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS academic_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                item_kind TEXT NOT NULL,
                exam_type TEXT,
                importance TEXT NOT NULL,
                confidence_percent INTEGER NOT NULL CHECK(confidence_percent >= 0 AND confidence_percent <= 100),
                due_date TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )


def _get_supabase() -> object | None:
    try:
        return get_supabase_client()
    except Exception:
        return None


def _normalize_session_record(record: dict[str, object]) -> SessionRecord:
    return {
        "id": record.get("id"),
        "subject": record.get("subject", ""),
        "duration_minutes": int(record.get("duration_minutes", 0) or 0),
        "session_date": str(record.get("session_date", "")),
        "created_at": str(record.get("created_at", "")),
    }


def _normalize_academic_item_record(record: dict[str, object]) -> AcademicItemRecord:
    return {
        "id": record.get("id"),
        "title": record.get("title", ""),
        "item_kind": record.get("item_kind", ""),
        "exam_type": record.get("exam_type") or "",
        "importance": record.get("importance", ""),
        "confidence_percent": int(record.get("confidence_percent", 0) or 0),
        "due_date": str(record.get("due_date", "")),
        "created_at": str(record.get("created_at", "")),
    }


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
    supabase = _get_supabase()
    if supabase is not None:
        try:
            supabase.table("study_sessions").insert(
                {
                    "subject": normalized_subject,
                    "duration_minutes": duration_minutes,
                    "session_date": session_day,
                    "created_at": created_at,
                }
            ).execute()
            return
        except Exception:
            pass

    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO study_sessions (subject, duration_minutes, session_date, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (normalized_subject, duration_minutes, session_day, created_at),
        )


def fetch_sessions(limit: int | None = None) -> list[SessionRecord]:
    supabase = _get_supabase()
    if supabase is not None:
        try:
            query = supabase.table("study_sessions").select(
                "id, subject, duration_minutes, session_date, created_at"
            ).order("session_date", desc=True).order("created_at", desc=True).order("id", desc=True)
            if limit is not None:
                query = query.limit(limit)
            response = query.execute()
            return [_normalize_session_record(record) for record in response.data or []]
        except Exception:
            pass

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
        rows = connection.execute(query, params).fetchall()
    return [_normalize_session_record(dict(row)) for row in rows]


def add_academic_item(
    title: str,
    item_kind: str,
    exam_type: str,
    importance: str,
    confidence_percent: int,
    due_date: str,
) -> None:
    normalized_title = " ".join(title.strip().split())
    normalized_kind = item_kind.strip().lower()
    normalized_exam_type = " ".join(exam_type.strip().split())
    normalized_importance = importance.strip().lower()

    if not normalized_title:
        raise ValueError("Title is required.")
    if normalized_kind not in {"exam", "project"}:
        raise ValueError("Type must be exam or project.")
    if normalized_importance not in {"critical", "high", "medium", "low"}:
        raise ValueError("Importance must be critical, high, medium, or low.")
    if not 0 <= confidence_percent <= 100:
        raise ValueError("Confidence must be between 0 and 100.")

    try:
        datetime.strptime(due_date, "%Y-%m-%d")
    except ValueError as exc:
        raise ValueError("Due date must use YYYY-MM-DD format.") from exc

    if normalized_kind == "project":
        normalized_exam_type = ""
    elif not normalized_exam_type:
        raise ValueError("Exam type is required for exams.")

    created_at = datetime.now().isoformat(timespec="seconds")
    supabase = _get_supabase()
    if supabase is not None:
        try:
            supabase.table("academic_items").insert(
                {
                    "title": normalized_title,
                    "item_kind": normalized_kind,
                    "exam_type": normalized_exam_type,
                    "importance": normalized_importance,
                    "confidence_percent": confidence_percent,
                    "due_date": due_date,
                    "created_at": created_at,
                }
            ).execute()
            return
        except Exception:
            pass

    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO academic_items (
                title,
                item_kind,
                exam_type,
                importance,
                confidence_percent,
                due_date,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                normalized_title,
                normalized_kind,
                normalized_exam_type,
                normalized_importance,
                confidence_percent,
                due_date,
                created_at,
            ),
        )


def fetch_academic_items(limit: int | None = None) -> list[AcademicItemRecord]:
    supabase = _get_supabase()
    if supabase is not None:
        try:
            query = supabase.table("academic_items").select(
                "id, title, item_kind, exam_type, importance, confidence_percent, due_date, created_at"
            ).order("due_date", desc=False).order("created_at", desc=False).order("id", desc=False)
            if limit is not None:
                query = query.limit(limit)
            response = query.execute()
            return [_normalize_academic_item_record(record) for record in response.data or []]
        except Exception:
            pass

    query = """
        SELECT id, title, item_kind, exam_type, importance, confidence_percent, due_date, created_at
        FROM academic_items
        ORDER BY due_date ASC, created_at ASC, id ASC
    """
    params: tuple[int, ...] = ()
    if limit is not None:
        query += " LIMIT ?"
        params = (limit,)

    with get_connection() as connection:
        rows = connection.execute(query, params).fetchall()
    return [_normalize_academic_item_record(dict(row)) for row in rows]


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


def _pick_random_item(items: list[dict[str, str]]) -> dict[str, str]:
    if not items:
        return {"text": "", "author": ""}
    return random.choice(items)


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


def _load_csv_quotes() -> list[dict[str, str]]:
    if not QUOTES_CSV_PATH.exists():
        return []

    try:
        with QUOTES_CSV_PATH.open(newline="", encoding="utf-8") as csv_file:
            reader = csv.DictReader(csv_file)
            records = []
            for row in reader:
                quote_text = " ".join(str(row.get("Quote", "")).split()).strip()
                category = " ".join(str(row.get("Category", "")).split()).strip()
                if not quote_text:
                    continue
                records.append(
                    {
                        "text": quote_text,
                        "author": category or "Inspiration",
                    }
                )
            return records
    except OSError:
        return []


def get_daily_motivation() -> dict[str, str]:
    quotes = _load_csv_quotes() or FALLBACK_QUOTES
    quote = _pick_random_item(quotes)
    return {
        "text": quote["text"],
        "author": quote["author"] or "Study Companion",
        "source": "csv" if quotes is not FALLBACK_QUOTES else "fallback",
    }


def _build_next_best_action(
    academic_items: list[AcademicItemRecord],
    subject_totals: dict[str, int],
) -> dict:
    today = date.today()
    ranked_actions = []

    for item in academic_items:
        title = item["title"]
        due_date = datetime.strptime(item["due_date"], "%Y-%m-%d").date()
        days_left = (due_date - today).days
        confidence_percent = int(item["confidence_percent"])
        studied_minutes = subject_totals.get(title, 0)
        importance_weight = {"critical": 45, "high": 30, "medium": 18, "low": 8}.get(item["importance"], 0)
        urgency_weight = 40 if days_left <= 0 else max(0, 32 - (days_left * 4))
        confidence_gap = 100 - confidence_percent
        coverage_penalty = min(studied_minutes // 15, 18)
        score = importance_weight + urgency_weight + confidence_gap - coverage_penalty

        if item["item_kind"] == "exam":
            action = "Do a timed problem set and then review only the mistakes."
        else:
            action = "Complete the highest-risk deliverable first, then polish the remaining pieces."

        if days_left <= 0:
            urgency_text = "Deadline is now."
        elif days_left == 1:
            urgency_text = "Due tomorrow."
        else:
            urgency_text = f"Due in {days_left} days."

        ranked_actions.append(
            {
                "title": title,
                "item_kind": item["item_kind"].title(),
                "exam_type": item["exam_type"],
                "importance": item["importance"].title(),
                "confidence_percent": confidence_percent,
                "days_left": days_left,
                "studied_minutes": studied_minutes,
                "score": score,
                "action": action,
                "urgency_text": urgency_text,
            }
        )

    ranked_actions.sort(key=lambda item: item["score"], reverse=True)
    if not ranked_actions:
        return {
            "title": "No urgent exam or project yet",
            "item_kind": "Study",
            "exam_type": "",
            "importance": "Medium",
            "confidence_percent": 0,
            "days_left": None,
            "studied_minutes": 0,
            "score": 0,
            "action": "Add an upcoming exam or project so the planner can predict the most important next move.",
            "urgency_text": "Nothing to rank yet.",
        }

    return ranked_actions[0]


def _build_daily_forced_plan(sessions: list[SessionRecord], academic_items: list[AcademicItemRecord]) -> dict:
    today = date.today()
    subject_minutes: dict[str, int] = defaultdict(int)
    last_studied: dict[str, date] = {}

    for session in sessions:
        subject = session["subject"]
        session_day = datetime.strptime(session["session_date"], "%Y-%m-%d").date()
        duration = int(session["duration_minutes"])
        subject_minutes[subject] += duration
        if subject not in last_studied or session_day > last_studied[subject]:
            last_studied[subject] = session_day

    ranked_subjects = sorted(
        subject_minutes.keys(),
        key=lambda subject: (
            last_studied.get(subject, date.min),
            subject_minutes[subject],
            subject.lower(),
        ),
    )

    urgent_items = []
    for item in academic_items:
        due_date = datetime.strptime(item["due_date"], "%Y-%m-%d").date()
        days_left = (due_date - today).days
        urgency_score = (
            max(days_left, -7),
            {"critical": 0, "high": 1, "medium": 2, "low": 3}.get(item["importance"], 4),
            int(item["confidence_percent"]),
        )
        urgent_items.append(
            {
                "title": item["title"],
                "item_kind": item["item_kind"].title(),
                "exam_type": item["exam_type"],
                "importance": item["importance"].title(),
                "confidence_percent": int(item["confidence_percent"]),
                "days_left": days_left,
                "urgency_score": urgency_score,
            }
        )

    urgent_items.sort(key=lambda item: item["urgency_score"])

    selected_subjects: list[dict[str, str | int]] = []
    for item in urgent_items[:3]:
        selected_subjects.append(
            {
                "subject": item["title"],
                "item_kind": item["item_kind"],
                "exam_type": item["exam_type"],
                "importance": item["importance"],
                "confidence_percent": item["confidence_percent"],
                "days_left": item["days_left"],
                "source": "upcoming",
            }
        )

    for subject in ranked_subjects:
        if len(selected_subjects) >= 3:
            break
        if any(entry["subject"] == subject for entry in selected_subjects):
            continue
        selected_subjects.append(
            {
                "subject": subject,
                "item_kind": "Study",
                "exam_type": "",
                "importance": "",
                "confidence_percent": 0,
                "days_left": None,
                "source": "history",
            }
        )

    while len(selected_subjects) < 3:
        fallback_subject = DEFAULT_PLAN_SUBJECTS[len(selected_subjects) % len(DEFAULT_PLAN_SUBJECTS)]
        if any(entry["subject"] == fallback_subject for entry in selected_subjects):
            continue
        selected_subjects.append(
            {
                "subject": fallback_subject,
                "item_kind": "Study",
                "exam_type": "",
                "importance": "",
                "confidence_percent": 0,
                "days_left": None,
                "source": "fallback",
            }
        )

    base_blocks = [50, 35, 25]
    energy_cycle = [
        "Start with the hardest chapter or problem set only.",
        "Review notes, examples, and mistakes without switching subjects.",
        "End with active recall: solve, recite, or summarize from memory.",
    ]

    blocks = []
    total_minutes = 0
    for index, plan_item in enumerate(selected_subjects):
        subject = str(plan_item["subject"])
        duration = base_blocks[index]
        total_minutes += duration
        if plan_item["source"] == "upcoming":
            days_left = int(plan_item["days_left"])
            if days_left <= 0:
                reason = f"{plan_item['item_kind']} deadline is here. Do not postpone it."
            elif days_left == 1:
                reason = f"{plan_item['item_kind']} is due tomorrow. This gets priority now."
            else:
                reason = f"{plan_item['item_kind']} is due in {days_left} days and confidence is {plan_item['confidence_percent']}%."
        else:
            last_day = last_studied.get(subject)
            if last_day is None:
                reason = "New priority today. Build momentum."
            else:
                days_away = (today - last_day).days
                reason = "You have not touched this recently." if days_away >= 2 else "Keep this subject warm today."

        blocks.append(
            {
                "order": index + 1,
                "subject": subject,
                "item_kind": plan_item["item_kind"],
                "exam_type": plan_item["exam_type"],
                "duration_minutes": duration,
                "instruction": energy_cycle[index],
                "reason": reason,
            }
        )

    return {
        "headline": "Daily forced plan",
        "summary": "No deciding. Follow these blocks in order and finish the day clean.",
        "total_minutes": total_minutes,
        "blocks": blocks,
    }


def get_dashboard_data() -> dict:
    sessions = fetch_sessions()
    academic_items = fetch_academic_items(limit=8)
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

    xp = total_minutes
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
    forced_plan = _build_daily_forced_plan(sessions, academic_items)
    next_best_action = _build_next_best_action(academic_items, subject_totals)
    upcoming_items = []
    for item in academic_items:
        due_date = datetime.strptime(item["due_date"], "%Y-%m-%d").date()
        days_left = (due_date - today).days
        upcoming_items.append(
            {
                "id": item["id"],
                "title": item["title"],
                "item_kind": item["item_kind"].title(),
                "exam_type": item["exam_type"],
                "importance": item["importance"].title(),
                "confidence_percent": int(item["confidence_percent"]),
                "due_date": item["due_date"],
                "days_left": days_left,
            }
        )

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
        "forced_plan": forced_plan,
        "next_best_action": next_best_action,
        "upcoming_items": upcoming_items,
    }
