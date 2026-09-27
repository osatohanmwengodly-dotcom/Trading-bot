import os
import logging
import requests
from datetime import datetime
import pandas as pd
from ta.momentum import RSIIndicator
from ta.trend import MACD, SMAIndicator
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

def get_binance_data(symbol: str, interval: str = "1d", limit: int = 200):
    """Fetch data from Binance public API"""
    symbol = symbol.upper().replace("-USD", "USDT").replace("-USDT", "USDT").replace("USDT", "USDT")
    
    # Make sure it ends with USDT
    if not symbol.endswith("USDT"):
        symbol = symbol + "USDT"

    url = "https://api.binance.com/api/v3/klines"
    params = {
        "symbol": symbol,
        "interval": interval,
        "limit": limit
    }

    try:
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()

        df = pd.DataFrame(data, columns=[
            "timestamp", "open", "high", "low", "close", "volume",
            "close_time", "quote_volume", "trades", "taker_buy_base",
            "taker_buy_quote", "ignore"
        ])

        df["close"] = pd.to_numeric(df["close"])
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
        df.set_index("timestamp", inplace=True)
        return df, symbol
    except Exception as e:
        logger.error(f"Binance error for {symbol}: {e}")
        return None, symbol

def get_signal(symbol: str, interval: str = "1d") -> str:
    try:
        # Map common timeframes
        tf_map = {
            "1d": "1d",
            "4h": "4h",
            "1h": "1h",
            "15m": "15m",
            "5m": "5m",
            "1w": "1w"
        }
        binance_interval = tf_map.get(interval.lower(), "1d")

        data, used_symbol = get_binance_data(symbol, interval=binance_interval)

        if data is None or len(data) < 30:
            return f"❌ Could not get data for `{symbol}`.\nMake sure it's a valid Binance pair (example: BTC-USD, ETH-USD, SOL-USD)"

        close = data["close"]

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

        # Final signal
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

        display_name = used_symbol.replace("USDT", "-USD")
        price_str = f"${last_close:,.2f}" if last_close > 1 else f"${last_close:.6f}"

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
        "👋 *Binance Signal Bot*\n\n"
        "Examples:\n"
        "`/signal BTC-USD`\n"
        "`/signal ETH-USD`\n"
        "`/signal SOL-USD`\n"
        "`/signal BNB-USD`\n"
        "`/signal XRP-USD`\n\n"
        "You can add timeframe:\n"
        "`/signal BTC-USD 4h`\n"
        "`/signal ETH-USD 1h`",
        parse_mode="Markdown"
    )

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "*Popular pairs*\n"
        "`BTC-USD` `ETH-USD` `SOL-USD` `BNB-USD`\n"
        "`XRP-USD` `ADA-USD` `DOGE-USD` `AVAX-USD`\n"
        "`DOT-USD` `LINK-USD` `MATIC-USD` `LTC-USD`\n\n"
        "*Timeframes*\n"
        "`1d` `4h` `1h` `15m` `5m`",
        parse_mode="Markdown"
    )

async def signal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: `/signal BTC-USD`", parse_mode="Markdown")
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
    print("Bot started successfully...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
