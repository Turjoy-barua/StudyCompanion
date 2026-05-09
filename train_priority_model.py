from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

import joblib
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.metrics import (
    accuracy_score,
    average_precision_score,
    classification_report,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.model_selection import GroupShuffleSplit
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler


BASE_DIR = Path(__file__).resolve().parent
DEFAULT_DATA_DIR = BASE_DIR / "anonymisedData"
DEFAULT_MODEL_PATH = BASE_DIR / "models" / "priority_risk_model.joblib"
DEFAULT_METRICS_PATH = BASE_DIR / "models" / "priority_risk_model_metrics.json"
KEYS = ["code_module", "code_presentation", "id_student"]
RISK_RESULTS = {"Fail", "Withdrawn"}


def _read_required_csv(data_dir: Path, filename: str) -> pd.DataFrame:
    path = data_dir / filename
    if not path.exists():
        raise FileNotFoundError(f"Missing required dataset file: {path}")
    return pd.read_csv(path)


def _aggregate_assessments(data_dir: Path, cutoff_day: int) -> pd.DataFrame:
    assessments = _read_required_csv(data_dir, "assessments.csv")
    student_assessment = _read_required_csv(data_dir, "studentAssessment.csv")
    merged = student_assessment.merge(
        assessments[["id_assessment", "code_module", "code_presentation", "assessment_type", "date", "weight"]],
        on="id_assessment",
        how="left",
    )
    merged = merged[merged["date_submitted"] <= cutoff_day].copy()
    merged["weighted_score"] = merged["score"] * merged["weight"]
    merged["is_late"] = (merged["date_submitted"] > merged["date"]).astype(int)
    merged["days_before_due"] = merged["date"] - merged["date_submitted"]

    grouped = merged.groupby(KEYS).agg(
        assessment_submissions=("id_assessment", "count"),
        assessment_score_mean=("score", "mean"),
        assessment_score_min=("score", "min"),
        assessment_score_max=("score", "max"),
        assessment_weight_sum=("weight", "sum"),
        assessment_weighted_score_sum=("weighted_score", "sum"),
        assessment_late_count=("is_late", "sum"),
        assessment_days_before_due_mean=("days_before_due", "mean"),
        assessment_banked_count=("is_banked", "sum"),
    )
    grouped["assessment_weighted_score_mean"] = (
        grouped["assessment_weighted_score_sum"] / grouped["assessment_weight_sum"].replace(0, pd.NA)
    )
    grouped = grouped.reset_index()

    due_counts = (
        assessments[assessments["date"] <= cutoff_day]
        .groupby(["code_module", "code_presentation"])
        .agg(assessments_due_by_cutoff=("id_assessment", "count"))
        .reset_index()
    )
    grouped = grouped.merge(due_counts, on=["code_module", "code_presentation"], how="left")
    grouped["assessment_completion_ratio"] = (
        grouped["assessment_submissions"] / grouped["assessments_due_by_cutoff"].replace(0, pd.NA)
    )
    return grouped


def _aggregate_vle(data_dir: Path, cutoff_day: int, chunksize: int) -> pd.DataFrame:
    vle = _read_required_csv(data_dir, "vle.csv")[
        ["id_site", "code_module", "code_presentation", "activity_type"]
    ]
    activity_parts = []
    daily_parts = []
    summary_parts = []

    for chunk in pd.read_csv(data_dir / "studentVle.csv", chunksize=chunksize):
        chunk = chunk[chunk["date"] <= cutoff_day].copy()
        if chunk.empty:
            continue

        chunk = chunk.merge(vle, on=["id_site", "code_module", "code_presentation"], how="left")
        chunk["clicks_pre_course"] = chunk["sum_click"].where(chunk["date"] < 0, 0)
        chunk["clicks_first_14"] = chunk["sum_click"].where(chunk["date"].between(0, 13), 0)
        chunk["clicks_first_30"] = chunk["sum_click"].where(chunk["date"].between(0, 29), 0)
        chunk["clicks_recent_14"] = chunk["sum_click"].where(chunk["date"].between(cutoff_day - 13, cutoff_day), 0)

        summary_parts.append(
            chunk.groupby(KEYS).agg(
                vle_total_clicks=("sum_click", "sum"),
                vle_clicks_pre_course=("clicks_pre_course", "sum"),
                vle_clicks_first_14=("clicks_first_14", "sum"),
                vle_clicks_first_30=("clicks_first_30", "sum"),
                vle_clicks_recent_14=("clicks_recent_14", "sum"),
            )
        )
        daily_parts.append(chunk.groupby(KEYS + ["date"], as_index=False)["sum_click"].sum())
        activity_parts.append(
            chunk.pivot_table(
                index=KEYS,
                columns="activity_type",
                values="sum_click",
                aggfunc="sum",
                fill_value=0,
            )
        )

    if not summary_parts:
        return pd.DataFrame(columns=KEYS)

    summary = pd.concat(summary_parts).groupby(level=KEYS).sum().reset_index()
    daily = pd.concat(daily_parts).groupby(KEYS).agg(
        vle_active_days=("date", "nunique"),
        vle_mean_clicks_active_day=("sum_click", "mean"),
        vle_max_clicks_active_day=("sum_click", "max"),
    )
    activity = pd.concat(activity_parts).groupby(level=KEYS).sum()
    activity = activity.add_prefix("vle_activity_")
    activity.columns = [str(column).replace(" ", "_").replace("-", "_") for column in activity.columns]

    return summary.merge(daily.reset_index(), on=KEYS, how="left").merge(
        activity.reset_index(), on=KEYS, how="left"
    )


def build_training_frame(data_dir: Path, cutoff_day: int = 60, chunksize: int = 1_000_000) -> pd.DataFrame:
    student_info = _read_required_csv(data_dir, "studentInfo.csv")
    registrations = _read_required_csv(data_dir, "studentRegistration.csv")
    courses = _read_required_csv(data_dir, "courses.csv")

    frame = student_info.merge(registrations, on=KEYS, how="left").merge(
        courses, on=["code_module", "code_presentation"], how="left"
    )
    frame["at_risk"] = frame["final_result"].isin(RISK_RESULTS).astype(int)

    assessment_features = _aggregate_assessments(data_dir, cutoff_day=cutoff_day)
    vle_features = _aggregate_vle(data_dir, cutoff_day=cutoff_day, chunksize=chunksize)

    frame = frame.merge(assessment_features, on=KEYS, how="left").merge(vle_features, on=KEYS, how="left")
    frame["registration_days_before_start"] = frame["date_registration"].abs()
    frame["has_unregistered_by_cutoff"] = (
        frame["date_unregistration"].notna() & (frame["date_unregistration"] <= cutoff_day)
    ).astype(int)

    numeric_fill_zero_prefixes = (
        "assessment_",
        "assessments_",
        "vle_",
    )
    for column in frame.columns:
        if column.startswith(numeric_fill_zero_prefixes):
            frame[column] = frame[column].fillna(0).infer_objects(copy=False)
    frame["imd_band"] = frame["imd_band"].fillna("Unknown")
    return frame


def train_model(frame: pd.DataFrame, random_state: int = 42) -> tuple[Pipeline, dict]:
    drop_columns = {
        "at_risk",
        "final_result",
        "id_student",
        "date_unregistration",
    }
    feature_columns = [column for column in frame.columns if column not in drop_columns]
    categorical_features = [
        "code_module",
        "code_presentation",
        "gender",
        "region",
        "highest_education",
        "imd_band",
        "age_band",
        "disability",
    ]
    categorical_features = [column for column in categorical_features if column in feature_columns]
    numeric_features = [column for column in feature_columns if column not in categorical_features]

    X = frame[feature_columns]
    y = frame["at_risk"]
    groups = frame["id_student"]

    splitter = GroupShuffleSplit(n_splits=1, test_size=0.2, random_state=random_state)
    train_index, test_index = next(splitter.split(X, y, groups))
    X_train, X_test = X.iloc[train_index], X.iloc[test_index]
    y_train, y_test = y.iloc[train_index], y.iloc[test_index]

    preprocessor = ColumnTransformer(
        transformers=[
            (
                "numeric",
                Pipeline(
                    steps=[
                        ("imputer", SimpleImputer(strategy="median")),
                        ("scaler", StandardScaler()),
                    ]
                ),
                numeric_features,
            ),
            (
                "categorical",
                Pipeline(
                    steps=[
                        ("imputer", SimpleImputer(strategy="most_frequent")),
                        ("onehot", OneHotEncoder(handle_unknown="ignore", sparse_output=False)),
                    ]
                ),
                categorical_features,
            ),
        ]
    )
    model = RandomForestClassifier(
        n_estimators=320,
        max_depth=14,
        min_samples_leaf=8,
        class_weight="balanced_subsample",
        n_jobs=-1,
        random_state=random_state,
    )
    pipeline = Pipeline(steps=[("preprocessor", preprocessor), ("classifier", model)])
    pipeline.fit(X_train, y_train)

    probabilities = pipeline.predict_proba(X_test)[:, 1]
    predictions = (probabilities >= 0.5).astype(int)
    metrics = {
        "rows": int(len(frame)),
        "train_rows": int(len(X_train)),
        "test_rows": int(len(X_test)),
        "positive_rate": float(y.mean()),
        "roc_auc": float(roc_auc_score(y_test, probabilities)),
        "average_precision": float(average_precision_score(y_test, probabilities)),
        "accuracy": float(accuracy_score(y_test, predictions)),
        "precision": float(precision_score(y_test, predictions)),
        "recall": float(recall_score(y_test, predictions)),
        "f1": float(f1_score(y_test, predictions)),
        "confusion_matrix": confusion_matrix(y_test, predictions).tolist(),
        "classification_report": classification_report(y_test, predictions, output_dict=True),
        "numeric_features": numeric_features,
        "categorical_features": categorical_features,
    }
    return pipeline, metrics


def main() -> None:
    parser = argparse.ArgumentParser(description="Train the Study Companion academic-risk priority model.")
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument("--model-path", type=Path, default=DEFAULT_MODEL_PATH)
    parser.add_argument("--metrics-path", type=Path, default=DEFAULT_METRICS_PATH)
    parser.add_argument("--cutoff-day", type=int, default=60)
    parser.add_argument("--chunksize", type=int, default=1_000_000)
    parser.add_argument("--random-state", type=int, default=42)
    args = parser.parse_args()

    frame = build_training_frame(args.data_dir, cutoff_day=args.cutoff_day, chunksize=args.chunksize)
    pipeline, metrics = train_model(frame, random_state=args.random_state)
    metrics.update(
        {
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "cutoff_day": args.cutoff_day,
            "target": "at_risk = final_result in {'Fail', 'Withdrawn'}",
        }
    )

    args.model_path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(
        {
            "model": pipeline,
            "metrics": metrics,
            "cutoff_day": args.cutoff_day,
            "feature_columns": metrics["numeric_features"] + metrics["categorical_features"],
        },
        args.model_path,
    )
    args.metrics_path.write_text(json.dumps(metrics, indent=2), encoding="utf-8")

    print(f"Saved model: {args.model_path}")
    print(f"Saved metrics: {args.metrics_path}")
    print(
        "Metrics: "
        f"roc_auc={metrics['roc_auc']:.3f}, "
        f"avg_precision={metrics['average_precision']:.3f}, "
        f"f1={metrics['f1']:.3f}, "
        f"recall={metrics['recall']:.3f}"
    )


if __name__ == "__main__":
    main()
