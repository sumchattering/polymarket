import pandas as pd


def find_pivot_highs(df, length):
    pivot_highs = [None] * len(df)
    for i in range(length, len(df) - length):
        window = df["high"][i - length : i + length + 1]
        if df["high"][i] == max(window):
            pivot_highs[i] = df["high"][i]
    return pivot_highs


def find_pivot_lows(df, length):
    pivot_lows = [None] * len(df)
    for i in range(length, len(df) - length):
        window = df["low"][i - length : i + length + 1]
        if df["low"][i] == min(window):
            pivot_lows[i] = df["low"][i]
    return pivot_lows


def find_horizontal_lines(df, length, lookback):
    lines = []

    df["pivot_high"] = find_pivot_highs(df, length)
    df["pivot_low"] = find_pivot_lows(df, length)

    ph_array = []
    pl_array = []

    for index, row in df.iterrows():
        ph = row["pivot_high"]
        pl = row["pivot_low"]
        open_time = row["open_time"]

        if ph is not None and pd.notna(ph):
            ph_array.insert(0, (ph, index, open_time))

        if pl is not None and pd.notna(pl):
            pl_array.insert(0, (pl, index, open_time))

    for i in range(min(lookback, len(ph_array))):
        ph, _, open_time = ph_array[i]
        lines.append(
            {
                "timestamp": open_time.timestamp(),
                "time": open_time,
                "value": ph,
                "type": "resistance",
            }
        )

    for i in range(min(lookback, len(pl_array))):
        pl, _, open_time = pl_array[i]
        lines.append(
            {
                "timestamp": open_time.timestamp(),
                "time": open_time,
                "value": pl,
                "type": "support",
            }
        )

    return lines
