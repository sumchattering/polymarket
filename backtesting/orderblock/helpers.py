def find_matching_order_blocks(line, order_blocks):
    matching_order_blocks = []
    for order_block in order_blocks:
        if order_block["time"] == line["time"]:
            if (order_block["type"] == "bullish" and line["type"] == "support") or (
                order_block["type"] == "bearish" and line["type"] == "resistance"
            ):
                matching_order_blocks.append(order_block)
    return matching_order_blocks


def find_close_order_blocks(line, order_blocks, tolerance):
    closest_order_blocks = []
    for order_block in order_blocks:
        if abs(line["value"] - order_block["price"]) < 0.000000001 + tolerance:
            if (order_block["type"] == "bullish" and line["type"] == "support") or (
                order_block["type"] == "bearish" and line["type"] == "resistance"
            ):
                closest_order_blocks.append(order_block)
    return closest_order_blocks


def find_average_order_block_size(order_blocks):
    total_size = 0
    for order_block in order_blocks:
        order_block_size = abs(order_block["price"] - order_block["loc"])
        total_size += order_block_size
    return total_size / len(order_blocks)


def is_order_block_in_list(order_blocks, order_block, full_match=False):
    for an_order_block in order_blocks:
        if full_match:
            if (
                an_order_block["time"] == order_block["time"]
                and an_order_block["price"] == order_block["price"]
                and an_order_block["loc"] == order_block["loc"]
                and an_order_block["type"] == order_block["type"]
                and an_order_block["fvg"] == order_block["fvg"]
                and an_order_block["pico"] == order_block["pico"]
            ):
                return True
        else:
            if (
                an_order_block["time"] == order_block["time"]
                and an_order_block["price"] == order_block["price"]
                and an_order_block["type"] == order_block["type"]
                and an_order_block["loc"] == order_block["loc"]
            ):
                return True
    return False
