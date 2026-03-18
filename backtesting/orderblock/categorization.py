import pandas as pd


def categorize_order_blocks(order_blocks, horizontal_lines):
    for block in order_blocks:
        block["time"] = block["time"].tz_localize(None)
    for line in horizontal_lines:
        line["time"] = line["time"].tz_localize(None)

    order_blocks.sort(key=lambda x: x["time"])
    bullish_order_blocks = [ob for ob in order_blocks if ob["type"] == "bullish"]
    bearish_order_blocks = [ob for ob in order_blocks if ob["type"] == "bearish"]
    reversed_order_blocks = sorted(order_blocks, key=lambda x: x["time"], reverse=True)

    for ob in order_blocks:
        ob["recommended"] = "false"
        ob["pico"] = "false"
        ob["successive_count"] = 0

        if ob["type"].lower() == "bullish":
            successive_count = 1
            for other_ob in reversed_order_blocks:
                if other_ob["time"] >= ob["time"]:
                    continue

                is_bullish = other_ob["type"].lower() == "bullish"
                price_below = other_ob["price"] <= ob["price"]
                loc_above = other_ob["loc"] >= ob["price"]

                if is_bullish and price_below and loc_above:
                    successive_count += 1
                else:
                    break
            ob["successive_count"] = successive_count

        if ob["type"].lower() == "bearish":
            successive_count = 1
            for other_ob in reversed_order_blocks:
                if other_ob["time"] >= ob["time"]:
                    continue

                is_bearish = other_ob["type"].lower() == "bearish"
                price_above = other_ob["price"] >= ob["price"]
                loc_below = other_ob["loc"] <= ob["price"]

                if is_bearish and price_above and loc_below:
                    successive_count += 1
                else:
                    break
            ob["successive_count"] = successive_count

    has_recommended_bullish = False
    for index in range(len(bullish_order_blocks) - 1, -1, -1):
        current_order_block = bullish_order_blocks[index]
        next_order_block = bullish_order_blocks[index - 1] if index > 0 else None
        time_before = next_order_block["time"] if next_order_block else pd.Timestamp(0)
        resistance_line_in_between = next(
            (
                line
                for line in horizontal_lines
                if line["time"] > time_before
                and line["time"] < current_order_block["time"]
                and line["type"] == "resistance"
            ),
            None,
        )
        if resistance_line_in_between is not None:
            current_order_block["pico"] = "true"
            if not has_recommended_bullish:
                current_order_block["recommended"] = "true"
                has_recommended_bullish = True
    has_recommended_bearish = False
    for index in range(len(bearish_order_blocks) - 1, -1, -1):
        current_order_block = bearish_order_blocks[index]
        next_order_block = bearish_order_blocks[index - 1] if index > 0 else None
        time_before = next_order_block["time"] if next_order_block else pd.Timestamp(0)
        support_line_in_between = next(
            (
                line
                for line in horizontal_lines
                if line["time"] > time_before
                and line["time"] < current_order_block["time"]
                and line["type"] == "support"
            ),
            None,
        )
        if support_line_in_between is not None:
            current_order_block["pico"] = "true"
            if not has_recommended_bearish:
                current_order_block["recommended"] = "true"
                has_recommended_bearish = True

    return order_blocks
