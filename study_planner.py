from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from math import ceil


@dataclass(frozen=True)
class Chapter:
    id: str
    title: str
    subject: str
    dueDate: str
    confidenceLevel: int
    importance: int
    isFinished: bool
    pastStudyMinutes: int
    estimatedTotalMinutes: int
    difficulty: int
    progressStatus: str = "not_started"


@dataclass(frozen=True)
class StudyBlock:
    chapterId: str
    chapterTitle: str
    subject: str
    date: str
    durationMinutes: int
    method: str
    reason: str
    priorityScore: float
    isHeavy: bool
    confidenceLevel: int
    progressStatus: str


@dataclass(frozen=True)
class StudyDayPlan:
    date: str
    totalStudyMinutes: int
    blocks: list[StudyBlock]
    breaks: list[dict[str, int | str]]


def _clamp(value: int, minimum: int, maximum: int) -> int:
    return max(minimum, min(value, maximum))


def _parse_day(raw_date: str | date) -> date:
    if isinstance(raw_date, date):
        return raw_date
    return datetime.strptime(raw_date, "%Y-%m-%d").date()


def _normalize_status(status: str) -> str:
    return status if status in {"not_started", "studying", "weak", "complete"} else "not_started"


def calculate_priority_score(chapter: Chapter, plan_day: date) -> float:
    due_day = _parse_day(chapter.dueDate)
    days_left = (due_day - plan_day).days
    progress_status = _normalize_status(chapter.progressStatus)
    is_complete = chapter.isFinished or progress_status == "complete"
    remaining_ratio = max(
        chapter.estimatedTotalMinutes - chapter.pastStudyMinutes,
        0,
    ) / max(chapter.estimatedTotalMinutes, 1)

    # Formula: urgency dominates, then low confidence, importance, unfinished work,
    # chapter status, remaining coverage gap, and difficulty. Complete chapters get
    # a strong penalty but can still appear as short review if urgent and important.
    urgency_score = 60 if days_left <= 0 else max(0, 52 - (days_left * 6))
    confidence_score = (6 - _clamp(chapter.confidenceLevel, 1, 5)) * 12
    importance_score = _clamp(chapter.importance, 1, 5) * 10
    unfinished_score = 30 if not is_complete else -35
    status_score = {
        "not_started": 24,
        "studying": 12,
        "weak": 32,
        "complete": -30,
    }[progress_status]
    coverage_score = remaining_ratio * 35
    difficulty_score = _clamp(chapter.difficulty, 1, 5) * 6

    return urgency_score + confidence_score + importance_score + unfinished_score + status_score + coverage_score + difficulty_score


def choose_study_method(chapter: Chapter) -> str:
    confidence = _clamp(chapter.confidenceLevel, 1, 5)
    importance = _clamp(chapter.importance, 1, 5)
    progress_status = _normalize_status(chapter.progressStatus)

    if progress_status == "complete":
        return "spaced review"
    if progress_status == "weak" and importance >= 4:
        return "active recall + quiz"
    if progress_status == "weak":
        return "active recall + explanation"
    if progress_status == "not_started" or not chapter.isFinished:
        return "learning + summary"
    if importance >= 4 and confidence <= 2:
        return "active recall + quiz"
    if confidence <= 2:
        return "active recall + explanation"
    if confidence == 3:
        return "practice questions"
    return "spaced review"


def _block_duration(chapter: Chapter, available_minutes: int) -> int:
    remaining = max(chapter.estimatedTotalMinutes - chapter.pastStudyMinutes, 15)
    if available_minutes < 30:
        return min(available_minutes, 25)
    if chapter.difficulty >= 4 or chapter.confidenceLevel <= 2:
        return min(45, max(25, min(remaining, available_minutes)))
    if chapter.confidenceLevel >= 4 or chapter.isFinished:
        return min(25, max(15, min(remaining, available_minutes)))
    return min(35, max(25, min(remaining, available_minutes)))


def generate_study_plan(
    chapters: list[Chapter],
    availableMinutesPerDay: int,
    startDate: str | date,
    endDate: str | date,
) -> list[StudyDayPlan]:
    start_day = _parse_day(startDate)
    end_day = _parse_day(endDate)
    if end_day < start_day:
        raise ValueError("endDate must be on or after startDate.")

    study_days: list[StudyDayPlan] = []
    mutable_minutes = {chapter.id: chapter.pastStudyMinutes for chapter in chapters}
    mutable_finished = {chapter.id: chapter.isFinished for chapter in chapters}
    mutable_statuses = {chapter.id: _normalize_status(chapter.progressStatus) for chapter in chapters}
    day_count = (end_day - start_day).days + 1

    for offset in range(day_count):
        plan_day = start_day + timedelta(days=offset)
        remaining_budget = max(0, availableMinutesPerDay)
        heavy_blocks = 0
        blocks: list[StudyBlock] = []
        breaks: list[dict[str, int | str]] = []

        ranked = sorted(
            (
                Chapter(
                    **{
                        **chapter.__dict__,
                        "pastStudyMinutes": mutable_minutes[chapter.id],
                        "isFinished": mutable_finished[chapter.id],
                        "progressStatus": mutable_statuses[chapter.id],
                    }
                )
                for chapter in chapters
            ),
            key=lambda chapter: calculate_priority_score(chapter, plan_day),
            reverse=True,
        )

        for chapter in ranked:
            if remaining_budget < 15:
                break
            if chapter.isFinished and calculate_priority_score(chapter, plan_day) < 70:
                continue

            is_heavy = chapter.difficulty >= 4 or chapter.confidenceLevel <= 2
            if is_heavy and heavy_blocks >= 2:
                continue

            duration = _block_duration(chapter, remaining_budget)
            if duration < 15:
                continue

            score = calculate_priority_score(chapter, plan_day)
            method = choose_study_method(chapter)
            due_day = _parse_day(chapter.dueDate)
            days_left = (due_day - plan_day).days
            coverage_gap = max(chapter.estimatedTotalMinutes - chapter.pastStudyMinutes, 0)
            reason = (
                f"Due in {days_left} day{'s' if days_left != 1 else ''}; "
                f"confidence {chapter.confidenceLevel}/5, importance {chapter.importance}/5, "
                f"{coverage_gap} estimated minutes left."
            )

            blocks.append(
                StudyBlock(
                    chapterId=chapter.id,
                    chapterTitle=chapter.title,
                    subject=chapter.subject,
                    date=plan_day.isoformat(),
                    durationMinutes=duration,
                    method=method,
                    reason=reason,
                    priorityScore=round(score, 2),
                    isHeavy=is_heavy,
                    confidenceLevel=chapter.confidenceLevel,
                    progressStatus=_normalize_status(chapter.progressStatus),
                )
            )
            mutable_minutes[chapter.id] += duration
            if mutable_minutes[chapter.id] >= chapter.estimatedTotalMinutes:
                mutable_finished[chapter.id] = True
                mutable_statuses[chapter.id] = "complete"
            elif mutable_statuses[chapter.id] == "not_started":
                mutable_statuses[chapter.id] = "studying"
            remaining_budget -= duration
            if is_heavy:
                heavy_blocks += 1
            if remaining_budget >= 20:
                breaks.append({"afterBlock": len(blocks), "durationMinutes": 5, "label": "Short break"})
                remaining_budget -= 5

        study_days.append(
            StudyDayPlan(
                date=plan_day.isoformat(),
                totalStudyMinutes=sum(block.durationMinutes for block in blocks),
                blocks=blocks,
                breaks=breaks,
            )
        )

    return study_days


def plan_to_dict(plan: list[StudyDayPlan]) -> list[dict]:
    return [
        {
            "date": day.date,
            "totalStudyMinutes": day.totalStudyMinutes,
            "blocks": [block.__dict__ for block in day.blocks],
            "breaks": day.breaks,
        }
        for day in plan
    ]


generateStudyPlan = generate_study_plan
