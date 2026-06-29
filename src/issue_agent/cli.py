from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .bench import summarize_korean_benchmark, write_swebench_predictions
from .config import load_config
from .errors import GiaError
from .issue import load_issue
from .metrics import compute_leaderboard, format_leaderboard, load_jsonl, sort_leaderboard
from .solver import IssueSolver, append_metadata


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="gia", description="Local-first GitHub issue agent")
    subparsers = parser.add_subparsers(dest="command", required=True)

    solve = subparsers.add_parser("solve", help="Solve a GitHub issue against a local repo")
    solve.add_argument("--repo", required=True, help="Path to the target git repository")
    issue_group = solve.add_mutually_exclusive_group(required=True)
    issue_group.add_argument("--issue", help="GitHub issue URL")
    issue_group.add_argument("--issue-file", help="Path to markdown/json issue file")
    issue_group.add_argument("--issue-text", help="Inline issue text")
    solve.add_argument("--config", help="Path to .gia.yaml")
    solve.add_argument("--sandbox", choices=["local", "docker"], help="Execution sandbox")
    solve.add_argument("--model-profile", help="Provider name to use as coder model")
    solve.add_argument(
        "--max-iters", type=int, default=3, help="Maximum patch/test/repair attempts"
    )
    solve.add_argument(
        "--diff-only", action="store_true", help="Generate a diff without applying checks"
    )
    solve.add_argument("--out-diff", help="Write final diff to this path")
    solve.add_argument("--metadata-out", help="Append run metadata JSONL to this path")
    solve.set_defaults(func=_solve)

    bench = subparsers.add_parser("bench", help="Benchmark helpers")
    bench_subparsers = bench.add_subparsers(dest="bench_command", required=True)
    swebench = bench_subparsers.add_parser("swebench", help="Write SWE-bench prediction JSONL")
    swebench.add_argument("--dataset", choices=["lite", "verified"], required=True)
    swebench.add_argument("--limit", type=int)
    swebench.add_argument("--predictions", required=True)
    swebench.add_argument("--cases", help="Local SWE-bench-style cases JSON/JSONL")
    swebench.add_argument("--model-name", default="gia-local")
    swebench.set_defaults(func=_bench_swebench)

    korean = bench_subparsers.add_parser("korean", help="Summarize Korean issue benchmark cases")
    korean.add_argument("--cases", required=True)
    korean.add_argument("--out", required=True)
    korean.set_defaults(func=_bench_korean)

    leaderboard = subparsers.add_parser("leaderboard", help="Print resolved/$ leaderboard")
    leaderboard.add_argument("--runs", required=True, help="Run metadata JSONL")
    leaderboard.add_argument(
        "--sort", choices=["resolved_per_dollar", "resolved", "cost"], default="resolved_per_dollar"
    )
    leaderboard.set_defaults(func=_leaderboard)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args) or 0)
    except GiaError as exc:
        print(f"gia: error: {exc}", file=sys.stderr)
        return 1


def _solve(args: argparse.Namespace) -> int:
    config = load_config(args.repo, args.config)
    sandbox = args.sandbox or config.sandbox.default
    issue = load_issue(issue_url=args.issue, issue_file=args.issue_file, issue_text=args.issue_text)
    solver = IssueSolver(
        config=config,
        sandbox=sandbox,
        model_profile=args.model_profile,
        max_iters=args.max_iters,
    )
    result = solver.solve(repo=args.repo, issue=issue, diff_only=args.diff_only)
    if args.out_diff:
        Path(args.out_diff).expanduser().resolve().write_text(result.diff, encoding="utf-8")
    else:
        print(result.diff, end="")
    if args.metadata_out:
        append_metadata(args.metadata_out, result.metadata)
    summary = json.dumps(_summary(result.metadata), ensure_ascii=False, sort_keys=True)
    print(summary, file=sys.stderr)
    return 0 if result.resolved or args.diff_only else 2


def _bench_swebench(args: argparse.Namespace) -> int:
    count = write_swebench_predictions(
        predictions_path=args.predictions,
        dataset=args.dataset,
        limit=args.limit,
        cases_path=args.cases,
        model_name=args.model_name,
    )
    print(f"wrote {count} predictions to {args.predictions}")
    return 0


def _bench_korean(args: argparse.Namespace) -> int:
    count = summarize_korean_benchmark(cases_path=args.cases, out_path=args.out)
    print(f"wrote {count} run records to {args.out}")
    return 0


def _leaderboard(args: argparse.Namespace) -> int:
    records = load_jsonl(args.runs)
    rows = sort_leaderboard(compute_leaderboard(records), sort_key=args.sort)
    print(format_leaderboard(rows))
    return 0


def _summary(metadata: dict[str, object]) -> dict[str, object]:
    return {
        "resolved": metadata.get("resolved"),
        "status": metadata.get("status"),
        "attempt_count": metadata.get("attempt_count"),
        "cost_usd": metadata.get("cost_usd"),
        "sandbox": metadata.get("sandbox"),
    }
