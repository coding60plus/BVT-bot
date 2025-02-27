from tradingview_ta import TA_Handler, Interval, Exchange

# use for environment variables
import os

# use if needed to pass args to external modules
import sys

# used for directory handling
import glob

import time

# load get config module
from helpers.get_config import config

data, _ = config()

EXCHANGE = data["EXCHANGE"]
SCREENER = data["SCREENER"]
PAIR_WITH = data["PAIR_WITH"]
TICKERS = data["TICKERS_LIST"]
TIME_TO_WAIT = data["TIME_TO_WAIT"]  # Minutes to wait between analysis
FULL_LOG = data["FULL_LOG"]  # List anylysis result to console
FIRST_INTERVAL = Interval.INTERVAL_1_MINUTE
SECOND_INTERVAL = Interval.INTERVAL_5_MINUTES
TA_BUY_THRESHOLD = 18  # How many of the 26 indicators to indicate a buy


def analyze(pairs):
    taMax = 0
    taMaxCoin = "none"
    signal_coins = {}
    first_analysis = {}
    second_analysis = {}
    first_handler = {}
    second_handler = {}
    if os.path.exists("signals/signalsample.exs"):
        os.remove("signals/signalsample.exs")

    for pair in pairs:
        first_handler[pair] = TA_Handler(symbol=pair, exchange=EXCHANGE, screener=SCREENER, interval=FIRST_INTERVAL, timeout=10)
        second_handler[pair] = TA_Handler(symbol=pair, exchange=EXCHANGE, screener=SCREENER, interval=SECOND_INTERVAL, timeout=10)

    for pair in pairs:

        try:
            first_analysis = first_handler[pair].get_analysis()
            second_analysis = second_handler[pair].get_analysis()
        except Exception as e:
            print("Signalsample:")
            print("Exception:")
            print(e)
            print(f"Coin: {pair}")
            print(f"First handler: {first_handler[pair]}")
            print(f"Second handler: {second_handler[pair]}")
            tacheckS = 0

        first_tacheck = first_analysis.summary["BUY"]
        second_tacheck = second_analysis.summary["BUY"]
        if FULL_LOG:
            print(f"Signalsample:{pair} First {first_tacheck} Second {second_tacheck}")
        # else:
        # print(".", end = '')

        if first_tacheck > taMax:
            taMax = first_tacheck
            taMaxCoin = pair
        if first_tacheck >= TA_BUY_THRESHOLD and second_tacheck >= TA_BUY_THRESHOLD:
            signal_coins[pair] = pair
            print(f"Signalsample: Signal detected on {pair}")
            with open("signals/signalsample.exs", "a+") as f:
                f.write(pair + "\n")
    print(f"Signalsample: Max signal by {taMaxCoin} at {taMax} on shortest timeframe")

    return signal_coins


def process():
    signal_coins = {}
    pairs = {}

    pairs = [line.strip() for line in open(TICKERS)]
    for line in open(TICKERS):
        pairs = [line.strip() + PAIR_WITH for line in open(TICKERS)]

    while True:
        print(f"Signalsample: Analyzing {len(pairs)} coins")
        signal_coins = analyze(pairs)
        if len(signal_coins) == 0:
            print(f"Signalsample: No coins above {TA_BUY_THRESHOLD} threshold on both timeframes. Waiting {TIME_TO_WAIT} minutes for next analysis")
        else:
            print(f"Signalsample: {len(signal_coins)} coins above {TA_BUY_THRESHOLD} treshold on both timeframes. Waiting {TIME_TO_WAIT} minutes for next analysis")

        time.sleep((TIME_TO_WAIT * 60))
