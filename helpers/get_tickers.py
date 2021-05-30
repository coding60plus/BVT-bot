from tradingview_ta import Interval, get_multiple_analysis

# load get config module
from helpers.get_config import config

data, _ = config()

EXCHANGE = data["EXCHANGE"]
SCREENER = data["SCREENER"]
FIRST_INTERVAL = Interval.INTERVAL_1_MINUTE
TICKER_THRESHOLD = 14  # How many of the 26 indicators to add ticker to list


def get_new_tickers(client, PAIR_WITH, FIATS):
    """Get all tickers that can be paired with current base currency"""
    prices = client.get_all_tickers()
    tickers = []
    pair_tickers = []
    analysis_tickers = []
    new_analysis = []

    # clears tickers.txt
    with open("tickers.txt", "r+") as handle:
        handle.truncate(0)

    for coin in prices:
        if coin["symbol"].endswith(PAIR_WITH) and all(item not in coin["symbol"] for item in FIATS):
            value = coin["symbol"]
            if value:
                pair_tickers.append(value)
                value = coin["symbol"].replace(PAIR_WITH, "")
                analysis_tickers.append(f"{EXCHANGE}:{coin['symbol']}")

    all_analysis = get_multiple_analysis(screener=SCREENER, interval=FIRST_INTERVAL, symbols=analysis_tickers)

    for analysis in all_analysis:
        # print("from analysis:", all_analysis[analysis].symbol)
        # if "BUY" in all_analysis[analysis].summary["RECOMMENDATION"]:
        if all_analysis[analysis].summary["BUY"] >= TICKER_THRESHOLD:
            index = analysis_tickers.index(analysis)
            ticker = pair_tickers[index].replace(PAIR_WITH, "")
            tickers.append(ticker)

    with open("tickers.txt", "a+") as handle:
        for ticker in tickers:
            handle.write(ticker + "\n")

    return tickers
