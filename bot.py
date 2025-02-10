import logging
import sqlite3
import random
import string
import os
from datetime import datetime, timedelta
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
    JobQueue
)

# ============================
# تنظیمات
# ============================
TOKEN = "7482034609:AAFK9VBVIc2UUoAXD2KFpJxSEVAdZl1uefI"  # جایگزین کنید
WEBHOOK_URL = "https://gbsmart-49kl.onrender.com/" + TOKEN  # جایگزین کنید
CHANNELS = ["@smartmodircom", "@ershadsajadian"]  # لیست کانال‌ها
ADMINS = [992366512]  # شناسه ادمین‌ها
SUPPORT, WALLET_ADDRESS, ADMIN_REPLY, SET_REWARD, SET_DAYS = range(5)

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
        
        CREATE TABLE IF NOT EXISTS reward_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            amount INTEGER,
            wallet_address TEXT,
            status TEXT DEFAULT 'pending',
            request_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        
        INSERT OR IGNORE INTO settings (key, value) VALUES ('reward_per_user', '10');
        INSERT OR IGNORE INTO settings (key, value) VALUES ('required_days', '30');
    """)
    conn.commit()

init_db()

# ============================
# دستورات اصلی کاربر
# ============================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """شروع ربات و بررسی عضویت در کانال‌ها"""
    user = update.effective_user
    telegram_id = user.id
    username = user.username or user.first_name

    if not cursor.execute("SELECT * FROM users WHERE telegram_id=?", (telegram_id,)).fetchone():
        referral_code = ''.join(random.choices(string.ascii_letters + string.digits, k=8))
        inviter_id = None
        
        if context.args:
            inviter = cursor.execute("SELECT telegram_id FROM users WHERE referral_code=?", (context.args[0],)).fetchone()
            inviter_id = inviter[0] if inviter else None

        cursor.execute(
            "INSERT INTO users (telegram_id, username, referral_code, inviter_id) VALUES (?,?,?,?)",
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
            [InlineKeyboardButton("🎁 لینک دعوت", callback_data="get_invite_link")],
            [InlineKeyboardButton("📊 لیست دعوت شدگان", callback_data="referral_stats")],
            [InlineKeyboardButton("💰 پاداش شما", callback_data="user_rewards")],
            [InlineKeyboardButton("📞 پشتیبانی", callback_data="support")]
        ]
        await query.edit_message_text(
            "✅ عضویت تأیید شد! از منوی زیر انتخاب کنید:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    else:
        await query.answer("❌ هنوز در همه کانال‌ها عضو نشده‌اید!", show_alert=True)

# ============================
# سیستم دعوت
# ============================
async def get_invite_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """تولید لینک دعوت"""
    query = update.callback_query
    user_id = query.from_user.id
    
    referral_code = cursor.execute(
        "SELECT referral_code FROM users WHERE telegram_id=?", (user_id,)
    ).fetchone()[0]
    
    bot_username = (await context.bot.get_me()).username
    invite_link = f"https://t.me/{bot_username}?start={referral_code}"
    
    await query.message.reply_text(
        f"🔗 لینک دعوت منحصر به فرد شما:\n{invite_link}\n\n"
        "هر فردی از طریق این لینک عضو شود، در لیست دعوت شدگان شما ثبت می‌شود!"
    )

async def referral_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """آمار دعوت شدگان"""
    query = update.callback_query
    user_id = query.from_user.id
    
    # کل دعوت شدگان
    total_ref = cursor.execute(
        "SELECT COUNT(*) FROM referrals WHERE inviter_id=?", (user_id,)
    ).fetchone()[0]
    
    # دعوت شدگان 30 روزه
    days = int(cursor.execute(
        "SELECT value FROM settings WHERE key='required_days'"
    ).fetchone()[0])
    
    active_ref = cursor.execute(f"""
        SELECT COUNT(*) 
        FROM referrals 
        WHERE inviter_id=? 
        AND julianday('now') - julianday(join_date) >= {days}
    """, (user_id,)).fetchone()[0]
    
    await query.message.reply_text(
        f"📊 آمار دعوت شدگان:\n\n"
        f"• کل دعوت شدگان: {total_ref} نفر\n"
        f"• دعوت شدگان فعال ({days}+ روز): {active_ref} نفر"
    )

# ============================
# سیستم پاداش
# ============================
async def user_rewards(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """محاسبه و نمایش پاداش"""
    query = update.callback_query
    user_id = query.from_user.id
    
    # محاسبه پاداش
    days = int(cursor.execute(
        "SELECT value FROM settings WHERE key='required_days'"
    ).fetchone()[0])
    
    active_ref = cursor.execute(f"""
        SELECT COUNT(*) 
        FROM referrals 
        WHERE inviter_id=? 
        AND julianday('now') - julianday(join_date) >= {days}
    """, (user_id,)).fetchone()[0]
    
    reward_per = int(cursor.execute(
        "SELECT value FROM settings WHERE key='reward_per_user'"
    ).fetchone()[0])
    
    total_reward = active_ref * reward_per
    
    keyboard = [[InlineKeyboardButton("💳 دریافت پاداش", callback_data="request_reward")]]
    
    await query.message.reply_text(
        f"💰 پاداش قابل دریافت شما:\n\n"
        f"• تعداد دعوت‌های واجد شرایط: {active_ref} نفر\n"
        f"• پاداش هر نفر: {reward_per} سکه\n"
        f"• مجموع: {total_reward} سکه\n\n"
        f"برای دریافت پاداش، دکمه زیر را کلیک کنید:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def request_reward(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """درخواست دریافت پاداش"""
    query = update.callback_query
    await query.message.reply_text("لطفاً آدرس کیف پول خود را وارد کنید:")
    return WALLET_ADDRESS

async def process_wallet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """پردازش آدرس کیف پول"""
    user_id = update.message.from_user.id
    wallet = update.message.text
    
    # ذخیره آدرس کیف پول
    cursor.execute(
        "UPDATE users SET wallet_address=? WHERE telegram_id=?", 
        (wallet, user_id)
    )
    
    # ثبت درخواست پاداش
    days = int(cursor.execute(
        "SELECT value FROM settings WHERE key='required_days'"
    ).fetchone()[0])
    
    active_ref = cursor.execute(f"""
        SELECT COUNT(*) 
        FROM referrals 
        WHERE inviter_id=? 
        AND julianday('now') - julianday(join_date) >= {days}
    """, (user_id,)).fetchone()[0]
    
    reward_per = int(cursor.execute(
        "SELECT value FROM settings WHERE key='reward_per_user'"
    ).fetchone()[0])
    
    total_reward = active_ref * reward_per
    
    cursor.execute(
        "INSERT INTO reward_requests (user_id, amount, wallet_address) VALUES (?,?,?)",
        (user_id, total_reward, wallet)
    )
    conn.commit()
    
    await update.message.reply_text(
        "✅ درخواست شما ثبت شد! پس از تأیید ادمین، پاداش به کیف پول شما واریز می‌شود."
    )
    return ConversationHandler.END

# ============================
# سیستم پشتیبانی
# ============================
async def support(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """شروع چت پشتیبانی"""
    await update.callback_query.message.reply_text(
        "📩 پیام خود را وارد کنید (برای لغو /cancel):"
    )
    return SUPPORT

async def support_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ذخیره پیام پشتیبانی"""
    user_id = update.message.from_user.id
    cursor.execute(
        "INSERT INTO support (telegram_id, message) VALUES (?,?)",
        (user_id, update.message.text)
    )
    conn.commit()
    
    for admin in ADMINS:
        await context.bot.send_message(
            admin,
            f"🚨 پیام جدید پشتیبانی از کاربر {user_id}:\n{update.message.text}"
        )
    
    await update.message.reply_text("✅ پیام شما ثبت شد.")
    return ConversationHandler.END

# ============================
# دستورات ادمین
# ============================
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """نمایش پنل ادمین"""
    if update.effective_user.id not in ADMINS:
        return
    
    keyboard = [
        [InlineKeyboardButton("👥 تعداد اعضا", callback_data="members_count")],
        [InlineKeyboardButton("📩 پیام‌های پشتیبانی", callback_data="support_messages")],
        [InlineKeyboardButton("🎁 درخواست‌های پاداش", callback_data="reward_requests")],
        [InlineKeyboardButton("⚙️ تنظیمات", callback_data="admin_settings")]
    ]
    
    await update.message.reply_text(
        "🛠 پنل مدیریت ادمین:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

# ============================
# اجرای ربات
# ============================
app = Flask(__name__)

@app.route(f"/{TOKEN}", methods=["POST"])
def webhook():
    update = Update.de_json(request.get_json(), application.bot)
    application.update_queue.put(update)
    return "OK", 200

if __name__ == "__main__":
    application = Application.builder().token(TOKEN).build()
    
    # افزودن هندلرها
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("admin", admin_panel))
    
    application.add_handler(ConversationHandler(
        entry_points=[CallbackQueryHandler(support, pattern="^support$")],
        states={
            SUPPORT: [MessageHandler(filters.TEXT & ~filters.COMMAND, support_message)]
        },
        fallbacks=[CommandHandler("cancel", lambda u,c: ConversationHandler.END)]
    ))
    
    application.add_handler(ConversationHandler(
        entry_points=[CallbackQueryHandler(request_reward, pattern="^request_reward$")],
        states={
            WALLET_ADDRESS: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_wallet)]
        },
        fallbacks=[]
    ))
    
    application.add_handler(CallbackQueryHandler(check_channels, pattern="^check_channels$"))
    application.add_handler(CallbackQueryHandler(get_invite_link, pattern="^get_invite_link$"))
    application.add_handler(CallbackQueryHandler(referral_stats, pattern="^referral_stats$"))
    application.add_handler(CallbackQueryHandler(user_rewards, pattern="^user_rewards$"))
    
    # اجرای ربات
    application.run_webhook(
        listen="0.0.0.0",
        port=int(os.environ.get("PORT", 8443)),
        webhook_url=WEBHOOK_URL,
        url_path=TOKEN,
        secret_token="YOUR_SECRET_TOKEN"
    )
