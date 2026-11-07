"""Walk-forward evaluation: each week, retrain every model on all data before that week, then forecast it.

Like a forecasting service that refreshes its models weekly: each test day is still forecast using only
data from before it (no leakage), but later weeks have seen earlier holidays (e.g. Christmas before New Year).
By default every model is retrained from scratch each week, so all models follow the same procedure.
"""
import argparse

import numpy as np
import pandas as pd

from baselines import historical_average, lightgbm_forecast, same_hour_last_week
from common import TEST_START, evaluate, load, origins, report
from gnn import DEVICE, train_and_predict

FOLD = pd.Timedelta(days=7)        # retrain weekly
VALIDATION = pd.Timedelta(days=7)  # the last week before each fold is used for early stopping


def folds(data):
    end_of_data = data.times[-1] + pd.Timedelta(hours=1)
    for start in pd.date_range(TEST_START, data.times[-1].normalize(), freq="7D"):
        test = origins(data.times, start, min(start + FOLD, end_of_data), midnight_only=True)
        if len(test):
            yield start, test


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-gnn", action="store_true", help="baselines only (fast)")
    parser.add_argument("--weeks", type=int, default=0,
                        help="only the first N weeks (2 = Christmas, Boxing Day and New Year); 0 = all")
    parser.add_argument("--fine-tune", action="store_true",
                        help="later weeks continue from the previous week's model (faster, but not the same procedure as the baselines)")
    args = parser.parse_args()

    data = load()
    print(f"Training on {DEVICE}")
    gnn_variants = [] if args.skip_gnn else [(True, "GNN (graph + GRU)"), (False, "Same model without graph")]
    names = ["Historical average", "Same hour last week", "LightGBM"] + [name for _, name in gnn_variants]
    predictions = {name: [] for name in names}
    weights = {name: None for _, name in gnn_variants}  # only used with --fine-tune
    all_test_days = []

    for week_number, (start, test) in enumerate(folds(data)):
        if args.weeks and week_number >= args.weeks:
            break  # stop after the first N weeks
        train_end, valid_start = start, start - VALIDATION
        print(f"\nWeek starting {start:%a %d %b}: train on data before {train_end:%d %b}, forecast {len(test)} days")
        historical = historical_average(data, test, train_end)
        predictions["Historical average"].append(historical)
        predictions["Same hour last week"].append(same_hour_last_week(data, test, historical))
        predictions["LightGBM"].append(lightgbm_forecast(data, test, train_end, valid_start))
        for use_graph, name in gnn_variants:
            predicted, weights[name] = train_and_predict(
                data, use_graph, train_end, valid_start, test,
                init_state=weights[name] if args.fine_tune else None,
            )
            predictions[name].append(predicted)
        all_test_days.append(test)

    label = f"walk-forward, first {args.weeks} weeks" if args.weeks else "walk-forward"
    test_days = np.concatenate(all_test_days)
    print("\nWalk-forward results (every test day forecast by a model trained only on earlier data):")
    for name, parts in predictions.items():
        report(evaluate(f"{name} ({label})", np.concatenate(parts), data, test_days))


if __name__ == "__main__":
    main()
