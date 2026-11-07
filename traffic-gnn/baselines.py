"""Day 2: three baselines the GNN has to beat.

Each function takes the training cut-off as a parameter, so the same code serves the fixed split
(this file) and walk-forward evaluation (walk_forward.py).
"""
import lightgbm as lgb
import numpy as np
import pandas as pd

from common import HORIZON, TRAIN_END, VALID_START, WEEK, calendar_features, evaluate, load, origins, report, test_origins


def historical_average(data, test, train_end) -> np.ndarray:
    """Mean for this weekday, hour and intersection, using only data before train_end."""
    in_train = data.times < train_end
    frame = pd.DataFrame(data.volumes[in_train], index=data.times[in_train])
    profile = frame.groupby([frame.index.dayofweek, frame.index.hour]).mean()
    profile = profile.fillna(frame.mean())  # a weekday-hour with no data falls back to the overall mean

    def average_for(hours: pd.DatetimeIndex) -> np.ndarray:
        return profile.loc[list(zip(hours.dayofweek, hours.hour))].to_numpy()

    return np.stack([average_for(data.times[o:o + HORIZON]).T for o in test])


def same_hour_last_week(data, test, fallback: np.ndarray) -> np.ndarray:
    """Last week's value for each hour; missing values filled from `fallback`."""
    last_week = np.stack([data.volumes[o - WEEK:o - WEEK + HORIZON].T for o in test])
    return np.where(np.isnan(last_week), fallback, last_week)


def lightgbm_forecast(data, test, train_end, valid_start) -> np.ndarray:
    """LightGBM with the same information the GNN gets (recent hours, last week, calendar)."""
    volumes, times = data.volumes, data.times
    n_sites = volumes.shape[1]
    calendar = calendar_features(times)
    site_level = np.nanmean(volumes[times < train_end], axis=0)

    def rows(origin_list: np.ndarray):
        features, targets = [], []
        for o in origin_list:
            recent_mean = np.nanmean(volumes[o - 24:o], axis=0)
            for h in range(HORIZON):
                t = o + h
                features.append(np.column_stack([
                    np.arange(n_sites),                 # which intersection (categorical)
                    np.full(n_sites, h),                # how far ahead
                    np.full(n_sites, times[t].hour),
                    np.full(n_sites, times[t].dayofweek),
                    np.full(n_sites, calendar[t, 4]),   # public holiday
                    np.full(n_sites, calendar[t, 5]),   # school holiday
                    volumes[o - 1],                     # last observed hour
                    recent_mean,                        # level over the last day
                    volumes[t - 24],                    # same hour yesterday
                    volumes[t - WEEK],                  # same hour last week
                    site_level,                         # typical size of this intersection
                ]))
                targets.append(volumes[t])
        return np.concatenate(features), np.concatenate(targets)

    train_x, train_y = rows(origins(times, times[0], valid_start, every_hours=6))
    valid_x, valid_y = rows(origins(times, valid_start, train_end, every_hours=6))
    keep_train, keep_valid = ~np.isnan(train_y), ~np.isnan(valid_y)

    model = lgb.LGBMRegressor(objective="regression_l1", n_estimators=1000, learning_rate=0.05,
                              num_leaves=63, verbose=-1)
    model.fit(train_x[keep_train], train_y[keep_train],
              eval_set=[(valid_x[keep_valid], valid_y[keep_valid])],
              categorical_feature=[0],
              callbacks=[lgb.early_stopping(50, verbose=False)])

    test_x, _ = rows(test)
    predicted = model.predict(test_x).reshape(len(test), HORIZON, n_sites).transpose(0, 2, 1)
    return np.clip(predicted, 0, None)


def main() -> None:
    data = load()
    test = test_origins(data)
    print(f"{len(test)} test days, {data.volumes.shape[1]} intersections\n")
    historical = historical_average(data, test, TRAIN_END)
    report(evaluate("Historical average", historical, data, test))
    report(evaluate("Same hour last week", same_hour_last_week(data, test, historical), data, test))
    report(evaluate("LightGBM", lightgbm_forecast(data, test, TRAIN_END, VALID_START), data, test))


if __name__ == "__main__":
    main()
