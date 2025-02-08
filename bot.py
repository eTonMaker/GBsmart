import logging
import sqlite3
import random
import string
import datetime
import os
from flask import Flask, request
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    ConversationHandler,
    ContextTypes,
)

# تنظیمات لاگ
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# ============================
# تنظیمات اولیه
# ============================

TOKEN = "7482034609:AAFK9VBVIc2UUoAXD2KFpJxSEVAdZl1uefI"  # توکن واقعی خود را وارد کنید
CHANNELS = ["@yourchannel1", "@yourchannel2"]  # کانال‌ها
ADMINS = [992366512]  # شناسه ادمین‌ها

# ============================
# پایگاه داده (SQLite)
# ============================

conn = sqlite3.connect("bot_database.db", check_same_thread=False)
cursor = conn.cursor()

def init_db():
    """ایجاد جداول پایگاه داده"""
    cursor.execute("""CREATE TABLE IF NOT EXISTS users (
            telegram_id INTEGER PRIMARY KEY,
            username TEXT,
            referral_code TEXT UNIQUE,
            inviter_id INTEGER,
            join_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            wallet_address TEXT
        )""")
    cursor.execute("""CREATE TABLE IF NOT EXISTS referrals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            inviter_id INTEGER,
            invited_id INTEGER,
            join_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            verified INTEGER DEFAULT 0,
            verified_date TIMESTAMP,
            reward_claimed INTEGER DEFAULT 0
        )""")
    cursor.execute("""CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )""")
    cursor.execute("""CREATE TABLE IF NOT EXISTS support (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id INTEGER,
            message TEXT,
            reply TEXT,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )""")
    cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", ("reward_per_user", "10"))
    cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", ("required_days", "30"))
    conn.commit()

# ============================
# دستورات و هندلرهای ربات
# ============================

SUPPORT_MESSAGE = 1  # شناسه مرحله مکالمه پشتیبانی

# /start : ثبت کاربر جدید، بررسی پارامتر دعوت و نمایش دکمه‌های عضویت در کانال‌ها
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info(f"Received /start command from {update.effective_user.id}")
    
    user = update.effective_user
    args = context.args
    telegram_id = user.id
    username = user.username if user.username else user.first_name

    # بررسی اینکه کاربر از قبل در پایگاه داده هست یا خیر
    cursor.execute("SELECT * FROM users WHERE telegram_id=?", (telegram_id,))
    result = cursor.fetchone()
    if not result:
        # کاربر جدید؛ تولید کد دعوت
        referral_code = generate_referral_code()
        inviter_id = None
        if args:
            inviter_code = args[0]
            # جستجو برای پیدا کردن inviter با استفاده از کد دعوت
            cursor.execute("SELECT telegram_id FROM users WHERE referral_code=?", (inviter_code,))
            inviter = cursor.fetchone()
            if inviter:
                inviter_id = inviter[0]
        cursor.execute("INSERT INTO users (telegram_id, username, referral_code, inviter_id) VALUES (?,?,?,?)", (telegram_id, username, referral_code, inviter_id))
        conn.commit()
        # اگر دعوت‌کننده وجود داشته باشد، رکورد دعوت ثبت می‌شود
        if inviter_id:
            cursor.execute("INSERT INTO referrals (inviter_id, invited_id) VALUES (?,?)", (inviter_id, telegram_id))
            conn.commit()

    # نمایش پیام خوشامدگویی و دکمه‌های عضویت در کانال‌ها
   
    join_keyboard = [
    [InlineKeyboardButton("عضویت در کانال شماره 1", url=f"https://t.me/{CHANNELS[0].lstrip('@')}")],
    [InlineKeyboardButton("عضویت در کانال شماره 2", url=f"https://t.me/{CHANNELS[1].lstrip('@')}")],
    [InlineKeyboardButton("تایید عضویت در کانال‌ها", callback_data="check_channels")]
]

reply_markup = InlineKeyboardMarkup(join_keyboard)
await update.message.reply_text("لطفاً ابتدا در کانال‌های زیر عضو شوید و سپس روی تایید عضویت کلیک کنید:", reply_markup=reply_markup)

# بررسی عضویت کاربر در کانال‌ها
async def check_channels(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info(f"Checking channel membership for user {update.callback_query.from_user.id}")
    
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
        except Exception as e:
            logger.error(f"Error checking membership for user {telegram_id} in {channel}: {e}")
            all_joined = False
            break

    if all_joined:
        await query.answer("عضویت شما تایید شد!")
        # نمایش منوی اصلی ربات
        main_menu_keyboard = [
            [InlineKeyboardButton("لینک دعوت اعضا", callback_data="referral_link")],
            [InlineKeyboardButton("لیست دعوت شدگان", callback_data="referral_list")],
            [InlineKeyboardButton("پاداش شما", callback_data="reward_info")],
            [InlineKeyboardButton("تماس با پشتیبانی", callback_data="support")],
        ]
        reply_markup = InlineKeyboardMarkup(main_menu_keyboard)
        await query.message.reply_text("منوی اصلی:", reply_markup=reply_markup)
    else:
        await query.answer("شما هنوز در تمامی کانال‌ها عضو نشده‌اید!", show_alert=True)

# نمایش لینک دعوت اختصاصی کاربر
async def referral_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    telegram_id = query.from_user.id
    cursor.execute("SELECT referral_code FROM users WHERE telegram_id=?", (telegram_id,))
    result = cursor.fetchone()
    if result:
        referral_code = result[0]
        bot_username = (await context.bot.get_me()).username
        link = f"https://t.me/{bot_username}?start={referral_code}"
        await query.answer()
        await query.message.reply_text(f"لینک دعوت اختصاصی شما:\n{link}")
    else:
        await query.answer("کاربر شما پیدا نشد!", show_alert=True)

# ============================
# تنظیمات و استارت ربات
# ============================

# ایجاد Flask برای مدیریت Webhook
app = Flask(__name__)

@app.route(f"/{TOKEN}", methods=["POST"])
def webhook():
    json_str = request.get_data(as_text=True)
    update = Update.de_json(json_str, application.bot)
    application.process_update(update)
    return "", 200

# راه‌اندازی ربات
def main():
    # راه‌اندازی ربات
    init_db()

    global application
    application = Application.builder().token(TOKEN).build()

    # هندلرهای دستورهای مختلف
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(check_channels, pattern="^check_channels$"))

    # تنظیم Webhook
    PORT = int(os.environ.get("PORT", 8443))  # مقدار پیش‌فرض 8443 اگر PORT موجود نبود
    webhook_url = f"https://gbsmart-49kl.onrender.com/{TOKEN}"
    application.run_webhook(
        listen="0.0.0.0",  # لیسن روی تمام اینترفیس‌ها
        port=PORT,  # استفاده از پورت اختصاص داده‌شده توسط Render
        url_path=TOKEN,
        webhook_url=webhook_url
    )

if __name__ == "__main__":
    main()
