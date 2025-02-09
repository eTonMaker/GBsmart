import logging
import sqlite3
import random
import string
import os
from flask import Flask, request
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    ContextTypes,
    ConversationHandler,
)

# ============================
# تنظیمات
# ============================

TOKEN = "7482034609:AAFK9VBVIc2UUoAXD2KFpJxSEVAdZl1uefI"  # جایگزین کنید
WEBHOOK_URL = "https://gbsmart-49kl.onrender.com/" + TOKEN  # آدرس وب‌هوک
CHANNELS = ["@smartmodircom", "@ershadsajadian"]  # لیست کانال‌ها
ADMINS = [992366512]  # شناسه ادمین‌ها

# تنظیمات لاگ
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ============================
# پایگاه داده (SQLite)
# ============================

conn = sqlite3.connect("bot_database.db", check_same_thread=False)
cursor = conn.cursor()

def init_db():
    """ایجاد جداول پایگاه داده در صورت عدم وجود"""
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            telegram_id INTEGER PRIMARY KEY,
            username TEXT,
            referral_code TEXT UNIQUE,
            inviter_id INTEGER,
            join_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            wallet_address TEXT
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS referrals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            inviter_id INTEGER,
            invited_id INTEGER,
            join_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            verified INTEGER DEFAULT 0
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS support (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id INTEGER,
            message TEXT,
            reply TEXT,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()

init_db()

# ============================
# دستورات ربات
# ============================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """شروع ربات و بررسی عضویت در کانال‌ها"""
    user = update.effective_user
    telegram_id = user.id
    username = user.username if user.username else user.first_name

    cursor.execute("SELECT * FROM users WHERE telegram_id=?", (telegram_id,))
    result = cursor.fetchone()
    
    if not result:
        referral_code = ''.join(random.choices(string.ascii_letters + string.digits, k=8))
        inviter_id = None
        if context.args:
            inviter_code = context.args[0]
            cursor.execute("SELECT telegram_id FROM users WHERE referral_code=?", (inviter_code,))
            inviter = cursor.fetchone()
            if inviter:
                inviter_id = inviter[0]

        cursor.execute("INSERT INTO users (telegram_id, username, referral_code, inviter_id) VALUES (?,?,?,?)", 
                       (telegram_id, username, referral_code, inviter_id))
        conn.commit()
        if inviter_id:
            cursor.execute("INSERT INTO referrals (inviter_id, invited_id) VALUES (?,?)", (inviter_id, telegram_id))
            conn.commit()

    join_keyboard = [
        [InlineKeyboardButton("عضویت در کانال 1", url=f"https://t.me/{CHANNELS[0].lstrip('@')}")],
        [InlineKeyboardButton("عضویت در کانال 2", url=f"https://t.me/{CHANNELS[1].lstrip('@')}")],
        [InlineKeyboardButton("✅ تایید عضویت", callback_data="check_channels")]
    ]
    reply_markup = InlineKeyboardMarkup(join_keyboard)
    await update.message.reply_text("لطفاً در کانال‌ها عضو شوید و سپس تأیید کنید:", reply_markup=reply_markup)

async def check_channels(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """بررسی عضویت در کانال‌ها و نمایش منوی اصلی"""
    query = update.callback_query
    user = query.from_user
    telegram_id = user.id

    all_joined = True
    for channel in CHANNELS:
        try:
            member = await context.bot.get_chat_member(channel, telegram_id)
            if member.status not in ["member", "creator", "administrator"]:
                all_joined = False
                break
        except Exception:
            all_joined = False
            break

    if all_joined:
        await query.answer("عضویت شما تأیید شد!")
        
        main_menu = [
            [InlineKeyboardButton("🎁 دریافت لینک دعوت", callback_data="get_referral_link")],
            [InlineKeyboardButton("💰 مشاهده موجودی", callback_data="check_balance")],
            [InlineKeyboardButton("📞 پشتیبانی", callback_data="support")]
        ]
        reply_markup = InlineKeyboardMarkup(main_menu)

        await query.message.reply_text(
            "✅ شما در کانال‌ها عضو شدید. حالا می‌توانید از ربات استفاده کنید.", 
            reply_markup=reply_markup
        )
    else:
        await query.answer("شما هنوز در کانال‌ها عضو نشده‌اید!", show_alert=True)

async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """پنل مدیریت برای ادمین‌ها"""
    if update.message.from_user.id in ADMINS:
        keyboard = [
            [InlineKeyboardButton("👥 مشاهده کاربران", callback_data="admin_users")],
            [InlineKeyboardButton("📩 درخواست‌های پشتیبانی", callback_data="admin_support")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text("📊 پنل مدیریت:", reply_markup=reply_markup)
    else:
        await update.message.reply_text("⛔ شما دسترسی ندارید!")

# ============================
# تنظیم وب‌هوک و اجرای ربات
# ============================

app = Flask(__name__)

@app.route(f"/{TOKEN}", methods=["POST"])
def webhook():
    update = Update.de_json(request.get_json(), application.bot)
    application.update_queue.put(update)
    return "OK", 200

if __name__ == "__main__":
    application = Application.builder().token(TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("admin", admin_panel))
    application.add_handler(CallbackQueryHandler(check_channels, pattern="^check_channels$"))
    application.add_handler(CallbackQueryHandler(admin_panel, pattern="^admin_panel$"))

    application.run_webhook(
        listen="0.0.0.0",
        port=int(os.environ.get("PORT", 8443)),
        url_path=TOKEN,
        webhook_url=WEBHOOK_URL
    )
