"""Agent evaluation: runs realistic requests through the real planner and checks every answer automatically.

Run from backend/:   python -m evals.run_eval
Uses the real Places, Routes and Gemini APIs (about one Gemini call per case), so it is run by hand, not in CI.
"""
import argparse
import json
import statistics
import time
from datetime import date, datetime
from pathlib import Path

from app import tools
from app.agent import plan_trip

HERE = Path(__file__).parent
ORIGIN = (-37.8136, 144.9631)  # Melbourne CBD


def to_minutes(hhmm: str) -> int:
    hours, minutes = hhmm.strip().split(":")[:2]
    return int(hours) * 60 + int(minutes[:2])


def clock(total_minutes: int) -> str:
    return f"{total_minutes // 60:02d}:{total_minutes % 60:02d}"


def check_case(case: dict, plan) -> list[dict]:
    """Rule-based checks for every suggestion. Plain code, so it is fast, free and repeatable."""
    sunset = to_minutes(tools.sunset_time(*ORIGIN, date.fromisoformat(case["trip_date"])))
    checks = []

    def add(suggestion, name: str, passed: bool, detail: str):
        checks.append({"place": suggestion.name, "check": name, "passed": passed, "detail": detail})

    for s in plan.suggestions:
        limit = case.get("max_drive_minutes")
        if limit is not None:
            add(s, "within_drive_limit", s.drive_minutes is not None and s.drive_minutes <= limit,
                f"{s.drive_minutes} min vs limit {limit}")
        if case.get("before_dark"):
            if s.leave_by is None or s.drive_minutes is None:
                add(s, "back_before_dark", False, "missing leave_by or drive time")
            else:
                try:
                    back = to_minutes(s.leave_by) + 2 * s.drive_minutes + int(case.get("activity_hours", 2) * 60)
                    add(s, "back_before_dark", back <= sunset, f"back about {clock(back)}, sunset {clock(sunset)}")
                except ValueError:
                    add(s, "back_before_dark", False, f"unreadable leave_by {s.leave_by!r}")
        words = case.get("expect_any", [])
        if words:
            text = f"{s.name} {s.reason}".lower()
            add(s, "relevant", any(word in text for word in words), f"expects one of {words}")
    return checks


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0, help="run only the first N cases")
    parser.add_argument("--pause", type=float, default=6.0,
                        help="seconds between cases, to stay under the free tier's per-minute limit")
    args = parser.parse_args()

    cases = json.loads((HERE / "cases.json").read_text())
    if args.limit:
        cases = cases[:args.limit]

    results = []
    for i, case in enumerate(cases, start=1):
        started = time.perf_counter()
        try:
            plan = plan_trip(case["query"], *ORIGIN, date.fromisoformat(case["trip_date"]), use_cache=False)
            error = None
        except Exception as exc:  # an evaluation records failures instead of stopping
            plan, error = None, f"{type(exc).__name__}: {exc}"
        seconds = time.perf_counter() - started

        checks = check_case(case, plan) if plan else []
        failed = [c for c in checks if not c["passed"]]
        results.append({
            "id": case["id"],
            "query": case["query"],
            "seconds": round(seconds, 1),
            "error": error,
            "used_ai": plan.used_ai if plan else None,
            "suggestions": [s.model_dump() for s in plan.suggestions] if plan else [],
            "checks": checks,
        })

        planner = "error" if error else ("AI" if plan.used_ai else "fallback")
        status = "ERROR" if error else ("PASS" if not failed else "FAIL")
        count = len(plan.suggestions) if plan else 0
        print(f"[{i:2d}/{len(cases)}] {status:5} {seconds:5.1f}s {planner:8} {count} picks  {case['id']}")
        for check in failed:
            print(f"        x {check['check']}: {check['place']} ({check['detail']})")
        if error:
            print(f"        x {error}")
        if i < len(cases):
            time.sleep(args.pause)

    summarise(results)


def summarise(results: list[dict]) -> None:
    def rate(items) -> str:
        items = list(items)
        return f"{sum(items)}/{len(items)} ({sum(items) / len(items):.0%})" if items else "n/a"

    all_checks = [c for r in results for c in r["checks"]]
    latencies = sorted(r["seconds"] for r in results if not r["error"])
    answered = [r for r in results if not r["error"] and r["suggestions"]]

    summary = {
        "cases": len(results),
        "answered_with_picks": rate(bool(not r["error"] and r["suggestions"]) for r in results),
        "answered_by_ai": rate(bool(r["used_ai"]) for r in results if not r["error"]),
        "within_drive_limit": rate(c["passed"] for c in all_checks if c["check"] == "within_drive_limit"),
        "back_before_dark": rate(c["passed"] for c in all_checks if c["check"] == "back_before_dark"),
        "relevant": rate(c["passed"] for c in all_checks if c["check"] == "relevant"),
        "median_seconds": round(statistics.median(latencies), 1) if latencies else None,
        "slowest_seconds": latencies[-1] if latencies else None,
        "picks_per_answered_case": round(statistics.mean(len(r["suggestions"]) for r in answered), 1) if answered else 0,
    }

    print("\n| Metric | Result |\n|---|---|")
    for key, value in summary.items():
        print(f"| {key.replace('_', ' ')} | {value} |")

    stamp = datetime.now().strftime("%Y-%m-%d_%H%M")
    output = HERE / "results" / f"eval_{stamp}.json"
    output.write_text(json.dumps({"summary": summary, "results": results}, indent=2))
    print(f"\nFull results saved to {output}")


if __name__ == "__main__":
    main()
