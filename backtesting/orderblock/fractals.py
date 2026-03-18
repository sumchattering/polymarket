

def fractal_offset_from_filter_fractal(filterFractal):
    if filterFractal == "3":
        fractalOffset = 1
    elif filterFractal == "5":
        fractalOffset = 2
    else:
        raise Exception("Invalid filterFractal" + filterFractal)
    return fractalOffset


def isRegularFractal(mode, df, index):
    if index < 3:
        return False
    if mode == "Buy":
        ret = df["high"][index] < df["high"][index - 1] and (
            df["high"][index - 2] < df["high"][index - 1]
            or df["high"][index - 2] == df["high"][index - 1]
            and df["high"][index - 3] < df["high"][index - 2]
        )
    elif mode == "Sell":
        ret = df["low"][index] > df["low"][index - 1] and (
            df["low"][index - 2] > df["low"][index - 1]
            or df["low"][index - 2] == df["low"][index - 1]
            and df["low"][index - 3] > df["low"][index - 2]
        )
    else:
        raise Exception("Invalid mode " + mode)
    return ret


def isBWFractal(mode, df, index):
    if index < 4:
        return False
    if mode == "Buy":
        return (
            df["high"][index] < df["high"][index - 2]
            and df["high"][index - 1] < df["high"][index - 2]
            and df["high"][index - 3] < df["high"][index - 2]
            and df["high"][index - 4] < df["high"][index - 2]
        )
    elif mode == "Sell":
        return (
            df["low"][index] > df["low"][index - 2]
            and df["low"][index - 1] > df["low"][index - 2]
            and df["low"][index - 3] > df["low"][index - 2]
            and df["low"][index - 4] > df["low"][index - 2]
        )
    else:
        raise Exception("Invalid mode " + mode)


def isFractalHigh(df, index, filterFractal):
    if index < 0 or index > len(df) - 1:
        return False
    if filterFractal == "3":
        return isRegularFractal("Buy", df, index)
    elif filterFractal == "5":
        return isBWFractal("Buy", df, index)


def isFractalLow(df, index, filterFractal):
    if index < 0 or index > len(df) - 1:
        return False
    if filterFractal == "3":
        return isRegularFractal("Sell", df, index)
    elif filterFractal == "5":
        return isBWFractal("Sell", df, index)
