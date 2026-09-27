import os
import logging
import time
from datetime import datetime
import yfinance as yf
import pandas as pd
from ta.momentum import RSIIndicator
from ta.trend import MACD, SMAIndicator
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
DEFAULT_INTERVAL = "1d"

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

def fetch_data(ticker: str, interval: str = "1d", period: str = "1y"):
    """More reliable way to fetch data"""
    for attempt in range(3):
        try:
            t = yf.Ticker(ticker)
            data = t.history(period=period, interval=interval, auto_adjust=True)
            if not data.empty and len(data) >= 20:
                return data
        except Exception as e:
            logger.warning(f"Attempt {attempt+1} failed for {ticker}: {e}")
            time.sleep(1)
    return None

def get_signal(symbol: str, interval: str = DEFAULT_INTERVAL) -> str:
    try:
        symbol = symbol.upper().strip()

        # Decide which ticker to use
        if symbol in ["XAUUSD", "XAU", "GOLD"]:
            tickers_to_try = ["GC=F", "GOLD", "GLD"]
            display_name = "XAUUSD"
        elif len(symbol) == 6 and symbol.isalpha():
            tickers_to_try = [f"{symbol}=X"]
            display_name = symbol
        else:
            tickers_to_try = [symbol]
            display_name = symbol

        data = None
        used_ticker = None

        for ticker in tickers_to_try:
            data = fetch_data(ticker, interval=interval)
            if data is not None:
                used_ticker = ticker
                break

        if data is None:
            return f"❌ Could not get data for `{display_name}`. Try again in a few minutes."

        close = data["Close"].dropna()
        if len(close) < 20:
            return f"❌ Not enough data for `{display_name}`."

        # Indicators
        rsi = RSIIndicator(close, window=14).rsi()
        macd = MACD(close)
        hist = macd.macd_diff()
        sma20 = SMAIndicator(close, window=20).sma_indicator()
        sma50 = SMAIndicator(close, window=50).sma_indicator()

        last_close = float(close.iloc[-1])
        last_rsi = float(rsi.iloc[-1])
        last_hist = float(hist.iloc[-1])
        prev_hist = float(hist.iloc[-2])
        last_sma20 = float(sma20.iloc[-1])
        last_sma50 = float(sma50.iloc[-1])

        score = 0
        reasons = []

        # RSI
        if last_rsi < 30:
            score += 2
            reasons.append(f"RSI oversold ({last_rsi:.1f})")
        elif last_rsi > 70:
            score -= 2
            reasons.append(f"RSI overbought ({last_rsi:.1f})")
        elif last_rsi < 45:
            score += 1
            reasons.append(f"RSI leaning bullish ({last_rsi:.1f})")
        elif last_rsi > 55:
            score -= 1
            reasons.append(f"RSI leaning bearish ({last_rsi:.1f})")

        # MACD
        if last_hist > 0 and prev_hist <= 0:
            score += 2
            reasons.append("MACD bullish crossover")
        elif last_hist < 0 and prev_hist >= 0:
            score -= 2
            reasons.append("MACD bearish crossover")
        elif last_hist > 0:
            score += 1
            reasons.append("MACD histogram positive")
        else:
            score -= 1
            reasons.append("MACD histogram negative")

        # Trend
        if last_close > last_sma20 > last_sma50:
            score += 1
            reasons.append("Price above SMA20 & SMA50 (uptrend)")
        elif last_close < last_sma20 < last_sma50:
            score -= 1
            reasons.append("Price below SMA20 & SMA50 (downtrend)")

        # Final decision
        if score >= 3:
            signal = "🟢 **STRONG BUY**"
        elif score >= 1:
            signal = "🟢 **BUY**"
        elif score <= -3:
            signal = "🔴 **STRONG SELL**"
        elif score <= -1:
            signal = "🔴 **SELL**"
        else:
            signal = "⚪ **HOLD / NEUTRAL**"

        # Price format
        if display_name == "XAUUSD":
            price_str = f"${last_close:,.2f}"
        else:
            price_str = f"{last_close:.5f}" if last_close < 50 else f"{last_close:,.2f}"

        msg = (
            f"📊 **Signal for `{display_name}`**\n"
            f"Timeframe: `{interval}`\n"
            f"Price: `{price_str}`\n\n"
            f"{signal}\n"
            f"Score: `{score}`\n\n"
            f"**Key levels**\n"
            f"• RSI(14): `{last_rsi:.1f}`\n"
            f"• MACD Hist: `{last_hist:.5f}`\n"
            f"• SMA20: `{last_sma20:.5f}`\n"
            f"• SMA50: `{last_sma50:.5f}`\n\n"
            f"**Reasons**\n" + "\n".join(f"• {r}" for r in reasons) +
            f"\n\n_Generated at {datetime.utcnow().strftime('%Y-%m-%d %H:%M')} UTC_"
        )
        return msg

    except Exception as e:
        logger.error(f"Error: {e}")
        return f"❌ Error: {str(e)}"

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 *Trading Signal Bot*\n\n"
        "Try:\n"
        "`/signal XAUUSD`\n"
        "`/signal EURUSD`\n"
        "`/signal BTC-USD`\n"
        "`/help`",
        parse_mode="Markdown"
    )

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "*Popular symbols*\n"
        "`XAUUSD` `EURUSD` `GBPUSD` `USDJPY`\n"
        "`BTC-USD` `ETH-USD` `AAPL` `TSLA`",
        parse_mode="Markdown"
    )

async def signal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: `/signal XAUUSD`", parse_mode="Markdown")
        return

    symbol = context.args[0]
    interval = context.args[1] if len(context.args) > 1 else "1d"

    await update.message.reply_text(f"⏳ Analyzing `{symbol.upper()}`...")
    result = get_signal(symbol, interval)
    await update.message.reply_text(result, parse_mode="Markdown")

def main():
    if not BOT_TOKEN:
        print("TELEGRAM_BOT_TOKEN not set")
        return

    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("signal", signal))
    print("Bot is running...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
