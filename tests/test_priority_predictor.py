from datetime import date, timedelta
from pathlib import Path
import sys


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from priority_model import PriorityPredictionModel


def test_ai_priority_predictor_ranks_urgent_low_confidence_deadline_first():
    today = date.today()
    predictions = PriorityPredictionModel().predict(
        sessions=[
            {
                "id": 1,
                "subject": "History",
                "duration_minutes": 80,
                "session_date": today.isoformat(),
                "created_at": f"{today.isoformat()}T10:00:00",
            }
        ],
        academic_items=[
            {
                "id": 10,
                "title": "Math Final",
                "subject_name": "Mathematics",
                "item_kind": "exam",
                "exam_type": "Written",
                "chapters": "Integrals",
                "importance": "critical",
                "confidence_percent": 30,
                "due_date": (today + timedelta(days=1)).isoformat(),
                "created_at": today.isoformat(),
            },
            {
                "id": 11,
                "title": "History Essay",
                "subject_name": "History",
                "item_kind": "project",
                "exam_type": "",
                "chapters": "Outline",
                "importance": "low",
                "confidence_percent": 90,
                "due_date": (today + timedelta(days=12)).isoformat(),
                "created_at": today.isoformat(),
            },
        ],
        study_subjects=[],
        subject_totals={"History": 80},
        weekly_subject_totals={"History": 80},
        adaptive_study_plan={"chapters": []},
    )

    assert predictions["items"][0]["title"] == "Math Final"
    assert predictions["items"][0]["source"] == "deadline"
    assert predictions["items"][0]["score"] > predictions["items"][1]["score"]


def test_ai_priority_predictor_uses_subject_goal_gap_when_no_deadlines_exist():
    today = date.today()
    predictions = PriorityPredictionModel().predict(
        sessions=[],
        academic_items=[],
        study_subjects=[
            {
                "id": 1,
                "name": "Physics",
                "priority": "high",
                "confidence_percent": 45,
                "weekly_goal_minutes": 180,
                "notes": "",
                "created_at": today.isoformat(),
            }
        ],
        subject_totals={},
        weekly_subject_totals={},
        adaptive_study_plan={"chapters": []},
    )

    assert predictions["items"][0]["title"] == "Physics"
    assert predictions["items"][0]["source"] == "subject"
    assert "weekly minutes left" in predictions["items"][0]["why"]
