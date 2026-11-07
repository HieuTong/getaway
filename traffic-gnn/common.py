"""Shared data loading, calendar features, train/test split and metrics for every model."""
import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

DATA = Path("data")
RESULTS = Path("results")

INPUT_HOURS = 24   # the model sees the last 24 hours...
HORIZON = 24       # ...and forecasts the next 24
WEEK = 168         # hours in a week, for "same hour last week" features

VALID_START = pd.Timestamp("2025-12-06")  # last two weeks before the test: early stopping only
TRAIN_END = pd.Timestamp("2025-12-20")    # all training data is before this date
TEST_START = TRAIN_END                    # test: 20 Dec 2025 - 31 Jan 2026, never seen in training

# Victorian public holidays in the data range.
PUBLIC_HOLIDAYS = ["2025-09-26", "2025-11-04", "2025-12-25", "2025-12-26", "2026-01-01", "2026-01-26"]
HOLIDAYS_OF_INTEREST = ["2025-12-25", "2025-12-26", "2026-01-01"]
# Victorian government school holidays (check against Victoria's published term dates).
SCHOOL_HOLIDAYS = [("2025-09-20", "2025-10-05"), ("2025-12-20", "2026-01-27")]


@dataclass
class Dataset:
    times: pd.DatetimeIndex
    volumes: np.ndarray    # [hours, intersections] detector counts; NaN where missing
    adjacency: np.ndarray  # [intersections, intersections] 1 = connected
    sites: pd.DataFrame


def load() -> Dataset:
    frame = pd.read_csv(DATA / "hourly_volumes.csv", index_col="TIME", parse_dates=["TIME"])
    return Dataset(
        times=frame.index,
        volumes=frame.to_numpy(dtype=np.float32),
        adjacency=np.load(DATA / "adjacency.npy"),
        sites=pd.read_csv(DATA / "corridor_sites.csv"),
    )


def calendar_features(times: pd.DatetimeIndex) -> np.ndarray:
    """[hours, 6]: hour and weekday as points on a circle, plus public and school holiday flags."""
    hour = times.hour.to_numpy()
    weekday = times.dayofweek.to_numpy()
    day = times.normalize()
    public = day.isin(pd.to_datetime(PUBLIC_HOLIDAYS)).astype(np.float32)
    school = np.zeros(len(times), dtype=np.float32)
    for start, end in SCHOOL_HOLIDAYS:
        school[(day >= start) & (day <= end)] = 1.0
    return np.stack([
        np.sin(2 * np.pi * hour / 24), np.cos(2 * np.pi * hour / 24),       # 23:00 is next to 00:00
        np.sin(2 * np.pi * weekday / 7), np.cos(2 * np.pi * weekday / 7),   # Sunday is next to Monday
        public, school,
    ], axis=1).astype(np.float32)


def origins(times: pd.DatetimeIndex, start, end, every_hours: int = 1, midnight_only: bool = False) -> np.ndarray:
    """Forecast start points o: inputs are hours o-24..o-1, targets o..o+23, all targets inside [start, end)."""
    chosen = []
    for o in range(WEEK, len(times) - HORIZON + 1):  # need a full week of history for weekly lags
        if times[o] < start or times[o + HORIZON - 1] >= end:
            continue
        if midnight_only and times[o].hour != 0:
            continue
        if not midnight_only and o % every_hours:
            continue
        chosen.append(o)
    return np.array(chosen)


def test_origins(data: Dataset) -> np.ndarray:
    """One forecast per test day, made at midnight: 'plan my day'."""
    return origins(data.times, TEST_START, data.times[-1] + pd.Timedelta(hours=1), midnight_only=True)


def evaluate(name: str, predictions: np.ndarray, data: Dataset, test: np.ndarray) -> dict:
    """predictions: [test days, intersections, 24 hours] in detector counts."""
    truth = np.stack([data.volumes[o:o + HORIZON].T for o in test])
    mask = ~np.isnan(truth)  # only score hours where real data exists

    def wape(rows) -> float:
        m = mask[rows]
        errors = np.abs(predictions[rows][m] - truth[rows][m]).sum()
        return float(errors / np.abs(truth[rows][m]).sum())

    days = [data.times[o].strftime("%Y-%m-%d") for o in test]
    holiday_rows = [i for i, day in enumerate(days) if day in HOLIDAYS_OF_INTEREST]
    peaks = {}
    for i in holiday_rows:
        actual = np.where(mask[i], truth[i], 0).sum(axis=0)          # corridor total per hour
        predicted = np.where(mask[i], predictions[i], 0).sum(axis=0)
        peaks[days[i]] = {
            "actual_peak": f"{int(actual.argmax()):02d}:00",
            "predicted_peak": f"{int(predicted.argmax()):02d}:00",
            "error_hours": int(abs(int(actual.argmax()) - int(predicted.argmax()))),
        }
    return {
        "model": name,
        "wape_test": wape(list(range(len(test)))),
        "wape_public_holidays": wape(holiday_rows) if holiday_rows else None,
        "peak_hour_error": float(np.mean([p["error_hours"] for p in peaks.values()])) if peaks else None,
        "holiday_peaks": peaks,
    }


def report(result: dict) -> None:
    holiday = result["wape_public_holidays"]
    print(f"{result['model']:<45} WAPE test {result['wape_test']:.1%}"
          f" | public holidays {holiday:.1%} | peak-hour error {result['peak_hour_error']:.1f} h")
    for day, peak in result["holiday_peaks"].items():
        print(f"    {day}: actual peak {peak['actual_peak']}, predicted {peak['predicted_peak']}")
    RESULTS.mkdir(exist_ok=True)
    slug = "".join(c if c.isalnum() else "_" for c in result["model"].lower()).strip("_")
    (RESULTS / f"{slug}.json").write_text(json.dumps(result, indent=2))
