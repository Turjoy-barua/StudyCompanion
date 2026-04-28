from __future__ import annotations

import csv
import os
import random
import sqlite3
from collections import defaultdict
from datetime import date, datetime, timedelta
from math import ceil
from pathlib import Path

from supabase_client import create_supabase_client
from study_planner import Chapter, generate_study_plan, plan_to_dict


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

SessionRecord = dict[str, object]
AcademicItemRecord = dict[str, object]
StudySubjectRecord = dict[str, object]
SUPABASE_ENABLED = bool(os.environ.get("SUPABASE_URL") and os.environ.get("SUPABASE_ANON_KEY"))
MAX_QUOTE_WORDS = 20


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
                subject_name TEXT,
                item_kind TEXT NOT NULL,
                exam_type TEXT,
                chapters TEXT,
                importance TEXT NOT NULL,
                confidence_percent INTEGER NOT NULL CHECK(confidence_percent >= 0 AND confidence_percent <= 100),
                due_date TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        try:
            connection.execute("ALTER TABLE academic_items ADD COLUMN chapters TEXT")
        except sqlite3.OperationalError:
            pass
        try:
            connection.execute("ALTER TABLE academic_items ADD COLUMN subject_name TEXT")
        except sqlite3.OperationalError:
            pass
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS study_subjects (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                priority TEXT NOT NULL,
                confidence_percent INTEGER NOT NULL CHECK(confidence_percent >= 0 AND confidence_percent <= 100),
                weekly_goal_minutes INTEGER NOT NULL CHECK(weekly_goal_minutes >= 0),
                notes TEXT,
                created_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS study_chapter_progress (
                chapter_id TEXT PRIMARY KEY,
                confidence_level INTEGER NOT NULL CHECK(confidence_level >= 1 AND confidence_level <= 5),
                is_finished INTEGER NOT NULL DEFAULT 0,
                past_study_minutes INTEGER NOT NULL DEFAULT 0 CHECK(past_study_minutes >= 0),
                estimated_total_minutes INTEGER,
                difficulty INTEGER CHECK(difficulty >= 1 AND difficulty <= 5),
                updated_at TEXT NOT NULL
            )
            """
        )
        


def _get_supabase(supabase: object | None = None) -> object | None:
    if supabase is not None:
        return supabase
    if not SUPABASE_ENABLED:
        return None
    try:
        return create_supabase_client()
    except Exception:
        return None


def _is_missing_supabase_column(exc: Exception, column_name: str) -> bool:
    error_text = str(exc)
    return column_name in error_text and (
        "42703" in error_text
        or "PGRST204" in error_text
        or "schema cache" in error_text
        or "Could not find" in error_text
    )


def _is_missing_supabase_table(exc: Exception, table_name: str) -> bool:
    error_text = str(exc)
    return table_name in error_text and (
        "42P01" in error_text
        or "PGRST205" in error_text
        or "schema cache" in error_text
        or "Could not find the table" in error_text
    )


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
        "subject_name": record.get("subject_name") or record.get("title", ""),
        "item_kind": record.get("item_kind", ""),
        "exam_type": record.get("exam_type") or "",
        "chapters": record.get("chapters") or "",
        "importance": record.get("importance", ""),
        "confidence_percent": int(record.get("confidence_percent", 0) or 0),
        "due_date": str(record.get("due_date", "")),
        "created_at": str(record.get("created_at", "")),
    }


def _normalize_study_subject_record(record: dict[str, object]) -> StudySubjectRecord:
    return {
        "id": record.get("id"),
        "name": record.get("name", ""),
        "priority": record.get("priority", ""),
        "confidence_percent": int(record.get("confidence_percent", 0) or 0),
        "weekly_goal_minutes": int(record.get("weekly_goal_minutes", 0) or 0),
        "notes": record.get("notes") or "",
        "created_at": str(record.get("created_at", "")),
    }


def _confidence_percent_to_level(confidence_percent: int) -> int:
    return max(1, min(5, ceil(max(0, min(confidence_percent, 100)) / 20)))


def _importance_to_level(importance: str) -> int:
    return {"critical": 5, "high": 4, "medium": 3, "low": 2}.get(importance, 3)


def _split_chapter_titles(raw_chapters: str, fallback_title: str) -> list[str]:
    cleaned = raw_chapters.replace("\n", ",").replace(";", ",")
    chapters = [" ".join(part.strip().split()) for part in cleaned.split(",")]
    chapters = [chapter for chapter in chapters if chapter]
    return chapters or [fallback_title]


def _chapter_id(item_id: object, chapter_index: int) -> str:
    return f"academic:{item_id}:chapter:{chapter_index}"


def fetch_chapter_progress() -> dict[str, dict[str, int | bool | None]]:
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT chapter_id,
                   confidence_level,
                   is_finished,
                   past_study_minutes,
                   estimated_total_minutes,
                   difficulty
            FROM study_chapter_progress
            """
        ).fetchall()

    return {
        str(row["chapter_id"]): {
            "confidence_level": int(row["confidence_level"]),
            "is_finished": bool(row["is_finished"]),
            "past_study_minutes": int(row["past_study_minutes"]),
            "estimated_total_minutes": row["estimated_total_minutes"],
            "difficulty": row["difficulty"],
        }
        for row in rows
    }


def update_chapter_confidence(chapter_id: str, confidence_level: int) -> None:
    normalized_chapter_id = chapter_id.strip()
    if not normalized_chapter_id:
        raise ValueError("Chapter id is required.")
    if not 1 <= confidence_level <= 5:
        raise ValueError("Confidence must be between 1 and 5.")

    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO study_chapter_progress (
                chapter_id,
                confidence_level,
                updated_at
            )
            VALUES (?, ?, ?)
            ON CONFLICT(chapter_id) DO UPDATE SET
                confidence_level = excluded.confidence_level,
                updated_at = excluded.updated_at
            """,
            (normalized_chapter_id, confidence_level, datetime.now().isoformat(timespec="seconds")),
        )


def add_session(
    subject: str,
    duration_minutes: int,
    session_date: str | None = None,
    supabase: object | None = None,
    user_id: str | None = None,
) -> None:
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
    supabase = _get_supabase(supabase)
    if supabase is not None:
        try:
            supabase.table("study_sessions").insert(
                {
                    "user_id": user_id,
                    "subject": normalized_subject,
                    "duration_minutes": duration_minutes,
                    "session_date": session_day,
                    "created_at": created_at,
                }
            ).execute()
            return
        except Exception as exc:
            if SUPABASE_ENABLED:
                raise ValueError(f"Could not save the session to Supabase. {exc}")

    if SUPABASE_ENABLED:
        raise ValueError("Login is required before saving a session.")

    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO study_sessions (subject, duration_minutes, session_date, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (normalized_subject, duration_minutes, session_day, created_at),
        )


def update_session(
    session_id: int,
    subject: str,
    duration_minutes: int,
    session_date: str,
    supabase: object | None = None,
    user_id: str | None = None,
) -> None:
    normalized_subject = " ".join(subject.strip().split())
    if not normalized_subject:
        raise ValueError("Subject is required.")
    if duration_minutes <= 0:
        raise ValueError("Duration must be greater than zero.")

    try:
        datetime.strptime(session_date, "%Y-%m-%d")
    except ValueError as exc:
        raise ValueError("Session date must use YYYY-MM-DD format.") from exc

    supabase = _get_supabase(supabase)
    if supabase is not None:
        try:
            query = supabase.table("study_sessions").update(
                {
                    "subject": normalized_subject,
                    "duration_minutes": duration_minutes,
                    "session_date": session_date,
                }
            ).eq("id", session_id)
            if user_id:
                query = query.eq("user_id", user_id)
            query.execute()
            return
        except Exception as exc:
            if SUPABASE_ENABLED:
                raise ValueError(f"Could not update the session in Supabase. {exc}")

    if SUPABASE_ENABLED:
        raise ValueError("Login is required before updating a session.")

    with get_connection() as connection:
        connection.execute(
            """
            UPDATE study_sessions
            SET subject = ?, duration_minutes = ?, session_date = ?
            WHERE id = ?
            """,
            (normalized_subject, duration_minutes, session_date, session_id),
        )


def delete_session(
    session_id: int,
    supabase: object | None = None,
    user_id: str | None = None,
) -> None:
    supabase = _get_supabase(supabase)
    if supabase is not None:
        try:
            query = supabase.table("study_sessions").delete().eq("id", session_id)
            if user_id:
                query = query.eq("user_id", user_id)
            query.execute()
            verify_query = supabase.table("study_sessions").select("id").eq("id", session_id)
            if user_id:
                verify_query = verify_query.eq("user_id", user_id)
            verify_response = verify_query.limit(1).execute()
            if verify_response.data:
                raise ValueError(
                    "Could not delete the session in Supabase. Run the delete RLS policy in supabase_schema.sql."
                )
            return
        except Exception as exc:
            if isinstance(exc, ValueError):
                raise
            if SUPABASE_ENABLED:
                raise ValueError(f"Could not delete the session from Supabase. {exc}")

    if SUPABASE_ENABLED:
        raise ValueError("Login is required before deleting a session.")

    with get_connection() as connection:
        connection.execute("DELETE FROM study_sessions WHERE id = ?", (session_id,))


def fetch_sessions(
    limit: int | None = None,
    supabase: object | None = None,
    user_id: str | None = None,
) -> list[SessionRecord]:
    supabase = _get_supabase(supabase)
    if supabase is not None:
        if SUPABASE_ENABLED and not user_id:
            return []
        try:
            query = supabase.table("study_sessions").select(
                "id, subject, duration_minutes, session_date, created_at, user_id"
            )
            if user_id:
                query = query.eq("user_id", user_id)
            query = query.order("session_date", desc=True).order("created_at", desc=True).order("id", desc=True)
            if limit is not None:
                query = query.limit(limit)
            response = query.execute()
            return [_normalize_session_record(record) for record in response.data or []]
        except Exception:
            if SUPABASE_ENABLED:
                return []

    if SUPABASE_ENABLED:
        return []

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
    subject_name: str,
    item_kind: str,
    exam_type: str,
    chapters: str,
    importance: str,
    confidence_percent: int,
    due_date: str,
    supabase: object | None = None,
    user_id: str | None = None,
) -> None:
    normalized_title = " ".join(title.strip().split())
    normalized_subject_name = " ".join(subject_name.strip().split()) or normalized_title
    normalized_kind = item_kind.strip().lower()
    normalized_exam_type = " ".join(exam_type.strip().split())
    normalized_chapters = " ".join(chapters.strip().split())
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
    supabase = _get_supabase(supabase)
    use_local_fallback = not SUPABASE_ENABLED
    if supabase is not None:
        try:
            payload = {
                "user_id": user_id,
                "title": normalized_title,
                "subject_name": normalized_subject_name,
                "item_kind": normalized_kind,
                "exam_type": normalized_exam_type,
                "chapters": normalized_chapters,
                "importance": normalized_importance,
                "confidence_percent": confidence_percent,
                "due_date": due_date,
                "created_at": created_at,
            }
            missing_optional_columns = ("chapters", "subject_name")
            while True:
                try:
                    supabase.table("academic_items").insert(payload).execute()
                    break
                except Exception as exc:
                    missing_column = next(
                        (
                            column_name
                            for column_name in missing_optional_columns
                            if column_name in payload and _is_missing_supabase_column(exc, column_name)
                        ),
                        None,
                    )
                    if missing_column is None:
                        raise
                    payload.pop(missing_column, None)
            return
        except Exception as exc:
            if _is_missing_supabase_table(exc, "academic_items"):
                use_local_fallback = True
            elif SUPABASE_ENABLED:
                raise ValueError(f"Could not save the upcoming item to Supabase. {exc}")

    if not use_local_fallback and SUPABASE_ENABLED:
        raise ValueError("Login is required before saving an upcoming item.")

    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO academic_items (
                title,
                subject_name,
                item_kind,
                exam_type,
                chapters,
                importance,
                confidence_percent,
                due_date,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                normalized_title,
                normalized_subject_name,
                normalized_kind,
                normalized_exam_type,
                normalized_chapters,
                normalized_importance,
                confidence_percent,
                due_date,
                created_at,
            ),
        )


def update_academic_item(
    item_id: int,
    title: str,
    subject_name: str,
    item_kind: str,
    exam_type: str,
    chapters: str,
    importance: str,
    confidence_percent: int,
    due_date: str,
    supabase: object | None = None,
    user_id: str | None = None,
) -> None:
    normalized_title = " ".join(title.strip().split())
    normalized_subject_name = " ".join(subject_name.strip().split()) or normalized_title
    normalized_kind = item_kind.strip().lower()
    normalized_exam_type = " ".join(exam_type.strip().split())
    normalized_chapters = " ".join(chapters.strip().split())
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

    supabase = _get_supabase(supabase)
    use_local_fallback = not SUPABASE_ENABLED
    if supabase is not None:
        try:
            payload = {
                "title": normalized_title,
                "subject_name": normalized_subject_name,
                "item_kind": normalized_kind,
                "exam_type": normalized_exam_type,
                "chapters": normalized_chapters,
                "importance": normalized_importance,
                "confidence_percent": confidence_percent,
                "due_date": due_date,
            }
            missing_optional_columns = ("chapters", "subject_name")
            while True:
                try:
                    query = supabase.table("academic_items").update(payload).eq("id", item_id)
                    if user_id:
                        query = query.eq("user_id", user_id)
                    query.execute()
                    break
                except Exception as exc:
                    missing_column = next(
                        (
                            column_name
                            for column_name in missing_optional_columns
                            if column_name in payload and _is_missing_supabase_column(exc, column_name)
                        ),
                        None,
                    )
                    if missing_column is None:
                        raise
                    payload.pop(missing_column, None)
            return
        except Exception as exc:
            if _is_missing_supabase_table(exc, "academic_items"):
                use_local_fallback = True
            elif SUPABASE_ENABLED:
                raise ValueError(f"Could not update the upcoming item in Supabase. {exc}")

    if not use_local_fallback and SUPABASE_ENABLED:
        raise ValueError("Login is required before updating an upcoming item.")

    with get_connection() as connection:
        connection.execute(
            """
            UPDATE academic_items
            SET title = ?,
                subject_name = ?,
                item_kind = ?,
                exam_type = ?,
                chapters = ?,
                importance = ?,
                confidence_percent = ?,
                due_date = ?
            WHERE id = ?
            """,
            (
                normalized_title,
                normalized_subject_name,
                normalized_kind,
                normalized_exam_type,
                normalized_chapters,
                normalized_importance,
                confidence_percent,
                due_date,
                item_id,
            ),
        )


def delete_academic_item(
    item_id: int,
    supabase: object | None = None,
    user_id: str | None = None,
) -> None:
    supabase = _get_supabase(supabase)
    use_local_fallback = not SUPABASE_ENABLED
    if supabase is not None:
        try:
            query = supabase.table("academic_items").delete().eq("id", item_id)
            if user_id:
                query = query.eq("user_id", user_id)
            query.execute()
            verify_query = supabase.table("academic_items").select("id").eq("id", item_id)
            if user_id:
                verify_query = verify_query.eq("user_id", user_id)
            verify_response = verify_query.limit(1).execute()
            if verify_response.data:
                raise ValueError(
                    "Could not delete the upcoming item in Supabase. Run the delete RLS policy in supabase_schema.sql."
                )
            return
        except Exception as exc:
            if isinstance(exc, ValueError):
                raise
            if _is_missing_supabase_table(exc, "academic_items"):
                use_local_fallback = True
            elif SUPABASE_ENABLED:
                raise ValueError(f"Could not delete the upcoming item from Supabase. {exc}")

    if not use_local_fallback and SUPABASE_ENABLED:
        raise ValueError("Login is required before deleting an upcoming item.")

    with get_connection() as connection:
        connection.execute("DELETE FROM academic_items WHERE id = ?", (item_id,))


def fetch_academic_items(
    limit: int | None = None,
    supabase: object | None = None,
    user_id: str | None = None,
) -> list[AcademicItemRecord]:
    supabase = _get_supabase(supabase)
    use_local_fallback = not SUPABASE_ENABLED
    if supabase is not None:
        if SUPABASE_ENABLED and not user_id:
            return []
        try:
            columns = "id, title, subject_name, item_kind, exam_type, chapters, importance, confidence_percent, due_date, created_at, user_id"
            query = supabase.table("academic_items").select(columns)
            if user_id:
                query = query.eq("user_id", user_id)
            query = query.order("due_date", desc=False).order("created_at", desc=False).order("id", desc=False)
            if limit is not None:
                query = query.limit(limit)
            try:
                response = query.execute()
            except Exception as exc:
                if not (
                    _is_missing_supabase_column(exc, "chapters")
                    or _is_missing_supabase_column(exc, "subject_name")
                ):
                    raise
                fallback_columns = "id, title, item_kind, exam_type, importance, confidence_percent, due_date, created_at, user_id"
                query = supabase.table("academic_items").select(fallback_columns)
                if user_id:
                    query = query.eq("user_id", user_id)
                query = query.order("due_date", desc=False).order("created_at", desc=False).order("id", desc=False)
                if limit is not None:
                    query = query.limit(limit)
                response = query.execute()
            return [_normalize_academic_item_record(record) for record in response.data or []]
        except Exception as exc:
            if _is_missing_supabase_table(exc, "academic_items"):
                use_local_fallback = True
            elif SUPABASE_ENABLED:
                return []

    if not use_local_fallback and SUPABASE_ENABLED:
        return []

    query = """
        SELECT id, title, subject_name, item_kind, exam_type, chapters, importance, confidence_percent, due_date, created_at
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


def add_study_subject(
    name: str,
    priority: str,
    confidence_percent: int,
    weekly_goal_minutes: int,
    notes: str = "",
    supabase: object | None = None,
    user_id: str | None = None,
) -> None:
    normalized_name = " ".join(name.strip().split())
    normalized_priority = priority.strip().lower()
    normalized_notes = " ".join(notes.strip().split())

    if not normalized_name:
        raise ValueError("Subject name is required.")
    if normalized_priority not in {"critical", "high", "medium", "low"}:
        raise ValueError("Priority must be critical, high, medium, or low.")
    if not 0 <= confidence_percent <= 100:
        raise ValueError("Confidence must be between 0 and 100.")
    if weekly_goal_minutes < 0:
        raise ValueError("Weekly goal cannot be negative.")

    created_at = datetime.now().isoformat(timespec="seconds")
    supabase = _get_supabase(supabase)
    use_local_fallback = not SUPABASE_ENABLED
    if supabase is not None:
        try:
            payload = {
                "user_id": user_id,
                "name": normalized_name,
                "priority": normalized_priority,
                "confidence_percent": confidence_percent,
                "weekly_goal_minutes": weekly_goal_minutes,
                "notes": normalized_notes,
                "created_at": created_at,
            }
            missing_optional_columns = ("notes", "weekly_goal_minutes")
            while True:
                try:
                    supabase.table("study_subjects").insert(payload).execute()
                    break
                except Exception as exc:
                    missing_column = next(
                        (
                            column_name
                            for column_name in missing_optional_columns
                            if column_name in payload and _is_missing_supabase_column(exc, column_name)
                        ),
                        None,
                    )
                    if missing_column is None:
                        raise
                    payload.pop(missing_column, None)
            return
        except Exception as exc:
            if _is_missing_supabase_table(exc, "study_subjects"):
                use_local_fallback = True
            elif SUPABASE_ENABLED:
                raise ValueError(
                    "Could not save the subject to Supabase. Make sure the study_subjects table exists. "
                    f"{exc}"
                )

    if not use_local_fallback and SUPABASE_ENABLED:
        raise ValueError("Login is required before saving a subject.")

    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO study_subjects (
                name,
                priority,
                confidence_percent,
                weekly_goal_minutes,
                notes,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(name) DO UPDATE SET
                priority = excluded.priority,
                confidence_percent = excluded.confidence_percent,
                weekly_goal_minutes = excluded.weekly_goal_minutes,
                notes = excluded.notes
            """,
            (
                normalized_name,
                normalized_priority,
                confidence_percent,
                weekly_goal_minutes,
                normalized_notes,
                created_at,
            ),
        )


def fetch_study_subjects(
    limit: int | None = None,
    supabase: object | None = None,
    user_id: str | None = None,
) -> list[StudySubjectRecord]:
    supabase = _get_supabase(supabase)
    use_local_fallback = not SUPABASE_ENABLED
    if supabase is not None:
        if SUPABASE_ENABLED and not user_id:
            return []
        try:
            columns = "id, name, priority, confidence_percent, weekly_goal_minutes, notes, created_at, user_id"
            fallback_columns = "id, name, priority, confidence_percent, created_at, user_id"
            try:
                query = supabase.table("study_subjects").select(columns)
                if user_id:
                    query = query.eq("user_id", user_id)
                query = query.order("created_at", desc=False).order("id", desc=False)
                if limit is not None:
                    query = query.limit(limit)
                response = query.execute()
            except Exception as exc:
                if not (
                    _is_missing_supabase_column(exc, "notes")
                    or _is_missing_supabase_column(exc, "weekly_goal_minutes")
                ):
                    raise
                query = supabase.table("study_subjects").select(fallback_columns)
                if user_id:
                    query = query.eq("user_id", user_id)
                query = query.order("created_at", desc=False).order("id", desc=False)
                if limit is not None:
                    query = query.limit(limit)
                response = query.execute()
            return [_normalize_study_subject_record(record) for record in response.data or []]
        except Exception as exc:
            if _is_missing_supabase_table(exc, "study_subjects"):
                use_local_fallback = True
            elif SUPABASE_ENABLED:
                return []

    if not use_local_fallback and SUPABASE_ENABLED:
        return []

    query = """
        SELECT id, name, priority, confidence_percent, weekly_goal_minutes, notes, created_at
        FROM study_subjects
        ORDER BY created_at ASC, id ASC
    """
    params: tuple[int, ...] = ()
    if limit is not None:
        query += " LIMIT ?"
        params = (limit,)

    with get_connection() as connection:
        rows = connection.execute(query, params).fetchall()
    return [_normalize_study_subject_record(dict(row)) for row in rows]


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


def _is_short_quote(text: str) -> bool:
    return len(text.split()) <= MAX_QUOTE_WORDS


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
        if not _is_short_quote(quote_text):
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
                if not _is_short_quote(quote_text):
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
    fallback_quotes = [quote for quote in FALLBACK_QUOTES if _is_short_quote(quote["text"])]
    quotes = _load_csv_quotes() or fallback_quotes
    quote = _pick_random_item(quotes)
    return {
        "text": quote["text"],
        "author": quote["author"] or "zenithstudy",
        "source": "csv" if quotes is not fallback_quotes else "fallback",
    }


def _build_next_best_action(
    academic_items: list[AcademicItemRecord],
    subject_totals: dict[str, int],
) -> dict:
    today = date.today()
    ranked_actions = []

    for item in academic_items:
        title = item["title"]
        plan_subject = str(item.get("subject_name") or title)
        due_date = datetime.strptime(item["due_date"], "%Y-%m-%d").date()
        days_left = (due_date - today).days
        confidence_percent = int(item["confidence_percent"])
        studied_minutes = subject_totals.get(plan_subject, 0)
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
                "subject_name": plan_subject,
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


def _build_daily_forced_plan(
    sessions: list[SessionRecord],
    academic_items: list[AcademicItemRecord],
    study_subjects: list[StudySubjectRecord],
    weekly_subject_totals: dict[str, int],
) -> dict:
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

    deadline_candidates = []
    importance_weight = {"critical": 45, "high": 32, "medium": 18, "low": 8}
    for item in academic_items:
        plan_subject = str(item.get("subject_name") or item["title"])
        due_date = datetime.strptime(item["due_date"], "%Y-%m-%d").date()
        days_left = (due_date - today).days
        confidence_percent = int(item["confidence_percent"])
        urgency_weight = (
            100
            if days_left <= 0
            else 90
            if days_left == 1
            else 70
            if days_left == 2
            else max(0, 58 - (days_left * 6))
        )
        score = (
            urgency_weight
            + importance_weight.get(str(item["importance"]), 0)
            + (100 - confidence_percent)
            - min(subject_minutes.get(plan_subject, 0) // 20, 20)
        )
        is_crucial = (
            days_left <= 1
            or (str(item["importance"]) in {"critical", "high"} and days_left <= 3)
            or (confidence_percent <= 45 and days_left <= 4)
        )
        deadline_candidates.append(
            {
                "title": item["title"],
                "subject": plan_subject,
                "item_kind": item["item_kind"].title(),
                "exam_type": item["exam_type"],
                "importance": item["importance"].title(),
                "confidence_percent": confidence_percent,
                "days_left": days_left,
                "score": score,
                "is_crucial": is_crucial,
                "source": "upcoming",
            }
        )

    deadline_candidates.sort(
        key=lambda item: (
            not item["is_crucial"],
            int(item["days_left"]),
            -int(item["score"]),
            str(item["title"]).lower(),
        )
    )

    subject_candidates: list[dict[str, str | int | None]] = []
    for subject in study_subjects:
        name = str(subject["name"])
        confidence_percent = int(subject["confidence_percent"])
        weekly_goal_minutes = int(subject["weekly_goal_minutes"])
        studied_this_week = weekly_subject_totals.get(name, 0)
        goal_gap = max(weekly_goal_minutes - studied_this_week, 0)
        last_day = last_studied.get(name)
        days_since_studied = None if last_day is None else (today - last_day).days
        recency_weight = 18 if days_since_studied is None else min(max(days_since_studied, 0) * 7, 28)
        score = (
            importance_weight.get(str(subject["priority"]), 0)
            + (100 - confidence_percent)
            + min(goal_gap // 10, 35)
            + recency_weight
        )
        subject_candidates.append(
            {
                "subject": name,
                "item_kind": "Study",
                "exam_type": "",
                "importance": str(subject["priority"]).title(),
                "confidence_percent": confidence_percent,
                "days_left": None,
                "goal_gap": goal_gap,
                "studied_this_week": studied_this_week,
                "weekly_goal_minutes": weekly_goal_minutes,
                "days_since_studied": days_since_studied,
                "score": score,
                "source": "subject",
            }
        )

    subject_candidates.sort(key=lambda item: (-int(item["score"]), str(item["subject"]).lower()))

    history_candidates = []
    for subject in sorted(subject_minutes.keys(), key=lambda name: (last_studied.get(name, date.min), subject_minutes[name], name.lower())):
        history_candidates.append(
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

    selected_subjects: list[dict[str, str | int | None]] = []

    crucial_deadlines = [item for item in deadline_candidates if item["is_crucial"]]
    background_deadlines = [item for item in deadline_candidates if not item["is_crucial"]]

    for item in crucial_deadlines[:2]:
        selected_subjects.append(
            {
                "subject": item["subject"],
                "title": item["title"],
                "item_kind": item["item_kind"],
                "exam_type": item["exam_type"],
                "importance": item["importance"],
                "confidence_percent": item["confidence_percent"],
                "days_left": item["days_left"],
                "source": "upcoming",
            }
        )

    for candidate_group in (subject_candidates, background_deadlines, history_candidates, crucial_deadlines[2:]):
        for item in candidate_group:
            if len(selected_subjects) >= 3:
                break
            subject_name = str(item.get("subject") or item.get("title"))
            if any(str(entry["subject"]).lower() == subject_name.lower() for entry in selected_subjects):
                continue
            if item["source"] == "upcoming":
                selected_subjects.append(
                    {
                        "subject": item["subject"],
                        "title": item["title"],
                        "item_kind": item["item_kind"],
                        "exam_type": item["exam_type"],
                        "importance": item["importance"],
                        "confidence_percent": item["confidence_percent"],
                        "days_left": item["days_left"],
                        "source": "upcoming",
                    }
                )
            else:
                selected_subjects.append(item)
        if len(selected_subjects) >= 3:
            break

    if not selected_subjects:
        return {
            "headline": "Daily forced plan",
            "summary": "Add subjects, exams, projects, or real study sessions first. The plan only uses your own data.",
            "total_minutes": 0,
            "blocks": [],
        }

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
        elif plan_item["source"] == "subject":
            goal_gap = int(plan_item.get("goal_gap") or 0)
            confidence_percent = int(plan_item["confidence_percent"])
            days_since_studied = plan_item.get("days_since_studied")
            if goal_gap > 0 and confidence_percent < 70:
                reason = f"Priority subject: {goal_gap} weekly minutes left and confidence is {confidence_percent}%."
            elif goal_gap > 0:
                reason = f"Weekly goal has {goal_gap} minutes left. Put time here before adding extras."
            elif days_since_studied is None:
                reason = "Saved subject with no logged session yet. Establish a baseline today."
            elif int(days_since_studied) >= 2:
                reason = f"You have not studied this for {days_since_studied} days."
            else:
                reason = "No urgent deadline is blocking you, so keep this priority subject warm."
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


def _build_subject_priorities(
    study_subjects: list[StudySubjectRecord],
    subject_totals: dict[str, int],
    weekly_subject_totals: dict[str, int],
) -> list[dict]:
    ranked_subjects = []
    priority_weight = {"critical": 45, "high": 30, "medium": 18, "low": 8}

    for subject in study_subjects:
        name = str(subject["name"])
        confidence_percent = int(subject["confidence_percent"])
        weekly_goal_minutes = int(subject["weekly_goal_minutes"])
        studied_this_week = weekly_subject_totals.get(name, 0)
        goal_gap = max(weekly_goal_minutes - studied_this_week, 0)
        score = (
            priority_weight.get(subject["priority"], 0)
            + (100 - confidence_percent)
            + min(goal_gap // 10, 35)
        )
        ranked_subjects.append(
            {
                "id": subject["id"],
                "name": name,
                "priority": str(subject["priority"]).title(),
                "confidence_percent": confidence_percent,
                "weekly_goal_minutes": weekly_goal_minutes,
                "studied_this_week": studied_this_week,
                "total_minutes": subject_totals.get(name, 0),
                "goal_gap": goal_gap,
                "notes": subject["notes"],
                "score": score,
            }
        )

    ranked_subjects.sort(key=lambda item: item["score"], reverse=True)
    return ranked_subjects


def _build_chapters_from_academic_items(
    academic_items: list[AcademicItemRecord],
    subject_totals: dict[str, int],
    progress_by_chapter: dict[str, dict[str, int | bool | None]],
) -> list[Chapter]:
    chapters: list[Chapter] = []

    for item in academic_items:
        subject = str(item.get("subject_name") or item["title"])
        chapter_titles = _split_chapter_titles(str(item.get("chapters") or ""), str(item["title"]))
        shared_subject_minutes = subject_totals.get(subject, 0) // max(len(chapter_titles), 1)
        base_confidence = _confidence_percent_to_level(int(item["confidence_percent"]))
        base_importance = _importance_to_level(str(item["importance"]))

        for index, chapter_title in enumerate(chapter_titles, start=1):
            chapter_id = _chapter_id(item["id"], index)
            progress = progress_by_chapter.get(chapter_id, {})
            difficulty = int(progress.get("difficulty") or max(1, min(5, 6 - base_confidence + (1 if base_importance >= 4 else 0))))
            estimated_total = int(progress.get("estimated_total_minutes") or (25 + (difficulty * 15)))
            past_minutes = int(progress.get("past_study_minutes") or min(shared_subject_minutes, estimated_total))
            confidence_level = int(progress.get("confidence_level") or base_confidence)
            is_finished = bool(progress.get("is_finished") or past_minutes >= estimated_total)

            chapters.append(
                Chapter(
                    id=chapter_id,
                    title=chapter_title,
                    subject=subject,
                    dueDate=str(item["due_date"]),
                    confidenceLevel=confidence_level,
                    importance=base_importance,
                    isFinished=is_finished,
                    pastStudyMinutes=past_minutes,
                    estimatedTotalMinutes=estimated_total,
                    difficulty=difficulty,
                )
            )

    return chapters


def _build_adaptive_study_plan(
    academic_items: list[AcademicItemRecord],
    subject_totals: dict[str, int],
    available_minutes_per_day: int = 120,
    horizon_days: int = 7,
) -> dict:
    today = date.today()
    progress = fetch_chapter_progress()
    chapters = _build_chapters_from_academic_items(academic_items, subject_totals, progress)
    if not chapters:
        return {
            "availableMinutesPerDay": available_minutes_per_day,
            "chapters": [],
            "days": [],
        }

    latest_due_date = max(datetime.strptime(chapter.dueDate, "%Y-%m-%d").date() for chapter in chapters)
    end_day = min(latest_due_date, today + timedelta(days=max(horizon_days - 1, 0)))
    plan = generate_study_plan(chapters, available_minutes_per_day, today, end_day)
    return {
        "availableMinutesPerDay": available_minutes_per_day,
        "chapters": [chapter.__dict__ for chapter in chapters],
        "days": plan_to_dict(plan),
    }


def _get_two_week_simulation_records() -> tuple[list[SessionRecord], list[AcademicItemRecord], list[StudySubjectRecord]]:
    today = date.today()
    sessions: list[SessionRecord] = []
    subjects = ("Mathematics", "Physics", "Biology", "History", "Chemistry")
    for offset in range(13, -1, -1):
        session_day = today - timedelta(days=offset)
        subject = subjects[offset % len(subjects)]
        sessions.append(
            {
                "id": 900 + offset,
                "subject": subject,
                "duration_minutes": 25 + ((offset * 10) % 55),
                "session_date": session_day.isoformat(),
                "created_at": f"{session_day.isoformat()}T18:00:00",
            }
        )
        if offset % 3 == 0:
            secondary = subjects[(offset + 2) % len(subjects)]
            sessions.append(
                {
                    "id": 1000 + offset,
                    "subject": secondary,
                    "duration_minutes": 20 + ((offset * 7) % 35),
                    "session_date": session_day.isoformat(),
                    "created_at": f"{session_day.isoformat()}T20:00:00",
                }
            )

    academic_items: list[AcademicItemRecord] = [
        {
            "id": 2001,
            "title": "Math Final",
            "subject_name": "Mathematics",
            "item_kind": "exam",
            "exam_type": "Written",
            "chapters": "Limits, Derivatives, Integrals, Series",
            "importance": "critical",
            "confidence_percent": 35,
            "due_date": (today + timedelta(days=2)).isoformat(),
            "created_at": today.isoformat(),
        },
        {
            "id": 2002,
            "title": "Physics Practical",
            "subject_name": "Physics",
            "item_kind": "exam",
            "exam_type": "Lab",
            "chapters": "Kinematics, Forces, Circuits",
            "importance": "high",
            "confidence_percent": 48,
            "due_date": (today + timedelta(days=5)).isoformat(),
            "created_at": today.isoformat(),
        },
        {
            "id": 2003,
            "title": "Cell Biology Project",
            "subject_name": "Biology",
            "item_kind": "project",
            "exam_type": "",
            "chapters": "Cell structure, Enzymes, Respiration",
            "importance": "medium",
            "confidence_percent": 62,
            "due_date": (today + timedelta(days=8)).isoformat(),
            "created_at": today.isoformat(),
        },
        {
            "id": 2004,
            "title": "Modern History Essay",
            "subject_name": "History",
            "item_kind": "project",
            "exam_type": "",
            "chapters": "Industrialization, World War I, Treaty analysis",
            "importance": "high",
            "confidence_percent": 70,
            "due_date": (today + timedelta(days=11)).isoformat(),
            "created_at": today.isoformat(),
        },
        {
            "id": 2005,
            "title": "Chemistry Quiz",
            "subject_name": "Chemistry",
            "item_kind": "exam",
            "exam_type": "Quiz",
            "chapters": "Stoichiometry, Acids and bases",
            "importance": "medium",
            "confidence_percent": 55,
            "due_date": (today + timedelta(days=14)).isoformat(),
            "created_at": today.isoformat(),
        },
    ]
    study_subjects: list[StudySubjectRecord] = [
        {"id": "demo-subject-math", "name": "Mathematics", "priority": "critical", "confidence_percent": 35, "weekly_goal_minutes": 240, "notes": "Weakest area: integrals", "created_at": today.isoformat()},
        {"id": "demo-subject-physics", "name": "Physics", "priority": "high", "confidence_percent": 48, "weekly_goal_minutes": 180, "notes": "Practice lab calculations", "created_at": today.isoformat()},
        {"id": "demo-subject-biology", "name": "Biology", "priority": "medium", "confidence_percent": 62, "weekly_goal_minutes": 120, "notes": "Project research still open", "created_at": today.isoformat()},
        {"id": "demo-subject-history", "name": "History", "priority": "high", "confidence_percent": 70, "weekly_goal_minutes": 150, "notes": "Essay outline needs evidence", "created_at": today.isoformat()},
        {"id": "demo-subject-chemistry", "name": "Chemistry", "priority": "medium", "confidence_percent": 55, "weekly_goal_minutes": 100, "notes": "Formula recall", "created_at": today.isoformat()},
    ]
    return sessions, academic_items, study_subjects


def get_dashboard_data(
    supabase: object | None = None,
    user_id: str | None = None,
    demo: bool = False,
) -> dict:
    if demo:
        sessions, academic_items, study_subjects = _get_two_week_simulation_records()
    else:
        sessions = fetch_sessions(supabase=supabase, user_id=user_id)
        academic_items = fetch_academic_items(limit=8, supabase=supabase, user_id=user_id)
        study_subjects = fetch_study_subjects(supabase=supabase, user_id=user_id)
    today = date.today()
    today_iso = today.isoformat()
    current_month = today.month
    current_year = today.year
    week_start = today - timedelta(days=today.weekday())

    total_minutes = 0
    today_minutes = 0
    today_sessions = 0
    subject_totals: dict[str, int] = defaultdict(int)
    weekly_subject_totals: dict[str, int] = defaultdict(int)
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
        if session_day >= week_start:
            weekly_subject_totals[session["subject"]] += duration
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
    subject_priorities = _build_subject_priorities(study_subjects, subject_totals, weekly_subject_totals)
    forced_plan = _build_daily_forced_plan(sessions, academic_items, study_subjects, weekly_subject_totals)
    next_best_action = _build_next_best_action(academic_items, subject_totals)
    adaptive_study_plan = _build_adaptive_study_plan(
        academic_items,
        subject_totals,
        available_minutes_per_day=120,
        horizon_days=14 if demo else 7,
    )
    upcoming_items = []
    for item in academic_items:
        due_date = datetime.strptime(item["due_date"], "%Y-%m-%d").date()
        days_left = (due_date - today).days
        upcoming_items.append(
            {
                "id": item["id"],
                "title": item["title"],
                "subject_name": item.get("subject_name") or item["title"],
                "item_kind": item["item_kind"].title(),
                "exam_type": item["exam_type"],
                "chapters": item["chapters"],
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
        "adaptive_study_plan": adaptive_study_plan,
        "study_subjects": study_subjects,
        "subject_priorities": subject_priorities,
        "upcoming_items": upcoming_items,
        "is_demo": demo,
    }
