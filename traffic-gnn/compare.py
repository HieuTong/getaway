"""Prints every model's results as a Markdown table, ready for the README."""
import json
from pathlib import Path

rows = [json.loads(p.read_text()) for p in sorted(Path("results").glob("*.json"))]
rows.sort(key=lambda r: (("walk-forward" in r["model"]), r["wape_public_holidays"] or 0))
print("| Model | WAPE, test period | WAPE, public holidays | Peak-hour error on holidays |")
print("|---|---|---|---|")
for r in rows:
    holiday = f"{r['wape_public_holidays']:.1%}" if r["wape_public_holidays"] is not None else "-"
    peak = f"{r['peak_hour_error']:.1f} h" if r["peak_hour_error"] is not None else "-"
    print(f"| {r['model']} | {r['wape_test']:.1%} | {holiday} | {peak} |")
