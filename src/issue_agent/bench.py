from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .metrics import load_jsonl


def write_swebench_predictions(
    *,
    predictions_path: str | Path,
    dataset: str,
    limit: int | None,
    cases_path: str | Path | None = None,
    model_name: str = "gia-local",
) -> int:
    records = _load_cases(cases_path)
    if limit is not None:
        records = records[:limit]
    output_path = Path(predictions_path).expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as file:
        for index, record in enumerate(records):
            instance_id = str(record.get("instance_id") or record.get("id") or f"{dataset}-{index}")
            patch = str(
                record.get("model_patch")
                or record.get("prediction")
                or record.get("patch")
                or record.get("diff")
                or ""
            )
            prediction = {
                "instance_id": instance_id,
                "model_name_or_path": model_name,
                "model_patch": patch,
            }
            file.write(json.dumps(prediction, ensure_ascii=False, sort_keys=True) + "\n")
    return len(records)


def summarize_korean_benchmark(*, cases_path: str | Path, out_path: str | Path) -> int:
    cases = _load_cases(cases_path)
    output = Path(out_path).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as file:
        for case in cases:
            issue_source = case.get("issue") or case.get("issue_text") or case.get("issue_file")
            record = {
                "id": case.get("id") or case.get("instance_id"),
                "repo": case.get("repo"),
                "issue_source": issue_source,
                "resolved": bool(case.get("resolved", False)),
                "status": case.get("status", "pending"),
                "cost_usd": float(case.get("cost_usd") or 0.0),
                "model_profile": case.get("model_profile") or case.get("model") or "default",
            }
            file.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
    return len(cases)


def _load_cases(cases_path: str | Path | None) -> list[dict[str, Any]]:
    if cases_path is None:
        return []
    path = Path(cases_path).expanduser().resolve()
    if path.suffix.lower() == ".json":
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return [record for record in data if isinstance(record, dict)]
        if isinstance(data, dict) and isinstance(data.get("cases"), list):
            return [record for record in data["cases"] if isinstance(record, dict)]
        return []
    return load_jsonl(path)
