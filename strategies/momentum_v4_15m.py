"""
Momentum V4 15m — RSI(21) 35/65 + ADX/CHOP trending filter on 15-minute markets.

Same signal logic as V4 but trades on 15m Polymarket windows.
For BTC/ETH, consider momentum_v4_candle5 instead (aggregates to 5m candles, higher WR).

Signal: RSI(21) on 1m < 35 -> UP (oversold reversal), > 65 -> DOWN (overbought reversal)
Filter: ADX(14) > 25 AND CHOP(14) < 50
"""
TIMEFRAME = "15m"

import os
import importlib.util

_dir = os.path.dirname(__file__)
_spec = importlib.util.spec_from_file_location("momentum_v4", os.path.join(_dir, "momentum_v4.py"))
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
generate_signal = _mod.generate_signal
