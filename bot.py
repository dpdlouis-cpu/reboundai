import telebot
import requests
import time
import threading
import json
import os
import feedparser

TOKEN ="8958506449:AAHYfuSnQgEP8Ix-oZRowu5yDfKWsO37cHg"
CHAT_ID = "8913110566"

bot = telebot.TeleBot(TOKEN)

WATCHLIST = {
    "btc": "BTCUSDT",
    "gold": "PAXGUSDT"
}

ALIASES = {
    "btc": "btc",
    "bitcoin": "btc",
    "gold": "gold",
    "golden": "gold",
    "or": "gold",
    "xau": "gold"
}

COINDESK_RSS = "https://www.coindesk.com/arc/outboundfeeds/rss/"
PAPER_FILE = "paper_v14.json"
HISTORY_FILE = "history_v14.json"

last_signal = {}
last_news_titles = set()


def load_json(file, default):
    if os.path.exists(file):
        try:
            with open(file, "r") as f:
                return json.load(f)
        except:
            return default
    return default


def save_json(file, data):
    with open(file, "w") as f:
        json.dump(data, f, indent=2)


def save_history(event):
    data = load_json(HISTORY_FILE, [])
    data.append(event)
    save_json(HISTORY_FILE, data[-1500:])


def load_paper():
    return load_json(PAPER_FILE, {
        "cash": 1000.0,
        "positions": {},
        "trades": [],
        "peak_equity": 1000.0,
        "max_drawdown": 0.0
    })


def save_paper(data):
    save_json(PAPER_FILE, data)


def api_get(url):
    return requests.get(url, timeout=10).json()


def get_price(symbol):
    return float(api_get(f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}")["price"])


def get_24h(symbol):
    return api_get(f"https://api.binance.com/api/v3/ticker/24hr?symbol={symbol}")


def get_klines(symbol, interval="5m", limit=300):
    data = api_get(
        f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}"
    )
    closes = [float(c[4]) for c in data]
    highs = [float(c[2]) for c in data]
    lows = [float(c[3]) for c in data]
    volumes = [float(c[5]) for c in data]
    return closes, highs, lows, volumes


def ema_series(prices, period):
    k = 2 / (period + 1)
    vals = [prices[0]]
    for p in prices[1:]:
        vals.append(p * k + vals[-1] * (1 - k))
    return vals


def ema(prices, period):
    return ema_series(prices, period)[-1]


def rsi(prices, period=14):
    gains = []
    losses = []

    for i in range(1, period + 1):
        diff = prices[-i] - prices[-i - 1]
        gains.append(max(diff, 0))
        losses.append(abs(min(diff, 0)))

    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period

    if avg_loss == 0:
        return 100

    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def macd(prices):
    e12 = ema_series(prices, 12)
    e26 = ema_series(prices, 26)

    n = min(len(e12), len(e26))
    e12 = e12[-n:]
    e26 = e26[-n:]

    macd_vals = []

    for i in range(n):
        macd_vals.append(e12[i] - e26[i])

    signal_vals = ema_series(macd_vals, 9)

    line = macd_vals[-1]
    signal = signal_vals[-1]
    hist = line - signal

    return line, signal, hist


def atr(highs, lows, closes, period=14):
    trs = []

    for i in range(1, period + 1):
        tr = max(
            highs[-i] - lows[-i],
            abs(highs[-i] - closes[-i - 1]),
            abs(lows[-i] - closes[-i - 1])
        )
        trs.append(tr)

    return sum(trs) / period


def analyse_news_sentiment(text):
    t = text.lower()

    bad = [
        "hack", "exploit", "lawsuit", "sec", "ban", "collapse",
        "fraud", "warning", "bearish", "selloff", "crackdown",
        "cpi", "fed", "rate hike", "liquidation"
    ]

    good = [
        "etf", "approval", "approved", "bullish", "adoption",
        "surge", "rally", "growth", "blackrock", "institutional",
        "accumulation"
    ]

    score = 0

    for w in good:
        if w in t:
            score += 1

    for w in bad:
        if w in t:
            score -= 1

    if score > 0:
        return "positive", score
    elif score < 0:
        return "dangereuse", score
    else:
        return "neutre", score


def get_latest_news(limit=5):
    feed = feedparser.parse(COINDESK_RSS)
    news = []

    for entry in feed.entries[:limit]:
        title = entry.get("title", "Sans titre")
        link = entry.get("link", "")
        sentiment, score = analyse_news_sentiment(title)

        news.append({
            "title": title,
            "link": link,
            "sentiment": sentiment,
            "score": score
        })

    return news


def news_score_for_asset(asset):
    news = get_latest_news(8)
    total = 0

    if asset == "btc":
        keywords = ["bitcoin", "btc"]
    else:
        keywords = ["gold", "xau", "paxg", "pax gold"]

    for item in news:
        title = item["title"].lower()

        if any(k in title for k in keywords):
            total += item["score"]

    return total


def analyse_timeframe(symbol, interval):
    closes, highs, lows, volumes = get_klines(symbol, interval, 300)

    price = closes[-1]
    ema20 = ema(closes, 20)
    ema50 = ema(closes, 50)
    ema200 = ema(closes, 200)

    rsi_val = rsi(closes)
    macd_line, macd_signal, macd_hist = macd(closes)
    atr_val = atr(highs, lows, closes)

    vol_now = volumes[-1]
    avg_vol = sum(volumes[-20:]) / 20

    support = min(closes[-40:])
    resistance = max(closes[-40:])

    dist_support = abs(price - support) / price * 100
    dist_resistance = abs(price - resistance) / price * 100

    score = 0

    if ema20 > ema50 > ema200:
        trend = "haussiere forte"
        score += 3
    elif ema20 > ema50:
        trend = "haussiere"
        score += 2
    elif ema20 < ema50 < ema200:
        trend = "baissiere forte"
        score -= 3
    else:
        trend = "baissiere"
        score -= 2

    if 48 <= rsi_val <= 64:
        rsi_state = "propre"
        score += 1
    elif rsi_val > 70:
        rsi_state = "surachete"
        score -= 2
    elif rsi_val < 30:
        rsi_state = "survendu"
        score += 1
    else:
        rsi_state = "moyen"

    if macd_line > macd_signal and macd_hist > 0:
        macd_state = "positif"
        score += 1
    else:
        macd_state = "negatif"
        score -= 1

    if vol_now > avg_vol * 1.4:
        volume_state = "fort"
        score += 1
    elif vol_now < avg_vol * 0.6:
        volume_state = "faible"
        score -= 1
    else:
        volume_state = "normal"

    if dist_support < 0.35:
        zone = "proche support"
        score += 1
    elif dist_resistance < 0.25:
        zone = "proche resistance"
        score -= 1
    else:
        zone = "milieu"

    if price > resistance and vol_now > avg_vol * 1.5:
        breakout = "breakout haussier"
        score += 2
    elif price < support and vol_now > avg_vol * 1.5:
        breakout = "breakout baissier"
        score -= 2
    else:
        breakout = "aucun"

    atr_percent = atr_val / price * 100

    if atr_percent > 1.3:
        volatility = "forte"
        score -= 1
    elif atr_percent < 0.35:
        volatility = "squeeze"
        score += 1
    else:
        volatility = "normale"

    return {
        "price": price,
        "score": score,
        "trend": trend,
        "rsi": rsi_val,
        "rsi_state": rsi_state,
        "macd": macd_state,
        "volume": volume_state,
        "support": support,
        "resistance": resistance,
        "zone": zone,
        "breakout": breakout,
        "atr": atr_val,
        "atr_percent": atr_percent,
        "volatility": volatility
    }


def analyse_asset(asset, symbol):
    tf5 = analyse_timeframe(symbol, "5m")
    tf15 = analyse_timeframe(symbol, "15m")
    tf1h = analyse_timeframe(symbol, "1h")
    tf4h = analyse_timeframe(symbol, "4h")

    price = tf5["price"]
    data24 = get_24h(symbol)
    variation24 = float(data24["priceChangePercent"])

    news_score = news_score_for_asset(asset)

    total_score = tf5["score"] + tf15["score"] + tf1h["score"] + tf4h["score"]

    if news_score > 0:
        news_status = "positive"
        total_score += 1
    elif news_score < 0:
        news_status = "dangereuse"
        total_score -= 4
    else:
        news_status = "neutre"

    bullish = (
        "haussiere" in tf5["trend"]
        and "haussiere" in tf15["trend"]
        and "haussiere" in tf1h["trend"]
    )

    bearish = (
        "baissiere" in tf5["trend"]
        and "baissiere" in tf15["trend"]
        and "baissiere" in tf1h["trend"]
    )

    entry = price
    stop_distance = tf5["atr"] * 1.5
    stop_loss = entry - stop_distance
    take_profit_1 = entry + stop_distance * 2
    take_profit_2 = entry + stop_distance * 3
    trailing_stop = entry - tf5["atr"]

    risk_reward = (take_profit_1 - entry) / (entry - stop_loss) if entry > stop_loss else 0

    elite_buy = (
        bullish
        and tf5["macd"] == "positif"
        and tf15["macd"] == "positif"
        and 50 <= tf5["rsi"] <= 64
        and tf5["volume"] in ["normal", "fort"]
        and tf5["volatility"] != "forte"
        and news_score >= 0
        and risk_reward >= 1.8
        and (
            tf5["zone"] == "proche support"
            or tf5["breakout"] == "breakout haussier"
        )
    )

    elite_sell = (
        bearish
        or tf5["rsi"] > 70
        or tf5["zone"] == "proche resistance"
        or tf5["breakout"] == "breakout baissier"
        or news_score < 0
    )

    if elite_buy:
        signal = "🟢 SIGNAL ELITE - MOMENT D'ACHETER"
    elif elite_sell:
        signal = "🔴 SIGNAL ELITE - MOMENT DE REVENDRE"
    else:
        signal = "⚠️ ATTENDRE"

    if total_score >= 10:
        decision = "ACHAT POSSIBLE"
    elif total_score <= -8:
        decision = "VENTE / PRUDENCE"
    else:
        decision = "NO TRADE"

    save_history({
        "asset": asset,
        "price": price,
        "score": total_score,
        "signal": signal,
        "time": time.time()
    })

    msg = f"""
Analyse ELITE {asset.upper()}

Prix : {price:.4f} $
Variation 24h : {variation24:.2f}%

--- 5m ---
Tendance : {tf5["trend"]}
RSI : {tf5["rsi"]:.2f} - {tf5["rsi_state"]}
MACD : {tf5["macd"]}
Volume : {tf5["volume"]}
Zone : {tf5["zone"]}
Breakout : {tf5["breakout"]}
Volatilite : {tf5["volatility"]}

--- 15m ---
Tendance : {tf15["trend"]}
RSI : {tf15["rsi"]:.2f}
MACD : {tf15["macd"]}

--- 1h ---
Tendance : {tf1h["trend"]}
RSI : {tf1h["rsi"]:.2f}
MACD : {tf1h["macd"]}

--- 4h ---
Tendance : {tf4h["trend"]}
RSI : {tf4h["rsi"]:.2f}

News : {news_status} / score {news_score}

Score total : {total_score}/40
Decision : {decision}

Entree theorique : {entry:.4f} $
Stop loss : {stop_loss:.4f} $
Take profit 1 : {take_profit_1:.4f} $
Take profit 2 : {take_profit_2:.4f} $
Trailing stop : {trailing_stop:.4f} $
Risk/Reward : {risk_reward:.2f}

{signal}

Attention : ce n'est pas un conseil financier.
"""

    return msg, signal, price, stop_loss, take_profit_1, take_profit_2, trailing_stop


def load_paper():
    return load_json(PAPER_FILE, {
        "cash": 1000.0,
        "positions": {},
        "trades": [],
        "peak_equity": 1000.0,
        "max_drawdown": 0.0
    })


def save_paper(data):
    save_json(PAPER_FILE, data)


def paper_buy(asset, price, sl, tp1, tp2, trailing):
    p = load_paper()

    if asset in p["positions"]:
        return "Position deja ouverte."

    risk_percent = 0.01
    capital = p["cash"]
    risk_amount = capital * risk_percent
    stop_distance = price - sl

    if stop_distance <= 0:
        return "Stop invalide."

    qty = risk_amount / stop_distance
    cost = qty * price

    if cost > capital:
        cost = capital * 0.20
        qty = cost / price

    p["cash"] -= cost

    p["positions"][asset] = {
        "entry": price,
        "quantity": qty,
        "cost": cost,
        "sl": sl,
        "tp1": tp1,
        "tp2": tp2,
        "trailing": trailing,
        "highest": price,
        "time": time.time()
    }

    p["trades"].append({
        "type": "BUY",
        "asset": asset,
        "price": price,
        "cost": cost,
        "qty": qty,
        "time": time.time()
    })

    save_paper(p)

    return f"Paper BUY {asset.upper()} | entree {price:.4f} | SL {sl:.4f} | TP1 {tp1:.4f}"


def paper_sell(asset, price, reason="signal"):
    p = load_paper()

    if asset not in p["positions"]:
        return "Aucune position ouverte."

    pos = p["positions"][asset]

    value = pos["quantity"] * price
    pnl = value - pos["cost"]
    pnl_pct = pnl / pos["cost"] * 100

    p["cash"] += value
    del p["positions"][asset]

    p["trades"].append({
        "type": "SELL",
        "asset": asset,
        "price": price,
        "pnl": pnl,
        "pnl_percent": pnl_pct,
        "reason": reason,
        "time": time.time()
    })

    save_paper(p)

    return f"Paper SELL {asset.upper()} | sortie {price:.4f} | PnL {pnl:.2f}$ ({pnl_pct:.2f}%) | raison {reason}"


def manage_open_positions():
    p = load_paper()
    changed = False
    messages = []

    for asset, pos in list(p["positions"].items()):
        price = get_price(WATCHLIST[asset])

        if price > pos["highest"]:
            pos["highest"] = price
            pos["trailing"] = max(pos["trailing"], price * 0.992)
            changed = True

        if price <= pos["sl"]:
            messages.append(paper_sell(asset, price, "STOP LOSS"))

        elif price >= pos["tp2"]:
            messages.append(paper_sell(asset, price, "TAKE PROFIT 2"))

        elif price <= pos["trailing"] and price > pos["entry"]:
            messages.append(paper_sell(asset, price, "TRAILING STOP"))

    if changed:
        save_paper(p)

    return messages


def paper_report():
    p = load_paper()
    equity = p["cash"]

    txt = f"Portefeuille fictif V14\n\nCash : {p['cash']:.2f}$\n\nPositions :\n"

    if not p["positions"]:
        txt += "Aucune position.\n"
    else:
        for asset, pos in p["positions"].items():
            price = get_price(WATCHLIST[asset])
            value = pos["quantity"] * price
            equity += value
            pnl = value - pos["cost"]
            pnl_pct = pnl / pos["cost"] * 100

            txt += f"""
{asset.upper()}
Entree : {pos['entry']:.4f}
Prix actuel : {price:.4f}
SL : {pos['sl']:.4f}
TP1 : {pos['tp1']:.4f}
TP2 : {pos['tp2']:.4f}
Trailing : {pos['trailing']:.4f}
PnL latent : {pnl:.2f}$ ({pnl_pct:.2f}%)
"""

    if equity > p.get("peak_equity", 1000):
        p["peak_equity"] = equity

    dd = (p["peak_equity"] - equity) / p["peak_equity"] * 100
    p["max_drawdown"] = max(p.get("max_drawdown", 0), dd)

    save_paper(p)

    sells = [t for t in p["trades"] if t["type"] == "SELL"]
    wins = [t for t in sells if t["pnl"] > 0]
    losses = [t for t in sells if t["pnl"] <= 0]

    winrate = len(wins) / len(sells) * 100 if sells else 0
    gross_profit = sum(t["pnl"] for t in wins)
    gross_loss = abs(sum(t["pnl"] for t in losses))
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else gross_profit

    txt += f"""

Equity : {equity:.2f}$
Trades fermes : {len(sells)}
Winrate : {winrate:.2f}%
Profit factor : {profit_factor:.2f}
Max drawdown : {p['max_drawdown']:.2f}%
"""

    return txt


def trades_report():
    p = load_paper()
    trades = p["trades"][-10:]

    if not trades:
        return "Aucun trade."

    txt = "Derniers trades\n\n"

    for t in trades:
        txt += f"{t}\n\n"

    return txt


def backtest_asset(asset, symbol, rsi_min=50, rsi_max=64):
    closes, highs, lows, volumes = get_klines(symbol, "15m", 300)

    cash = 1000
    position = None
    trades = []

    for i in range(210, len(closes) - 1):
        sub = closes[:i]
        sub_high = highs[:i]
        sub_low = lows[:i]

        price = closes[i]

        ema20 = ema(sub, 20)
        ema50 = ema(sub, 50)
        ema200 = ema(sub, 200)
        rsi_val = rsi(sub)
        macd_line, macd_signal, hist = macd(sub)
        atr_val = atr(sub_high, sub_low, sub)

        buy = (
            ema20 > ema50 > ema200
            and macd_line > macd_signal
            and hist > 0
            and rsi_min <= rsi_val <= rsi_max
            and position is None
        )

        sell = (
            position is not None
            and (
                rsi_val > 70
                or ema20 < ema50
                or price <= position["sl"]
                or price >= position["tp"]
            )
        )

        if buy:
            sl = price - atr_val * 1.5
            tp = price + atr_val * 3
            qty = (cash * 0.20) / price
            cost = qty * price
            cash -= cost

            position = {
                "entry": price,
                "qty": qty,
                "cost": cost,
                "sl": sl,
                "tp": tp
            }

        elif sell:
            value = position["qty"] * price
            pnl = value - position["cost"]
            cash += value
            trades.append(pnl)
            position = None

    total = len(trades)
    wins = len([x for x in trades if x > 0])
    losses = len([x for x in trades if x <= 0])
    winrate = wins / total * 100 if total else 0
    pnl_total = sum(trades)

    gross_profit = sum([x for x in trades if x > 0])
    gross_loss = abs(sum([x for x in trades if x <= 0]))
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else gross_profit

    return {
        "asset": asset,
        "trades": total,
        "wins": wins,
        "losses": losses,
        "winrate": winrate,
        "pnl": pnl_total,
        "profit_factor": profit_factor,
        "cash_final": cash,
        "rsi_min": rsi_min,
        "rsi_max": rsi_max
    }


def optimize_asset(asset, symbol):
    best = None

    tests = [
        (45, 60),
        (48, 64),
        (50, 64),
        (52, 66),
        (55, 68)
    ]

    for rmin, rmax in tests:
        result = backtest_asset(asset, symbol, rmin, rmax)

        if best is None:
            best = result
        elif result["profit_factor"] > best["profit_factor"]:
            best = result

    return best


def surveillance_auto():
    for asset in WATCHLIST:
        last_signal[asset] = ""

    bot.send_message(CHAT_ID, "ReboundAI V14 ELITE actif ⚔️")

    while True:
        try:
            for msg in manage_open_positions():
                bot.send_message(CHAT_ID, "GESTION POSITION\n" + msg)

            for asset, symbol in WATCHLIST.items():
                analyse, signal, price, sl, tp1, tp2, trailing = analyse_asset(asset, symbol)

                if signal != last_signal[asset]:
                    bot.send_message(CHAT_ID, f"SIGNAL ELITE {asset.upper()}\n\n{analyse}")

                    if signal == "🟢 SIGNAL ELITE - MOMENT D'ACHETER":
                        bot.send_message(CHAT_ID, "PAPER TRADING\n" + paper_buy(asset, price, sl, tp1, tp2, trailing))

                    elif signal == "🔴 SIGNAL ELITE - MOMENT DE REVENDRE":
                        bot.send_message(CHAT_ID, "PAPER TRADING\n" + paper_sell(asset, price, "SIGNAL REVENDRE"))

                    last_signal[asset] = signal

            time.sleep(60)

        except Exception as e:
            print("Erreur surveillance :", e)
            time.sleep(15)


def surveillance_news():
    global last_news_titles

    while True:
        try:
            for item in get_latest_news(5):
                title = item["title"]

                if title not in last_news_titles:
                    last_news_titles.add(title)

                    if item["sentiment"] != "neutre":
                        bot.send_message(CHAT_ID, f"""
NEWS {item["sentiment"].upper()}

{title}

Score : {item["score"]}
Lien : {item["link"]}
""")

            time.sleep(300)

        except Exception as e:
            print("Erreur news :", e)
            time.sleep(60)


@bot.message_handler(commands=["start"])
def start(message):
    bot.reply_to(message, """
ReboundAI V14 ELITE actif

Commandes :
btc
gold
golden
or
xau
/market
/news
/portfolio
/trades
/resetpaper
/backtest btc
/backtest gold
/optimize btc
/optimize gold
/help
""")


@bot.message_handler(commands=["market"])
def market(message):
    txt = "Marche BTC + GOLD\n\n"

    for asset, symbol in WATCHLIST.items():
        txt += f"{asset.upper()} : {get_price(symbol):.4f}$\n"

    bot.reply_to(message, txt)


@bot.message_handler(commands=["portfolio"])
def portfolio(message):
    bot.reply_to(message, paper_report())


@bot.message_handler(commands=["trades"])
def trades(message):
    bot.reply_to(message, trades_report())


@bot.message_handler(commands=["resetpaper"])
def resetpaper(message):
    save_paper({
        "cash": 1000.0,
        "positions": {},
        "trades": [],
        "peak_equity": 1000.0,
        "max_drawdown": 0.0
    })

    bot.reply_to(message, "Paper trading remis a zero : 1000$")


@bot.message_handler(commands=["news"])
def news(message):
    try:
        txt = "Dernieres news\n\n"

        for n in get_latest_news(5):
            txt += f"{n['title']}\nSentiment : {n['sentiment']} | Score {n['score']}\n{n['link']}\n\n"

        bot.reply_to(message, txt)

    except:
        bot.reply_to(message, "Erreur news.")


@bot.message_handler(commands=["backtest"])
def backtest_cmd(message):
    try:
        parts = message.text.lower().split()

        if len(parts) < 2:
            bot.reply_to(message, "Utilise : /backtest btc ou /backtest gold")
            return

        asset = ALIASES.get(parts[1])

        if asset not in WATCHLIST:
            bot.reply_to(message, "Actif inconnu.")
            return

        result = backtest_asset(asset, WATCHLIST[asset])

        bot.reply_to(message, f"""
BACKTEST {asset.upper()}

Trades : {result['trades']}
Gagnants : {result['wins']}
Perdants : {result['losses']}
Winrate : {result['winrate']:.2f}%
PnL total : {result['pnl']:.2f}$
Profit factor : {result['profit_factor']:.2f}
Cash final : {result['cash_final']:.2f}$
RSI : {result['rsi_min']} - {result['rsi_max']}

Attention : backtest simple, pas une garantie.
""")

    except Exception as e:
        print("Erreur backtest :", e)
        bot.reply_to(message, "Erreur backtest.")


@bot.message_handler(commands=["optimize"])
def optimize_cmd(message):
    try:
        parts = message.text.lower().split()

        if len(parts) < 2:
            bot.reply_to(message, "Utilise : /optimize btc ou /optimize gold")
            return

        asset = ALIASES.get(parts[1])

        if asset not in WATCHLIST:
            bot.reply_to(message, "Actif inconnu.")
            return

        best = optimize_asset(asset, WATCHLIST[asset])

        bot.reply_to(message, f"""
OPTIMISATION {asset.upper()}

Meilleur RSI trouve :
{best['rsi_min']} - {best['rsi_max']}

Trades : {best['trades']}
Winrate : {best['winrate']:.2f}%
PnL : {best['pnl']:.2f}$
Profit factor : {best['profit_factor']:.2f}
Cash final : {best['cash_final']:.2f}$

Attention : risque d'overfitting. A confirmer en paper trading.
""")

    except Exception as e:
        print("Erreur optimize :", e)
        bot.reply_to(message, "Erreur optimisation.")


@bot.message_handler(commands=["help"])
def help_cmd(message):
    bot.reply_to(message, """
Commandes :
btc
gold / golden / or / xau

/market
/news
/portfolio
/trades
/resetpaper
/backtest btc
/backtest gold
/optimize btc
/optimize gold

V14 ELITE :
- BTC + GOLD uniquement
- multi-timeframe 5m/15m/1h/4h
- EMA20/50/200
- RSI
- MACD histogramme
- ATR
- stop loss intelligent
- take profit
- trailing stop
- paper trading
- backtest
- optimisation simple
""")


@bot.message_handler(func=lambda message: True)
def reply(message):
    try:
        text = message.text.lower().strip()

        if text in ALIASES:
            asset = ALIASES[text]
            analyse, signal, price, sl, tp1, tp2, trailing = analyse_asset(asset, WATCHLIST[asset])
            bot.reply_to(message, analyse)
        else:
            bot.reply_to(message, "Commande inconnue. Fais /help")

    except Exception as e:
        print("Erreur reply :", e)
        bot.reply_to(message, "Erreur analyse.")


threading.Thread(target=surveillance_auto, daemon=True).start()
threading.Thread(target=surveillance_news, daemon=True).start()

print("ReboundAI V14 ELITE lance ⚔️")

while True:
    try:
        bot.infinity_polling(timeout=10, long_polling_timeout=5)
    except Exception as e:
        print("Crash :", e)
        time.sleep(5)
