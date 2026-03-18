import logging

from .categorization import categorize_order_blocks
from .fractals import (
    fractal_offset_from_filter_fractal,
    isFractalHigh,
    isFractalLow,
)
from .helpers import is_order_block_in_list
from .pivots import find_horizontal_lines

logger = logging.getLogger(__name__)
delLines = True
fvgDistance = 3


def calculate_order_blocks(
    df, filter_fractal_length, candle_line_height, pico_line_length, pico_lookback
):
    horizontal_lines = find_horizontal_lines(
        df,
        length=pico_line_length,
        lookback=pico_lookback,
    )
    filterFractal = f"{filter_fractal_length}"
    fractalOffset = fractal_offset_from_filter_fractal(filterFractal)
    horizontal_lines.sort(key=lambda x: x["time"])
    bullish_order_blocks = []
    bearish_order_blocks = []
    fractals = []
    fractal_highs = []
    fractal_high_times = []
    fractal_lows = []
    fractal_low_times = []
    for i in range(len(df)):
        if isFractalHigh(df, i, filterFractal):
            fractal_high_value = df["high"][i - fractalOffset]
            fractal_high_time = df["open_time"][i - fractalOffset]
            fractal_highs.append(fractal_high_value)
            fractal_high_times.append(fractal_high_time)
            fractals.append(
                {
                    "type": "bearish",
                    "time": fractal_high_time,
                    "value": fractal_high_value,
                }
            )

        if isFractalLow(df, i, filterFractal):
            fractal_low_time = df["open_time"][i - fractalOffset]
            fractal_low_value = df["low"][i - fractalOffset]
            fractal_lows.append(fractal_low_value)
            fractal_low_times.append(fractal_low_time)
            fractals.append(
                {
                    "type": "bullish",
                    "time": fractal_low_time,
                    "value": fractal_low_value,
                }
            )

        close = df["close"][i]
        time = df["open_time"][i]
        low = df["low"][i]
        high = df["high"][i]

        # Bearish Loop
        if len(fractal_lows) > 0:
            logger.debug(
                f"Bearish Loop Num Low Fractals: {len(fractal_lows)} Time {time}"
            )
            for r in reversed(range(len(fractal_lows))):
                fractal_low_value = fractal_lows[r]
                fractal_low_time = fractal_low_times[r]
                if close < fractal_low_value:
                    idx = 0
                    maximum = low
                    gapIndex = 0

                    for k in reversed(range(len(df))):
                        bearish_gap = (
                            k > 2
                            and df["close"][k - 1] < df["low"][k - 2]
                            and df["high"][k] < df["low"][k - 2]
                        )

                        if df["open_time"][k] < fractal_low_time:
                            break

                        if df["close"][k] > df["open"][k] and df["high"][k] > maximum:
                            idx = k
                            maximum = df["high"][k]

                        if bearish_gap and df["high"][k] > maximum:
                            gapIndex = k - 2

                    if idx != 0:
                        is_fvg = (
                            gapIndex > 0
                            and gapIndex - idx >= 0
                            and gapIndex - idx <= (fvgDistance)
                        )
                        loc = (
                            df["open"][idx]
                            if candle_line_height.lower() == "body"
                            else df["low"][idx]
                        )
                        price = max(df["high"][idx : idx + 3])
                        start_time = df["open_time"][idx]
                        logger.debug(f"Bearish OB found at {start_time}")
                        fvg = "true" if is_fvg else "false"
                        bearish_order_blocks.append(
                            {
                                "timestamp": start_time.timestamp(),
                                "type": "bearish",
                                "time": start_time,
                                "price": float(price),
                                "loc": float(loc),
                                "fvg": fvg,
                                "pico": "false",
                                "successive_count": 0,
                                "recommended": "false",
                            }
                        )
                    else:
                        # logger.verbose("Bearish OB not found")
                        pass

                    fractal_lows.pop(r)
                    fractal_low_times.pop(r)

        # Bullish Loop
        if len(fractal_highs) > 0:
            logger.debug(
                "Bullish Loop Num High Fractals: %s Time %s"
                % (len(fractal_highs), time)
            )
            for r in reversed(range(len(fractal_highs))):
                fractal_high_value = fractal_highs[r]
                fractal_high_time = fractal_high_times[r]
                if close > fractal_high_value:
                    idx = 0
                    minimum = low
                    gapIndex = 0

                    for k in reversed(range(len(df))):
                        bullishGap = (
                            k > 2
                            and df["close"][k - 1] > df["high"][k - 2]
                            and df["low"][k] > df["high"][k - 2]
                        )
                        if df["open_time"][k] < fractal_high_time:
                            break

                        if df["close"][k] < df["open"][k] and df["low"][k] < minimum:
                            idx = k
                            minimum = df["low"][k]

                        if bullishGap:
                            gapIndex = k - 2

                    if idx != 0:
                        is_fvg = (
                            gapIndex > 0
                            and gapIndex - idx >= 0
                            and gapIndex - idx <= (fvgDistance)
                        )
                        loc = (
                            df["open"][idx]
                            if candle_line_height.lower() == "body"
                            else df["high"][idx]
                        )
                        price = min(df["low"][idx : idx + 3])
                        start_time = df["open_time"][idx]
                        logger.debug("Bullish OB found at {start_time}")
                        fvg = "true" if is_fvg else "false"
                        bullish_order_blocks.append(
                            {
                                "timestamp": start_time.timestamp(),
                                "type": "bullish",
                                "time": start_time,
                                "price": float(price),
                                "loc": float(loc),
                                "fvg": fvg,
                                "pico": "false",
                                "successive_count": 0,
                                "recommended": "false",
                            }
                        )
                    else:
                        # logger.debug("Bullish OB not found")
                        pass

                    fractal_highs.pop(r)
                    fractal_high_times.pop(r)

        # Deletion Logic
        if delLines and len(bearish_order_blocks) > 0:
            for index in reversed(range(len(bearish_order_blocks))):
                if (
                    high >= bearish_order_blocks[index]["price"]
                    and high >= bearish_order_blocks[index]["loc"]
                ):
                    bearish_order_blocks.pop(index)

        if delLines and len(bullish_order_blocks) > 0:
            for index in reversed(range(len(bullish_order_blocks))):
                if (
                    low <= bullish_order_blocks[index]["price"]
                    and low <= bullish_order_blocks[index]["loc"]
                ):
                    bullish_order_blocks.pop(index)
    order_blocks = bearish_order_blocks + bullish_order_blocks
    order_blocks_without_duplicates = []
    for order_block in order_blocks:
        if not is_order_block_in_list(order_blocks_without_duplicates, order_block):
            order_blocks_without_duplicates.append(order_block)

    order_blocks_without_duplicates = categorize_order_blocks(
        order_blocks_without_duplicates, horizontal_lines
    )

    return order_blocks_without_duplicates, fractals, horizontal_lines
