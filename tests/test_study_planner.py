from datetime import date, timedelta
from pathlib import Path
import sys


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from study_planner import Chapter, generate_study_plan, plan_to_dict


def test_generate_study_plan_prioritizes_urgent_low_confidence_chapter():
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    next_week = (date.today() + timedelta(days=7)).isoformat()
    chapters = [
        Chapter(
            id="math-3",
            title="Chapter 3",
            subject="Math",
            dueDate=tomorrow,
            confidenceLevel=1,
            importance=5,
            isFinished=False,
            pastStudyMinutes=10,
            estimatedTotalMinutes=90,
            difficulty=5,
        ),
        Chapter(
            id="history-2",
            title="Chapter 2",
            subject="History",
            dueDate=next_week,
            confidenceLevel=5,
            importance=2,
            isFinished=True,
            pastStudyMinutes=80,
            estimatedTotalMinutes=80,
            difficulty=2,
        ),
    ]

    plan = plan_to_dict(generate_study_plan(chapters, 75, date.today(), date.today()))

    assert plan[0]["blocks"][0]["chapterId"] == "math-3"
    assert plan[0]["blocks"][0]["method"] == "active recall + quiz"
    assert plan[0]["totalStudyMinutes"] <= 75


if __name__ == "__main__":
    test_generate_study_plan_prioritizes_urgent_low_confidence_chapter()
    print("study_planner example passed")
