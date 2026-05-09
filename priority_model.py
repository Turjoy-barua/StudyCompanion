from __future__ import annotations

from datetime import date, datetime
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
DEFAULT_RISK_MODEL_PATH = BASE_DIR / "models" / "priority_risk_model.joblib"


def _bounded_priority_score(score: float) -> int:
    return max(0, min(100, round(score)))


def _format_deadline_text(days_left: int | None) -> str:
    if days_left is None:
        return "No deadline"
    if days_left < 0:
        return f"{abs(days_left)} day{'s' if abs(days_left) != 1 else ''} overdue"
    if days_left == 0:
        return "Due today"
    if days_left == 1:
        return "Due tomorrow"
    return f"Due in {days_left} days"


def _deadline_pressure(days_left: int | None) -> int:
    if days_left is None:
        return 0
    if days_left <= 0:
        return 42
    if days_left == 1:
        return 38
    if days_left == 2:
        return 32
    return max(0, 28 - (days_left * 3))


class AcademicRiskModel:
    """Loader for the trained ML model created by train_priority_model.py."""

    _bundle_cache: dict[Path, dict] = {}

    def __init__(self, model_path: str | Path = DEFAULT_RISK_MODEL_PATH) -> None:
        self.model_path = Path(model_path)
        self._bundle: dict | None = None

    @property
    def is_available(self) -> bool:
        return self.model_path.exists()

    def load(self) -> dict:
        if self._bundle is not None:
            return self._bundle
        cache_key = self.model_path.resolve()
        if cache_key in self._bundle_cache:
            self._bundle = self._bundle_cache[cache_key]
            return self._bundle
        if not self.model_path.exists():
            raise FileNotFoundError(
                f"Trained risk model not found at {self.model_path}. "
                "Run `python3 train_priority_model.py --data-dir anonymisedData` first."
            )

        import joblib

        self._bundle = joblib.load(self.model_path)
        self._bundle_cache[cache_key] = self._bundle
        return self._bundle

    def metrics(self) -> dict:
        return dict(self.load().get("metrics", {}))

    def predict_risk(self, feature_rows: list[dict]) -> list[dict]:
        if not feature_rows:
            return []

        import pandas as pd

        bundle = self.load()
        frame = pd.DataFrame(feature_rows)
        for column in bundle.get("feature_columns", []):
            if column not in frame.columns:
                frame[column] = None
        if bundle.get("feature_columns"):
            frame = frame[bundle["feature_columns"]]
        probabilities = bundle["model"].predict_proba(frame)[:, 1]
        predictions = []
        for row, probability in zip(feature_rows, probabilities, strict=False):
            risk_score = _bounded_priority_score(float(probability) * 100)
            predictions.append(
                {
                    **row,
                    "risk_probability": float(probability),
                    "risk_score": risk_score,
                    "risk_label": "high" if risk_score >= 70 else "medium" if risk_score >= 40 else "low",
                }
            )
        return predictions


class PriorityPredictionModel:
    """Deterministic priority model for ranking the student's next actions."""

    def __init__(self, max_predictions: int = 5) -> None:
        self.max_predictions = max_predictions
        self.importance_weight = {"critical": 28, "high": 20, "medium": 12, "low": 6}

    def predict(
        self,
        sessions: list[dict],
        academic_items: list[dict],
        study_subjects: list[dict],
        subject_totals: dict[str, int],
        weekly_subject_totals: dict[str, int],
        adaptive_study_plan: dict,
        today: date | None = None,
    ) -> dict:
        today = today or date.today()
        last_studied = self._last_studied_by_subject(sessions)
        predictions: list[dict] = []

        predictions.extend(self._deadline_predictions(academic_items, subject_totals, today))
        predictions.extend(self._subject_predictions(study_subjects, weekly_subject_totals, last_studied, today))
        predictions.extend(self._chapter_predictions(adaptive_study_plan, today))

        predictions.sort(
            key=lambda prediction: (
                -int(prediction["score"]),
                str(prediction["source"]),
                str(prediction["title"]).lower(),
            )
        )
        top_predictions = [
            {**prediction, "rank": index + 1}
            for index, prediction in enumerate(predictions[: self.max_predictions])
        ]

        if not top_predictions:
            return {
                "headline": "AI priority predictor",
                "summary": "Add subjects, deadlines, chapters, or study sessions so the predictor can rank your next moves.",
                "items": [],
            }

        top = top_predictions[0]
        return {
            "headline": "AI priority predictor",
            "summary": f"Top priority: {top['title']} because its current priority score is {top['score']}/100.",
            "items": top_predictions,
        }

    def _last_studied_by_subject(self, sessions: list[dict]) -> dict[str, date]:
        last_studied: dict[str, date] = {}
        for session in sessions:
            subject = str(session["subject"])
            session_day = datetime.strptime(str(session["session_date"]), "%Y-%m-%d").date()
            if subject not in last_studied or session_day > last_studied[subject]:
                last_studied[subject] = session_day
        return last_studied

    def _deadline_predictions(
        self,
        academic_items: list[dict],
        subject_totals: dict[str, int],
        today: date,
    ) -> list[dict]:
        predictions = []
        for item in academic_items:
            subject = str(item.get("subject_name") or item["title"])
            due_date = datetime.strptime(str(item["due_date"]), "%Y-%m-%d").date()
            days_left = (due_date - today).days
            confidence_percent = int(item["confidence_percent"])
            studied_minutes = subject_totals.get(subject, 0)
            score = (
                _deadline_pressure(days_left)
                + self.importance_weight.get(str(item["importance"]), 0)
                + ((100 - confidence_percent) * 0.34)
                - min(studied_minutes // 25, 10)
            )

            if days_left <= 1:
                next_step = "Start with a timed exam-style block, then fix only the mistakes."
            elif confidence_percent < 55:
                next_step = "Identify the weakest chapter and do active recall before rereading notes."
            elif str(item["item_kind"]) == "project":
                next_step = "Finish the riskiest deliverable before polishing low-risk parts."
            else:
                next_step = "Do a focused practice set and mark what still feels uncertain."

            predictions.append(
                {
                    "title": str(item["title"]),
                    "subject": subject,
                    "kind": str(item["item_kind"]).title(),
                    "score": _bounded_priority_score(score),
                    "urgency": _format_deadline_text(days_left),
                    "why": (
                        f"{str(item['importance']).title()} priority, {confidence_percent}% confidence, "
                        f"and {studied_minutes} logged minutes."
                    ),
                    "next_step": next_step,
                    "source": "deadline",
                }
            )
        return predictions

    def _subject_predictions(
        self,
        study_subjects: list[dict],
        weekly_subject_totals: dict[str, int],
        last_studied: dict[str, date],
        today: date,
    ) -> list[dict]:
        predictions = []
        for subject in study_subjects:
            name = str(subject["name"])
            confidence_percent = int(subject["confidence_percent"])
            weekly_goal_minutes = int(subject["weekly_goal_minutes"])
            studied_this_week = weekly_subject_totals.get(name, 0)
            goal_gap = max(weekly_goal_minutes - studied_this_week, 0)
            days_since_studied = None
            if name in last_studied:
                days_since_studied = (today - last_studied[name]).days
            recency_pressure = 16 if days_since_studied is None else min(max(days_since_studied, 0) * 5, 20)
            score = (
                self.importance_weight.get(str(subject["priority"]), 0)
                + ((100 - confidence_percent) * 0.3)
                + min(goal_gap // 8, 24)
                + recency_pressure
            )

            if goal_gap > 0:
                next_step = f"Study for {min(goal_gap, 45)} minutes toward the weekly goal."
            elif confidence_percent < 65:
                next_step = "Review one weak area and update confidence after the block."
            else:
                next_step = "Do a short maintenance review to keep this subject active."

            if days_since_studied is None:
                recency_text = "No logged session yet"
            elif days_since_studied == 0:
                recency_text = "Studied today"
            else:
                recency_text = f"Last studied {days_since_studied} day{'s' if days_since_studied != 1 else ''} ago"

            predictions.append(
                {
                    "title": name,
                    "subject": name,
                    "kind": "Subject",
                    "score": _bounded_priority_score(score),
                    "urgency": recency_text,
                    "why": (
                        f"{str(subject['priority']).title()} priority, {goal_gap} weekly minutes left, "
                        f"and {confidence_percent}% confidence."
                    ),
                    "next_step": next_step,
                    "source": "subject",
                }
            )
        return predictions

    def _chapter_predictions(self, adaptive_study_plan: dict, today: date) -> list[dict]:
        predictions = []
        for chapter in adaptive_study_plan.get("chapters", []):
            progress_status = str(chapter.get("progressStatus") or "not_started")
            if progress_status == "complete":
                continue

            due_date = datetime.strptime(str(chapter["dueDate"]), "%Y-%m-%d").date()
            days_left = (due_date - today).days
            confidence_level = int(chapter["confidenceLevel"])
            importance = int(chapter["importance"])
            difficulty = int(chapter["difficulty"])
            estimated_total = max(int(chapter["estimatedTotalMinutes"]), 1)
            past_minutes = int(chapter["pastStudyMinutes"])
            coverage_gap = max(estimated_total - past_minutes, 0)
            status_pressure = {"weak": 22, "not_started": 18, "studying": 10}.get(progress_status, 8)
            score = (
                _deadline_pressure(days_left)
                + status_pressure
                + ((6 - confidence_level) * 7)
                + (importance * 5)
                + (difficulty * 3)
                + ((coverage_gap / estimated_total) * 16)
            )
            predictions.append(
                {
                    "title": str(chapter["title"]),
                    "subject": str(chapter["subject"]),
                    "kind": "Chapter",
                    "score": _bounded_priority_score(score),
                    "urgency": _format_deadline_text(days_left),
                    "why": (
                        f"{progress_status.replace('_', ' ').title()}, confidence {confidence_level}/5, "
                        f"and {coverage_gap} estimated minutes left."
                    ),
                    "next_step": "Use active recall first, then spend the final minutes correcting gaps.",
                    "source": "chapter",
                }
            )
        return predictions


def build_ai_priority_predictions(
    sessions: list[dict],
    academic_items: list[dict],
    study_subjects: list[dict],
    subject_totals: dict[str, int],
    weekly_subject_totals: dict[str, int],
    adaptive_study_plan: dict,
) -> dict:
    return PriorityPredictionModel().predict(
        sessions,
        academic_items,
        study_subjects,
        subject_totals,
        weekly_subject_totals,
        adaptive_study_plan,
    )
