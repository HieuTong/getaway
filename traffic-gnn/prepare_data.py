"""Day 1: build a small traffic graph for the Nepean Highway corridor from Victoria's open SCATS data.

Outputs (in data/):
  corridor_sites.csv   - the intersections used as graph nodes
  hourly_volumes.csv   - hourly vehicle counts: one row per hour, one column per intersection
  adjacency.npy        - which intersections are connected (within EDGE_KM of each other)
"""
import io
import math
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd

RAW = Path("data/raw")
OUT = Path("data")

CORRIDOR_KEYWORD = "NEPEAN"        # Nepean Highway: St Kilda to Frankston, the bayside beach route
LAT_RANGE = (-38.25, -37.85)       # roughly St Kilda (north) to Frankston (south)
EDGE_KM = 1.5                      # intersections closer than this are treated as connected
MAX_MISSING_SHARE = 0.10           # drop intersections missing more than 10% of their hours

VOLUME_COLUMNS = [f"V{i:02d}" for i in range(96)]  # 96 x 15-minute counts per day
KEEP_COLUMNS = {"NB_SCATS_SITE", "QT_INTERVAL_COUNT", "NB_DETECTOR", "CT_RECORDS", "CT_ALARM_24HOUR", *VOLUME_COLUMNS}


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distance between two points on Earth, in kilometres."""
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def load_corridor_sites() -> pd.DataFrame:
    signals = pd.read_csv(RAW / "victorian_traffic_signals.csv", encoding="utf-8-sig")
    signals.columns = [c.strip().upper() for c in signals.columns]
    on_corridor = (
        (signals["TYPE"] == "INT")
        & signals["SITE_NAME"].str.upper().str.contains(CORRIDOR_KEYWORD, na=False)
        & signals["LATITUDE"].between(*LAT_RANGE)
    )
    sites = signals.loc[on_corridor, ["SITE_NO", "SITE_NAME", "LATITUDE", "LONGITUDE"]]
    return sites.sort_values("LATITUDE", ascending=False).reset_index(drop=True)  # north to south


def volume_sources() -> list[Path]:
    """Every traffic-count file under data/raw: ZIPs or CSVs, including inside folders (e.g. Safari auto-unzips)."""
    return sorted(
        path for path in RAW.rglob("*")
        if path.suffix.lower() in {".zip", ".csv"} and path.name != "victorian_traffic_signals.csv"
    )


def iter_csv_files(zip_path: Path):
    """Yields every CSV inside a ZIP, including CSVs inside nested ZIPs."""
    if zip_path.suffix.lower() == ".csv":  # a plain CSV, not an archive
        with open(zip_path, "rb") as handle:
            yield zip_path.name, handle
        return
    with zipfile.ZipFile(zip_path) as archive:
        for name in archive.namelist():
            lower = name.lower()
            if lower.endswith(".csv"):
                with archive.open(name) as handle:
                    yield name, handle
            elif lower.endswith(".zip"):
                inner = zipfile.ZipFile(io.BytesIO(archive.read(name)))
                for inner_name in inner.namelist():
                    if inner_name.lower().endswith(".csv"):
                        with inner.open(inner_name) as handle:
                            yield inner_name, handle


def load_daily_site_volumes(site_ids: set[int]) -> pd.DataFrame:
    """One row per (site, day) with 96 x 15-minute counts, summed over that site's healthy detectors."""
    pieces = []
    for zip_path in volume_sources():
        print(f"reading {zip_path.name}")
        for _, handle in iter_csv_files(zip_path):
            frame = pd.read_csv(handle, usecols=lambda c: c.strip().upper() in KEEP_COLUMNS)
            frame.columns = [c.strip().upper() for c in frame.columns]
            frame = frame[frame["NB_SCATS_SITE"].isin(site_ids)]
            if frame.empty:
                continue
            # Data quality: keep only detectors with a full day of readings and no alarms.
            frame = frame[(frame["CT_RECORDS"] == 96) & (frame["CT_ALARM_24HOUR"] == 0)]
            frame[VOLUME_COLUMNS] = frame[VOLUME_COLUMNS].clip(lower=0)  # negative counts are error codes
            frame["DAY"] = pd.to_datetime(frame["QT_INTERVAL_COUNT"]).dt.normalize()
            pieces.append(frame.groupby(["NB_SCATS_SITE", "DAY"])[VOLUME_COLUMNS].sum())
    if not pieces:
        raise SystemExit("No volume data found for the corridor. Check the ZIP files in data/raw/.")
    return pd.concat(pieces).groupby(level=[0, 1]).sum()


def to_hourly_matrix(daily: pd.DataFrame) -> pd.DataFrame:
    """Rows = hourly timestamps, columns = site numbers, values = vehicles in that hour."""
    hourly = daily.to_numpy().reshape(len(daily), 24, 4).sum(axis=2)  # four 15-minute counts -> one hour
    rows = []
    for (site, day), counts in zip(daily.index, hourly):
        for hour, count in enumerate(counts):
            rows.append((day + pd.Timedelta(hours=hour), site, count))
    long = pd.DataFrame(rows, columns=["TIME", "SITE_NO", "VOLUME"])
    wide = long.pivot_table(index="TIME", columns="SITE_NO", values="VOLUME")
    full_range = pd.date_range(wide.index.min(), wide.index.max(), freq="h")
    return wide.reindex(full_range)  # missing hours become visible gaps (NaN), not silently skipped


def build_adjacency(sites: pd.DataFrame) -> np.ndarray:
    n = len(sites)
    adjacency = np.zeros((n, n), dtype=np.float32)
    for i in range(n):
        for j in range(n):
            if i != j and haversine_km(sites.LATITUDE[i], sites.LONGITUDE[i],
                                       sites.LATITUDE[j], sites.LONGITUDE[j]) <= EDGE_KM:
                adjacency[i, j] = 1.0
    return adjacency


def main() -> None:
    sites = load_corridor_sites()
    print(f"{len(sites)} signalised intersections on the corridor")

    daily = load_daily_site_volumes(set(sites["SITE_NO"]))
    volumes = to_hourly_matrix(daily)

    missing_share = volumes.isna().mean()
    kept = missing_share[missing_share <= MAX_MISSING_SHARE].index
    print(f"{volumes.shape[1]} intersections have counts; {len(kept)} kept after the missing-data check")

    sites = sites[sites["SITE_NO"].isin(kept)].reset_index(drop=True)
    volumes = volumes[sites["SITE_NO"]]
    adjacency = build_adjacency(sites)

    OUT.mkdir(exist_ok=True)
    sites.to_csv(OUT / "corridor_sites.csv", index=False)
    volumes.to_csv(OUT / "hourly_volumes.csv", index_label="TIME")
    np.save(OUT / "adjacency.npy", adjacency)

    print(f"hours: {volumes.index.min()} to {volumes.index.max()} ({len(volumes)} rows)")
    print(f"graph: {len(sites)} nodes, {int(adjacency.sum())} directed edges")

    # A first look: total corridor traffic by hour on Boxing Day vs an ordinary December Friday.
    total = volumes.sum(axis=1, min_count=1)
    for label, day in [("Boxing Day 2025", "2025-12-26"), ("Friday 12 Dec 2025", "2025-12-12")]:
        day_total = total.loc[day] if day in total.index.strftime("%Y-%m-%d") else None
        if day_total is not None and day_total.notna().any():
            peak = day_total.idxmax()
            print(f"{label}: busiest hour {peak:%H}:00 with {int(day_total.max()):,} detector counts (summed over all corridor intersections)")


if __name__ == "__main__":
    main()
