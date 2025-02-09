import logging
import sqlite3
import random
import string
import os
from flask import Flask, request
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, MessageHandler,
    filters, ContextTypes, ConversationHandler
)

# ============================
# تنظیمات
# ============================
TOKEN = "7482034609:AAFK9VBVIc2UUoAXD2KFpJxSEVAdZl1uefI"  # جایگزین کنید
WEBHOOK_URL = "https://gbsmart-49kl.onrender.com/" + TOKEN  # جایگزین کنید
CHANNELS = ["@smartmodircom", "@ershadsajadian"]  # لیست کانال‌ها
ADMINS = [992366512]  # شناسه ادمین‌ها
SUPPORT = range(1)

# تنظیمات لاگ
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# ============================
# پایگاه داده (SQLite)
# ============================
conn = sqlite3.connect("bot_database.db", check_same_thread=False)
cursor = conn.cursor()

def init_db():
    """ایجاد جداول پایگاه داده"""
    cursor.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            telegram_id INTEGER PRIMARY KEY,
            username TEXT,
            referral_code TEXT UNIQUE,
            inviter_id INTEGER,
            join_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            wallet_address TEXT
        );

        CREATE TABLE IF NOT EXISTS referrals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            inviter_id INTEGER,
            invited_id INTEGER,
            join_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            verified INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        );

        CREATE TABLE IF NOT EXISTS support (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id INTEGER,
            message TEXT,
            reply TEXT,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        INSERT OR IGNORE INTO settings (key, value) VALUES ('reward_per_user', '10');
    """)
    conn.commit()

init_db()

# ============================
# دستورات اصلی ربات
# ============================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """شروع ربات و بررسی عضویت در کانال‌ها"""
    user = update.effective_user
    telegram_id = user.id
    username = user.username or user.first_name

    referral_code = ''.join(random.choices(string.ascii_letters + string.digits, k=8))
    inviter_id = None

    if context.args and len(context.args) > 0:
        inviter = cursor.execute("SELECT telegram_id FROM users WHERE referral_code=?", (context.args[0],)).fetchone()
        inviter_id = inviter[0] if inviter else None

    cursor.execute(
        "INSERT OR IGNORE INTO users (telegram_id, username, referral_code, inviter_id) VALUES (?,?,?,?)",
        (telegram_id, username, referral_code, inviter_id)
    )
    if inviter_id:
        cursor.execute("INSERT INTO referrals (inviter_id, invited_id) VALUES (?,?)", (inviter_id, telegram_id))
    conn.commit()

    keyboard = [
        [InlineKeyboardButton(f"عضویت در {chan}", url=f"https://t.me/{chan.lstrip('@')}") for chan in CHANNELS],
        [InlineKeyboardButton("✅ تایید عضویت", callback_data="check_channels")]
    ]
    await update.message.reply_text(
        "📢 لطفاً در کانال‌ها عضو شوید و سپس تأیید کنید:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def check_channels(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """بررسی عضویت در کانال‌ها"""
    query = update.callback_query
    user_id = query.from_user.id
    
    all_joined = True
    for channel in CHANNELS:
        try:
            member = await context.bot.get_chat_member(channel, user_id)
            if member.status not in ["member", "creator", "administrator"]:
                all_joined = False
                break
        except Exception as e:
            logger.error(f"Channel check error: {e}")
            all_joined = False

    if all_joined:
        keyboard = [
            [InlineKeyboardButton("🎁 دریافت لینک دعوت", callback_data="get_invite_link")],
            [InlineKeyboardButton("💰 موجودی", callback_data="check_balance")],
            [InlineKeyboardButton("📞 پشتیبانی", callback_data="support")]
        ]
        await query.edit_message_text(
            "✅ عضویت تأیید شد! از منوی زیر انتخاب کنید:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    else:
        await query.answer("❌ هنوز در همه کانال‌ها عضو نشده‌اید!", show_alert=True)

# ============================
# تنظیمات اجرا
# ============================
app = Flask(__name__)

application = Application.builder().token(TOKEN).build()

@app.route(f"/{TOKEN}", methods=["POST"])
def webhook():
    update = Update.de_json(request.get_json(), application.bot)
    application.update_queue.put(update)
    return "OK", 200

if __name__ == "__main__":
    # افزودن هندلرها
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(check_channels, pattern="^check_channels$"))

    # اجرای Flask
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
