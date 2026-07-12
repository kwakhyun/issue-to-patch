from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class LeaderboardRow:
    model_profile: str
    runs: int
    resolved: int
    cost_usd: float
    resolved_per_dollar: float | None
    zero_cost: bool


def load_jsonl(path: str | Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    with Path(path).expanduser().open(encoding="utf-8") as file:
        for line in file:
            stripped = line.strip()
            if stripped:
                records.append(json.loads(stripped))
    return records


def compute_leaderboard(records: list[dict[str, Any]]) -> list[LeaderboardRow]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        key = _record_model_key(record)
        groups.setdefault(key, []).append(record)
    rows: list[LeaderboardRow] = []
    for key, group in groups.items():
        runs = len(group)
        resolved = sum(1 for record in group if bool(record.get("resolved")))
        cost = sum(float(record.get("cost_usd") or 0.0) for record in group)
        rows.append(
            LeaderboardRow(
                model_profile=key,
                runs=runs,
                resolved=resolved,
                cost_usd=cost,
                resolved_per_dollar=(resolved / cost if cost > 0 else None),
                zero_cost=cost == 0,
            )
        )
    return rows


def _record_model_key(record: dict[str, Any]) -> str:
    explicit = record.get("model_key")
    if explicit:
        return str(explicit)
    provider = record.get("model_provider")
    model = record.get("model")
    if provider and model:
        return f"{provider}:{model}"
    return str(record.get("model_profile") or model or provider or "default")


def sort_leaderboard(
    rows: list[LeaderboardRow], *, sort_key: str = "resolved_per_dollar"
) -> list[LeaderboardRow]:
    if sort_key == "resolved":
        return sorted(rows, key=lambda row: (row.resolved, -row.cost_usd), reverse=True)
    if sort_key == "cost":
        return sorted(rows, key=lambda row: row.cost_usd)
    return sorted(
        rows,
        key=lambda row: (
            row.resolved_per_dollar is not None,
            row.resolved_per_dollar or 0.0,
            row.resolved,
        ),
        reverse=True,
    )


def format_leaderboard(rows: list[LeaderboardRow]) -> str:
    headers = ["model_profile", "runs", "resolved", "cost_usd", "resolved/$", "zero_cost"]
    table = ["  ".join(headers)]
    for row in rows:
        resolved_per_dollar = (
            "n/a" if row.resolved_per_dollar is None else f"{row.resolved_per_dollar:.4f}"
        )
        table.append(
            "  ".join(
                [
                    row.model_profile,
                    str(row.runs),
                    str(row.resolved),
                    f"{row.cost_usd:.6f}",
                    resolved_per_dollar,
                    str(row.zero_cost).lower(),
                ]
            )
        )
    return "\n".join(table)
