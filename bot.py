import logging
import sqlite3
import random
import string
import datetime
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

# ============================
# تنظیمات اولیه
# ============================

TOKEN = "7482034609:AAFK9VBVIc2UUoAXD2KFpJxSEVAdZl1uefI"
CHANNELS = ["@yourchannel1", "@yourchannel2"]
ADMINS = [992366512]

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
            verified INTEGER DEFAULT 0,
            verified_date TIMESTAMP,
            reward_claimed INTEGER DEFAULT 0
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
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
    cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", ("reward_per_user", "10"))
    cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", ("required_days", "30"))
    conn.commit()

def generate_referral_code(length=6):
    """تولید کد دعوت تصادفی"""
    return "".join(random.choices(string.ascii_uppercase + string.digits, k=length))

SUPPORT_MESSAGE, WALLET_INPUT = range(2)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    args = context.args
    telegram_id = user.id
    username = user.username if user.username else user.first_name

    cursor.execute("SELECT * FROM users WHERE telegram_id=?", (telegram_id,))
    result = cursor.fetchone()
    if not result:
        referral_code = generate_referral_code()
        inviter_id = None
        if args:
            inviter_code = args[0]
            cursor.execute("SELECT telegram_id FROM users WHERE referral_code=?", (inviter_code,))
            inviter = cursor.fetchone()
            if inviter:
                inviter_id = inviter[0]
        cursor.execute("INSERT INTO users (telegram_id, username, referral_code, inviter_id) VALUES (?,?,?,?)", (telegram_id, username, referral_code, inviter_id))
        conn.commit()
        if inviter_id:
            cursor.execute("INSERT INTO referrals (inviter_id, invited_id) VALUES (?,?)", (inviter_id, telegram_id))
            conn.commit()

    join_keyboard = [
        [InlineKeyboardButton("عضویت در کانال شماره 1", url=f"https://t.me/{CHANNELS[0].lstrip('@')}")],
        [InlineKeyboardButton("عضویت در کانال شماره 2", url=f"https://t.me/{CHANNELS[1].lstrip('@')}")],
        [InlineKeyboardButton("تایید عضویت در کانال‌ها", callback_data="check_channels")]
    ]
    reply_markup = InlineKeyboardMarkup(join_keyboard)
    await update.message.reply_text("لطفاً ابتدا در کانال‌های زیر عضو شوید و سپس روی تایید عضویت کلیک کنید:", reply_markup=reply_markup)

async def check_channels(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
            logger.error(f"خطا در بررسی عضویت کاربر {telegram_id} در {channel}: {e}")
            all_joined = False
            break

    if all_joined:
        await query.answer("عضویت شما تایید شد!")
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

# ادامه کد و متدها...
