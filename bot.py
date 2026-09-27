import os
import logging
from datetime import datetime
import yfinance as yf
import pandas as pd
from ta.momentum import RSIIndicator
from ta.trend import MACD, SMAIndicator
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
DEFAULT_INTERVAL = "1d"
LOOKBACK = "1y"

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

def get_gold_data(interval="1d"):
    """Try multiple gold tickers until one works"""
    gold_tickers = ["GC=F", "XAUUSD=X", "GOLD", "GLD"]
    
    for ticker in gold_tickers:
        try:
            data = yf.download(ticker, period=LOOKBACK, interval=interval, progress=False, auto_adjust=True)
            if not data.empty and len(data) >= 30:
                if isinstance(data.columns, pd.MultiIndex):
                    data.columns = data.columns.get_level_values(0)
                return data, ticker
        except Exception as e:
            logger.warning(f"Failed {ticker}: {e}")
            continue
    return None, None

def normalize_symbol(symbol: str) -> str:
    s = symbol.upper().strip()
    if s in ["XAUUSD", "XAU", "GOLD", "XAUUSD=X"]:
        return "GOLD"
    if "=" in s or "-" in s:
        return s
    if len(s) == 6 and s.isalpha():
        return f"{s}=X"
    return s

def get_signal(symbol: str, interval: str = DEFAULT_INTERVAL) -> str:
    try:
        symbol_upper = symbol.upper().strip()

        # Special handling for Gold
        if symbol_upper in ["XAUUSD", "XAU", "GOLD"]:
            data, used_ticker = get_gold_data(interval)
            if data is None:
                return "❌ Could not fetch gold data from any source. Try again later."
            display_name = "XAUUSD"
        else:
            ticker = normalize_symbol(symbol)
            data = yf.download(ticker, period=LOOKBACK, interval=interval, progress=False, auto_adjust=True)
            if data.empty or len(data) < 30:
                return f"❌ Not enough data for `{symbol}` on `{interval}`."
            if isinstance(data.columns, pd.MultiIndex):
                data.columns = data.columns.get_level_values(0)
            used_ticker = ticker
            display_name = symbol_upper

        close = data["Close"].dropna()
        if len(close) < 30:
            return f"❌ Not enough clean data for `{display_name}`."

        # Indicators
        rsi = RSIIndicator(close, window=14).rsi()
        macd_ind = MACD(close)
        hist = macd_ind.macd_diff()
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

        # Signal
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
        if display_name in ["XAUUSD", "GOLD"]:
            price_str = f"${last_close:,.2f}"
        else:
            price_str = f"{last_close:.5f}" if last_close < 50 else f"{last_close:.2f}"

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
        return f"❌ Error analyzing `{symbol}`: {str(e)}"

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 *Trading Signal Bot*\n\n"
        "Commands:\n"
        "`/signal EURUSD`\n"
        "`/signal XAUUSD`\n"
        "`/signal XAUUSD 4h`\n"
        "`/signal BTC-USD`\n"
        "`/help`",
        parse_mode="Markdown"
    )

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "📌 *Popular pairs*\n\n"
        "*Crypto:* `BTC-USD` • `ETH-USD` • `SOL-USD`\n"
        "*Forex:* `EURUSD` • `GBPUSD` • `USDJPY` • `AUDUSD`\n"
        "*Gold:* `XAUUSD` • `GOLD`\n"
        "*Stocks:* `AAPL` • `TSLA` • `NVDA`"
    )
    await update.message.reply_text(text, parse_mode="Markdown")

async def signal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text(
            "Usage:\n`/signal EURUSD`\n`/signal XAUUSD`\n`/signal XAUUSD 4h`",
            parse_mode="Markdown"
        )
        return

    symbol = context.args[0]
    interval = context.args[1] if len(context.args) > 1 else DEFAULT_INTERVAL

    await update.message.reply_text(f"⏳ Analyzing `{symbol.upper()}`...")
    result = get_signal(symbol, interval)
    await update.message.reply_text(result, parse_mode="Markdown")

def main():
    if not BOT_TOKEN:
        print("Error: TELEGRAM_BOT_TOKEN not set")
        return

    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("signal", signal))
    print("Bot started successfully...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
