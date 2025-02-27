# use for environment variables
import os
import sys
import threading
import importlib
import json
import glob

# Needed for colorful console output Install with: python3 -m pip install colorama (Mac/Linux) or pip install colorama (PC)
from colorama import init

init()

# used for dates
from datetime import date, datetime, timedelta
import time

from helpers.api_auth import auth
from helpers.get_tickers import get_new_tickers
from helpers.get_config import config
from helpers.colors import txcolors
from helpers.db import *

# tracks profit/loss each session
global session_profit
session_profit = 0

# over max_orders buy_coins() dont trade more
# global max_orders

# print with timestamps
old_out = sys.stdout


class TerminalOutput:
    """Stamped stdout."""

    nl = True

    def write(self, x):
        """Write function overloaded."""
        if x == "\n":
            old_out.write(x)
            self.nl = True
        elif self.nl:
            old_out.write(f"{txcolors.DIM}[{str(datetime.now().replace(microsecond=0))}]{txcolors.DEFAULT} {x}")
            self.nl = False
        else:
            old_out.write(x)

    def flush(self):
        pass


sys.stdout = TerminalOutput()


def is_fiat(PAIR_WITH):
    # check if we are using a fiat as a base currency
    global hsp_head
    # list below is in the order that Binance displays them, apologies for not using ASC order
    fiats = ["USDT", "BUSD", "AUD", "BRL", "EUR", "GBP", "RUB", "TRY", "TUSD", "USDC", "PAX", "BIDR", "DAI", "IDRT", "UAH", "NGN", "VAI", "BVND"]

    if PAIR_WITH in fiats:
        return True
    else:
        return False


def decimals(PAIR_WITH):
    # set number of decimals for reporting fractions
    if is_fiat(PAIR_WITH):
        return 2
    else:
        return 8


def get_price(add_to_historical=True):
    """Return the current price for all coins on binance"""

    global historical_prices, hsp_head

    initial_price = {}
    prices = client.get_all_tickers()

    for coin in prices:

        if CUSTOM_LIST:
            if any(item + PAIR_WITH == coin["symbol"] for item in tickers) and all(item not in coin["symbol"] for item in FIATS):
                initial_price[coin["symbol"]] = {"price": coin["price"], "time": datetime.now()}
        else:
            if PAIR_WITH in coin["symbol"] and all(item not in coin["symbol"] for item in FIATS):
                initial_price[coin["symbol"]] = {"price": coin["price"], "time": datetime.now()}

    if add_to_historical:
        hsp_head += 1

        if hsp_head == RECHECK_INTERVAL:
            hsp_head = 0

        historical_prices[hsp_head] = initial_price

    return initial_price


def wait_for_price():
    """calls the initial price and ensures the correct amount of time has passed
    before reading the current price again"""

    global historical_prices, hsp_head, volatility_cooloff

    volatile_coins = {}
    externals = {}

    coins_up = 0
    coins_down = 0
    coins_unchanged = 0

    pause_bot()

    if historical_prices[hsp_head]["BNB" + PAIR_WITH]["time"] > datetime.now() - timedelta(minutes=float(TIME_DIFFERENCE / RECHECK_INTERVAL)):

        # sleep for exactly the amount of time required
        time.sleep((timedelta(minutes=float(TIME_DIFFERENCE / RECHECK_INTERVAL)) - (datetime.now() - historical_prices[hsp_head]["BNB" + PAIR_WITH]["time"])).total_seconds())

    # print(
    #     f"Using {len(coins_bought)}/{TRADE_SLOTS} trade slots. Session profit: {session_profit:.2f}% - Est: {(QUANTITY * session_profit)/100:.{decimals(PAIR_WITH)}f} {PAIR_WITH}"
    # )  # retrieve latest prices

    get_price()

    # calculate the difference in prices
    for coin in historical_prices[hsp_head]:

        # minimum and maximum prices over time period
        min_price = min(historical_prices, key=lambda x: float("inf") if x is None else float(x[coin]["price"]))
        max_price = max(historical_prices, key=lambda x: -1 if x is None else float(x[coin]["price"]))

        threshold_check = (
            (-1.0 if min_price[coin]["time"] > max_price[coin]["time"] else 1.0)
            * (float(max_price[coin]["price"]) - float(min_price[coin]["price"]))
            / float(min_price[coin]["price"])
            * 100
        )

        # each coin with higher gains than our CHANGE_IN_PRICE is added to the volatile_coins dict if less than TRADE_SLOTS is not reached.
        if threshold_check > CHANGE_IN_PRICE:
            coins_up += 1

            if coin not in volatility_cooloff:
                volatility_cooloff[coin] = datetime.now() - timedelta(minutes=TIME_DIFFERENCE)

            # only include coin as volatile if it hasn't been picked up in the last TIME_DIFFERENCE minutes already
            if datetime.now() >= volatility_cooloff[coin] + timedelta(minutes=TIME_DIFFERENCE):
                volatility_cooloff[coin] = datetime.now()

                if len(coins_bought) + len(volatile_coins) < TRADE_SLOTS or TRADE_SLOTS == 0:
                    volatile_coins[coin] = round(threshold_check, 3)
                    print(f"{coin} has gained {volatile_coins[coin]}% within the last {TIME_DIFFERENCE} minutes, calculating {QUANTITY} {PAIR_WITH} value of {coin} for purchase!")

                else:
                    print(
                        f"{txcolors.WARNING}{coin} has gained {round(threshold_check, 3)}% within the last {TIME_DIFFERENCE} minutes, but you are using all available trade slots!{txcolors.DEFAULT}"
                    )

        elif threshold_check < CHANGE_IN_PRICE:
            coins_down += 1

        else:
            coins_unchanged += 1

    # Disabled until fix
    print(f"Up: {coins_up} Down: {coins_down} Unchanged: {coins_unchanged}")

    # Here goes new code for external signalling
    externals = external_signals()
    exnumber = 0

    for excoin in externals:
        if excoin not in volatile_coins and excoin not in coins_bought and (len(coins_bought) + exnumber) < TRADE_SLOTS:
            volatile_coins[excoin] = 1
            exnumber += 1
            print(f"External signal received on {excoin}, calculating {QUANTITY} {PAIR_WITH} value of {excoin} for purchase!")

    return volatile_coins, len(volatile_coins), historical_prices[hsp_head]


def external_signals():
    external_list = {}
    signals = {}

    # check directory and load pairs from files into external_list
    signals = glob.glob("signals/*.exs")
    for filename in signals:
        for line in open(filename):
            symbol = line.strip()
            external_list[symbol] = symbol
        try:
            os.remove(filename)
        except:
            if DEBUG:
                print(f"{txcolors.WARNING}Could not remove external signalling file{txcolors.DEFAULT}")

    return external_list


def balance_report():
    INVESTMENT_TOTAL = QUANTITY * TRADE_SLOTS
    CURRENT_EXPOSURE = QUANTITY * len(coins_bought)
    TOTAL_GAINS = (QUANTITY * session_profit) / 100
    NEW_BALANCE = INVESTMENT_TOTAL + TOTAL_GAINS
    INVESTMENT_GAIN = (TOTAL_GAINS / INVESTMENT_TOTAL) * 100

    print(f" ")
    print(
        f"Using {len(coins_bought)}/{TRADE_SLOTS} trade slots. Session profit: {(txcolors.SELL_LOSS if session_profit < 0. else txcolors.SELL_PROFIT)}{session_profit:.2f} %{txcolors.DEFAULT} - Est: {(txcolors.SELL_LOSS if TOTAL_GAINS < 0. else txcolors.SELL_PROFIT)}{TOTAL_GAINS:.{decimals(PAIR_WITH)}f} {PAIR_WITH}{txcolors.DEFAULT}"
    )
    print(
        f"Investment: {INVESTMENT_TOTAL:.{decimals(PAIR_WITH)}f} {PAIR_WITH}, Exposure: {CURRENT_EXPOSURE:.{decimals(PAIR_WITH)}f} {PAIR_WITH}, New balance: {(txcolors.SELL_LOSS if NEW_BALANCE < INVESTMENT_TOTAL else txcolors.SELL_PROFIT)}{NEW_BALANCE:.{decimals(PAIR_WITH)}f} {PAIR_WITH}{txcolors.DEFAULT}, Gains: {(txcolors.SELL_LOSS if INVESTMENT_GAIN < 0. else txcolors.SELL_PROFIT)}{INVESTMENT_GAIN:.2f}%{txcolors.DEFAULT}"
    )
    print(f"---------------------------------------------------------------------------------------------")
    print(f" ")

    return


def pause_bot():
    """Pause the script when external indicators detect a bearish trend in the market"""
    global bot_paused, session_profit, hsp_head

    # start counting for how long the bot has been paused
    start_time = time.perf_counter()

    while os.path.isfile("signals/paused.exc"):

        if bot_paused == False:
            print(f"{txcolors.WARNING}Buying paused due to negative market conditions, stop loss and take profit will continue to work...{txcolors.DEFAULT}")
            bot_paused = True

        # Sell function needs to work even while paused
        coins_sold = sell_coins()
        remove_from_portfolio(coins_sold)
        get_price(True)

        # pausing here
        if hsp_head == 1:
            print(
                f"Paused...Session profit:{(txcolors.SELL_LOSS if session_profit < 0. else txcolors.SELL_PROFIT)}{session_profit:.2f} %{txcolors.DEFAULT} - Est: {(txcolors.SELL_LOSS if ((QUANTITY * session_profit)/100) < 0. else txcolors.SELL_PROFIT)}{(QUANTITY * session_profit)/100:.{decimals(PAIR_WITH)}f} {PAIR_WITH}{txcolors.DEFAULT}"
            )
        time.sleep((TIME_DIFFERENCE * 60) / RECHECK_INTERVAL)

    else:
        # stop counting the pause time
        stop_time = time.perf_counter()
        time_elapsed = timedelta(seconds=int(stop_time - start_time))

        # resume the bot and ser pause_bot to False
        if bot_paused == True:
            print(f"{txcolors.WARNING}Resuming buying due to positive market conditions, total sleep time: {time_elapsed}{txcolors.DEFAULT}")
            bot_paused = False

    return


def convert_volume():
    """Converts the volume given in QUANTITY from USDT to the each coin's volume"""

    volatile_coins, number_of_coins, last_price = wait_for_price()
    lot_size = {}
    volume = {}

    for coin in volatile_coins:

        # Find the correct step size for each coin
        # max accuracy for BTC for example is 6 decimal points
        # while XRP is only 1
        try:
            info = client.get_symbol_info(coin)
            step_size = info["filters"][2]["stepSize"]
            lot_size[coin] = step_size.index("1") - 1

            if lot_size[coin] < 0:
                lot_size[coin] = 0

        except:
            pass

        # calculate the volume in coin from QUANTITY in USDT (default)
        volume[coin] = float(QUANTITY / float(last_price[coin]["price"]))

        # define the volume with the correct step size
        if coin not in lot_size:
            volume[coin] = float("{:.1f}".format(volume[coin]))

        else:
            # if lot size has 0 decimal points, make the volume an integer
            if lot_size[coin] == 0:
                volume[coin] = int(volume[coin])
            else:
                volume[coin] = float("{:.{}f}".format(volume[coin], lot_size[coin]))

    return volume, last_price


def buy_coins():
    """Place Buy market orders for each volatile coin found"""
    # global max_orders
    volume, last_price = convert_volume()
    orders = {}

    for coin in volume:

        # only buy if the there are no active trades on the coin
        # print("max_orders", max_orders)
        # if max_orders <= 0:
        #     print(f"max_orders reached, no more trade!!! Wait finish trade queue.")

        # if coin not in coins_bought and (max_orders > 0):
        if coin not in coins_bought:
            print(f"{txcolors.BUY}Preparing to buy {volume[coin]} {coin}{txcolors.DEFAULT}")
            # max_orders -= 1
            # print("max orders =", max_orders)

            if TEST_MODE:
                orders[coin] = [{"symbol": coin, "orderId": fake_orderid(), "time": datetime.now().timestamp()}]
                value = {"volume": volume[coin], "timestamp": time.time(), "action": "buy", "coin": str(coin), "buyPrice": float(last_price[coin]["price"])}
                if MONGO:
                    insert_trades(value, DATABASE_NAME)

                # Log trade
                if LOG_TRADES:
                    write_log(f"Buy : {volume[coin]} {coin} - {last_price[coin]['price']}")

                continue

            # try to create a real order if the test orders did not raise an exception
            try:
                buy_limit = client.create_order(symbol=coin, side="BUY", type="MARKET", quantity=volume[coin])

            # error handling here in case position cannot be placed
            except Exception as e:
                print(f"Error in buy_coins: {e}")

            # run the else block if the position has been placed and return order info
            else:
                orders[coin] = client.get_all_orders(symbol=coin, limit=1)

                # binance sometimes returns an empty list, the code will wait here until binance returns the order
                while orders[coin] == []:
                    print("Binance is being slow in returning the order, calling the API again...")

                    orders[coin] = client.get_all_orders(symbol=coin, limit=1)
                    time.sleep(1)

                else:
                    print("Order returned, saving order to file")
                    value = {"volume": volume[coin], "timestamp": time.time(), "action": "buy", "coin": str(coin), "buyPrice": float(last_price[coin]["price"])}
                    if MONGO:
                        insert_trades(value, DATABASE_NAME)

                    # Log trade
                    if LOG_TRADES:
                        write_log(f"Buy : {volume[coin]} {coin} - {last_price[coin]['price']}")

        else:
            print(f"Signal detected, but there is already an active trade on {coin}")

    return orders, last_price, volume


def sell_coins():
    """sell coins that have reached the STOP LOSS or TAKE PROFIT threshold"""

    global hsp_head, session_profit

    last_price = get_price(False)  # don't populate rolling window
    # last_price = get_price(add_to_historical=True) # don't populate rolling window
    coins_sold = {}

    for coin in list(coins_bought):
        # define stop loss and take profit
        TP = float(coins_bought[coin]["bought_at"]) + (float(coins_bought[coin]["bought_at"]) * coins_bought[coin]["take_profit"]) / 100
        SL = float(coins_bought[coin]["bought_at"]) + (float(coins_bought[coin]["bought_at"]) * coins_bought[coin]["stop_loss"]) / 100

        LastPrice = float(last_price[coin]["price"])
        BuyPrice = float(coins_bought[coin]["bought_at"])
        PriceChange = float((LastPrice - BuyPrice) / BuyPrice * 100)

        # sell fee below would ofc only apply if transaction was closed at the current LastPrice
        SellFee = LastPrice * (TRADING_FEE / 100)
        BuyFee = BuyPrice * (TRADING_FEE / 100)

        # check that the price is above the take profit and readjust SL and TP accordingly if trialing stop loss used
        if LastPrice > TP and USE_TRAILING_STOP_LOSS:

            # increasing TP by TRAILING_TAKE_PROFIT (essentially next time to readjust SL)
            coins_bought[coin]["take_profit"] = PriceChange + TRAILING_TAKE_PROFIT
            coins_bought[coin]["stop_loss"] = coins_bought[coin]["take_profit"] - TRAILING_STOP_LOSS
            if DEBUG:
                if DEBUG:
                    print(
                        f"{coin} TP reached, adjusting TP {coins_bought[coin]['take_profit']:.{decimals(PAIR_WITH)}f}  and SL {coins_bought[coin]['stop_loss']:.{decimals(PAIR_WITH)}f} accordingly to lock-in profit"
                    )
            continue

        # check that the price is below the stop loss or above take profit (if trailing stop loss not used) and sell if this is the case
        if LastPrice < SL or LastPrice > TP and not USE_TRAILING_STOP_LOSS:
            print(
                f"{txcolors.SELL_PROFIT if PriceChange >= 0. else txcolors.SELL_LOSS}TP or SL reached, selling {coins_bought[coin]['volume']} {coin} - {BuyPrice} - {LastPrice} : {PriceChange-(BuyFee+SellFee):.2f}% Est: {(QUANTITY*(PriceChange-(BuyFee+SellFee)))/100:.{decimals(PAIR_WITH)}f} {PAIR_WITH}{txcolors.DEFAULT}"
            )
            # try to create a real order
            try:

                if not TEST_MODE:
                    sell_coins_limit = client.create_order(symbol=coin, side="SELL", type="MARKET", quantity=coins_bought[coin]["volume"])

            # error handling here in case position cannot be placed
            except Exception as e:
                print(f"Error in sell_coins: {e}")

            # run the else block if coin has been sold and create a dict for each coin sold
            else:
                coins_sold[coin] = coins_bought[coin]

                # prevent system from buying this coin for the next TIME_DIFFERENCE minutes
                volatility_cooloff[coin] = datetime.now()

                profit = ((LastPrice - BuyPrice) * coins_sold[coin]["volume"]) * (1 - (BuyFee + SellFee))

                # Log trade
                if LOG_TRADES:
                    # Original
                    # profit = ((LastPrice - BuyPrice) * coins_sold[coin]["volume"]) * (1 - (TRADING_FEE * 2))  # adjust for trading fee here
                    # write_log(f"Sell: {coins_sold[coin]['volume']} {coin} - {BuyPrice} - {LastPrice} Profit: {profit:.{decimals(PAIR_WITH)}f} {PAIR_WITH} ({PriceChange-(TRADING_FEE*2):.2f}%)")
                    # session_profit = session_profit + (PriceChange - (TRADING_FEE * 2))

                    # BY FreshLondon
                    # adding maths as this is really hurting my brain
                    # example here for buying 1x coin at 5 and selling at 10
                    # if buy is 5, fee is 0.00375
                    # if sell is 10, fee is 0.0075
                    # for the above, BuyFee + SellFee = 0.07875
                    # profit = ((LastPrice - BuyPrice) * coins_sold[coin]["volume"]) * (1 - (BuyFee + SellFee))
                    # LastPrice (10) - BuyPrice (5) = 5
                    # 5 * coins_sold (1) = 5
                    # 5 * (1-(0.07875)) = 4.60625
                    # profit = 4.60625, it seems ok!
                    write_log(
                        f"Sell: {coins_sold[coin]['volume']} {coin} - {BuyPrice} - {LastPrice} Profit: {profit:.{decimals(PAIR_WITH)}f} {PAIR_WITH} ({PriceChange-(BuyFee+SellFee):.2f}%)"
                    )
                    session_profit = session_profit + (PriceChange - (BuyFee + SellFee))

                    # print balance report
                    balance_report()

                # Send event to database
                if "-" in str(profit):
                    made_profit = False
                else:
                    made_profit = True
                value = {
                    "volume": coins_sold[coin]["volume"],
                    "timestamp": time.time(),
                    "action": "sell",
                    "madeProfit": made_profit,
                    "coin": coin,
                    "profit": profit,
                    "buyPrice": BuyPrice,
                    "sellPrice": LastPrice,
                }
                if MONGO:
                    insert_trades(value, DATABASE_NAME)
            continue

        # no action; print once every TIME_DIFFERENCE
        if hsp_head == 1:
            if len(coins_bought) > 0:
                print(
                    f"TP or SL not yet reached, not selling {coin} for now {BuyPrice} - {LastPrice} : {txcolors.SELL_PROFIT if PriceChange >= 0. else txcolors.SELL_LOSS}{PriceChange-(BuyFee+SellFee):.2f}% Est: {(QUANTITY*(PriceChange-(BuyFee+SellFee)))/100:.{decimals(PAIR_WITH)}f} {PAIR_WITH}{txcolors.DEFAULT}"
                )

    if hsp_head == 1 and len(coins_bought) == 0:
        print(f"No trade slots are currently in use")

    return coins_sold


def update_portfolio(orders, last_price, volume):
    """add every coin bought to our portfolio for tracking/selling later"""
    if DEBUG and len(orders) > 0:
        print(orders)

    for coin in orders:
        if TEST_MODE:
            order_id = fake_orderid()
            if DEBUG:
                print(f"Running in test updating portfolio with fake orderid:{order_id}")
        else:
            order_id = orders[coin][0]["orderId"]
        value = {
            "symbol": orders[coin][0]["symbol"],
            "orderid": order_id,
            "timestamp": orders[coin][0]["time"],
            "bought_at": last_price[coin]["price"],
            "volume": volume[coin],
            "stop_loss": -STOP_LOSS,
            "take_profit": TAKE_PROFIT,
        }
        coins_bought[coin] = value

        # save the coins in a json file in the same directory
        with open(coins_bought_file_path, "w") as file:
            json.dump(coins_bought, file, indent=4)

        print(f'Order with id {orders[coin][0]["orderId"]} placed and saved to file')

    # For some reason we cant add the
    # if MONGO: stuff in the above loop.
    # it causes the json file to be malformed...
    # So this is the next best option...
    for coin in orders:
        if TEST_MODE:
            order_id = fake_orderid()
            if DEBUG:
                print(f"Running in test updating portfolio with fake orderid:{order_id}")
        else:
            order_id = orders[coin][0]["orderId"]

        value = {
            "symbol": orders[coin][0]["symbol"],
            "orderid": order_id,
            "timestamp": orders[coin][0]["time"],
            "buyPrice": float(last_price[coin]["price"]),
            "volume": volume[coin],
            "stopLoss": -STOP_LOSS,
            "takeProfit": TAKE_PROFIT,
        }
        if MONGO:
            insert_portfolio(value, DATABASE_NAME)
        # print balance report
        balance_report()


def remove_from_portfolio(coins_sold):
    """Remove coins sold due to SL or TP from portfolio"""
    for coin in coins_sold:
        coins_bought.pop(coin)
        if MONGO:
            # value = {'orderid': coins_sold[coin]['orderid']}
            value = {"symbol": coins_sold[coin]["symbol"]}
            delete_item = delete_portolio_item(value, DATABASE_NAME)

    with open(coins_bought_file_path, "w") as file:
        json.dump(coins_bought, file, indent=4)


def write_log(logline):
    timestamp = datetime.now().strftime("%d/%m %H:%M:%S")
    with open(LOG_FILE, "a+") as f:
        f.write(timestamp + " " + logline + "\n")


if __name__ == "__main__":

    # set to false at Start
    global bot_paused
    bot_paused = False

    data, key = config()

    # Load system vars
    TEST_MODE = data["TEST_MODE"]
    LOG_TRADES = data["LOG_TRADES"]
    LOG_FILE = data["LOG_FILE"]
    DEBUG = data["DEBUG"]
    AMERICAN_USER = data["AMERICAN_USER"]
    TESTNET = data["TESTNET"]
    MONGO = data["MONGO"]
    DATABASE_NAME = data["DATABASE_NAME"]
    PAIR_WITH = data["PAIR_WITH"]
    QUANTITY = data["QUANTITY"]
    # MAX_ORDERS = data["MAX_ORDERS"]
    TRADE_SLOTS = data["TRADE_SLOTS"]
    FIATS = data["FIATS"]
    TIME_DIFFERENCE = data["TIME_DIFFERENCE"]
    RECHECK_INTERVAL = data["RECHECK_INTERVAL"]
    CHANGE_IN_PRICE = data["CHANGE_IN_PRICE"]
    STOP_LOSS = data["STOP_LOSS"]
    TAKE_PROFIT = data["TAKE_PROFIT"]
    CUSTOM_LIST = data["CUSTOM_LIST"]
    TICKERS_LIST = data["TICKERS_LIST"]
    USE_TRAILING_STOP_LOSS = data["USE_TRAILING_STOP_LOSS"]
    TRAILING_STOP_LOSS = data["TRAILING_STOP_LOSS"]
    TRAILING_TAKE_PROFIT = data["TRAILING_TAKE_PROFIT"]
    TRADING_FEE = data["TRADING_FEE"]
    SIGNALLING_MODULES = data["SIGNALLING_MODULES"]

    # perform certain checks
    if data["DEBUG"]:
        print(f"loaded config below\n{json.dumps(data['parsed_config'], indent=4)}")
        print(f"Your credentials have been loaded from {data['creds_file']}")

    # Initialise max_orders
    # max_orders = MAX_ORDERS

    client = auth(data, key)

    # Use CUSTOM_LIST symbols if CUSTOM_LIST is set to True
    if CUSTOM_LIST:
        tickers = [line.strip() for line in open(TICKERS_LIST)]
    else:
        tickers = get_new_tickers(client, PAIR_WITH, FIATS)
        tickers = [line.strip() for line in open(TICKERS_LIST)]

    # try to load all the coins bought by the bot if the file exists and is not empty
    coins_bought = {}

    # path to the saved coins_bought file
    coins_bought_file_path = "coins_bought.json"

    # rolling window of prices; cyclical queue
    historical_prices = [None] * (TIME_DIFFERENCE * RECHECK_INTERVAL)
    hsp_head = -1

    # prevent including a coin in volatile_coins if it has already appeared there less than TIME_DIFFERENCE minutes ago
    volatility_cooloff = {}

    # use separate files for testing and live trading
    if TEST_MODE:
        print("Currently In TESTMODE")
        coins_bought_file_path = "test_" + coins_bought_file_path

    # if saved coins_bought json file exists and it's not empty then load it
    if os.path.isfile(coins_bought_file_path) and os.stat(coins_bought_file_path).st_size != 0:
        with open(coins_bought_file_path) as file:
            coins_bought = json.load(file)

    if not TEST_MODE:
        if not data["NOTIMEOUT"]:  # if notimeout skip this (fast for dev tests)
            print("WARNING: test mode is disabled in the configuration, you are using live funds. Waiting 30 seconds before action as a security measure")
            time.sleep(30)

    signals = glob.glob("signals/*.exs")
    for filename in signals:
        for line in open(filename):
            try:
                os.remove(filename)
            except:
                if DEBUG:
                    print(f"{txcolors.WARNING}Could not remove external signalling file {filename}{txcolors.DEFAULT}")

    if os.path.isfile("signals/paused.exc"):
        try:
            os.remove("signals/paused.exc")
        except:
            if DEBUG:
                print(f"{txcolors.WARNING}Could not remove external signalling file {filename}{txcolors.DEFAULT}")

    # load signalling modules
    mymodule = {}
    try:
        if len(SIGNALLING_MODULES) > 0:
            for module in SIGNALLING_MODULES:
                print(f"Starting {module}")
                module = "modules." + module
                mymodule[module] = importlib.import_module(module)
                t = threading.Thread(target=mymodule[module].process, args=())
                t.daemon = True
                t.start()
                time.sleep(2)
        else:
            print(f"No modules to load {SIGNALLING_MODULES}")
    except Exception as e:
        print(f"Error in main for {SIGNALLING_MODULES}: {e}")

    # seed initial prices
    get_price()
    while True:
        # print balance report
        balance_report()
        orders, last_price, volume = buy_coins()
        update_portfolio(orders, last_price, volume)
        coins_sold = sell_coins()
        remove_from_portfolio(coins_sold)
