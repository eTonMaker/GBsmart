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
SUPPORT, ADMIN_REPLY, SET_REWARD, SET_DAYS = range(4)

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
        
        CREATE TABLE IF NOT EXISTS channel_membership (
            user_id INTEGER,
            channel TEXT,
            join_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            leave_date TIMESTAMP,
            PRIMARY KEY (user_id, channel)
        );
        
        CREATE TABLE IF NOT EXISTS reward_requests (
            user_id INTEGER PRIMARY KEY,
            amount INTEGER,
            status TEXT DEFAULT 'pending'
        );
        
        INSERT OR IGNORE INTO settings (key, value) VALUES ('reward_per_user', '10');
        INSERT OR IGNORE INTO settings (key, value) VALUES ('required_days', '30');
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
# سیستم دعوت و موجودی
# ============================
async def get_invite_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """تولید لینک دعوت"""
    query = update.callback_query
    user_id = query.from_user.id
    
    if referral_code := cursor.execute(
        "SELECT referral_code FROM users WHERE telegram_id=?", (user_id,)
    ).fetchone()[0]:
        bot_username = (await context.bot.get_me()).username
        await query.message.reply_text(
            f"🔗 لینک دعوت شما:\nhttps://t.me/{bot_username}?start={referral_code}"
        )
    else:
        await query.answer("⛔ خطا در تولید لینک!", show_alert=True)

async def check_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """نمایش موجودی"""
    query = update.callback_query
    user_id = query.from_user.id
    
    referrals = cursor.execute(
        "SELECT COUNT(*) FROM referrals WHERE inviter_id=?", (user_id,)
    ).fetchone()[0]
    
    reward = int(cursor.execute(
        "SELECT value FROM settings WHERE key='reward_per_user'"
    ).fetchone()[0])
    
    await query.message.reply_text(
        f"💎 موجودی شما: {referrals * reward} سکه\n👥 تعداد دعوت‌ها: {referrals}"
    )

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
            f"🚨 پیام جدید پشتیبانی:\nاز: {user_id}\nمتن: {update.message.text}"
        )
    
    await update.message.reply_text("✅ پیام شما ثبت شد.")
    return ConversationHandler.END

async def reply_to_support(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """پاسخ ادمین به کاربر"""
    if update.effective_user.id not in ADMINS:
        return
    
    args = context.args
    if len(args) < 2:
        await update.message.reply_text("⚠️ فرمت صحیح: /reply <user_id> <پیام>")
        return
    
    user_id = args[0]
    message = " ".join(args[1:])
    
    try:
        await context.bot.send_message(user_id, f"📬 پاسخ پشتیبانی:\n{message}")
        cursor.execute(
            "INSERT INTO support (telegram_id, reply) VALUES (?,?)",
            (user_id, message)
        )
        conn.commit()
        await update.message.reply_text("✅ پاسخ ارسال شد.")
    except Exception as e:
        await update.message.reply_text(f"❌ ارسال ناموفق: {e}")

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
        [InlineKeyboardButton("✅ چک کردن اعضا", callback_data="check_members")],
        [InlineKeyboardButton("🎁 لیست پاداش‌ها", callback_data="reward_list")],
        [InlineKeyboardButton("💰 تنظیم پاداش", callback_data="set_reward")],
        [InlineKeyboardButton("📆 تنظیم روزهای لازم", callback_data="set_days")]
    ]
    
    await update.message.reply_text(
        "🛠 پنل مدیریت ادمین:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def members_count(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    count = cursor.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    await query.message.reply_text(f"👥 تعداد کل اعضا: {count} نفر")

async def show_support_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    messages = cursor.execute("""
        SELECT id, telegram_id, message 
        FROM support 
        WHERE reply IS NULL
    """).fetchall()
    
    if not messages:
        await query.answer("⚠️ هیچ پیام جدیدی وجود ندارد!")
        return
    
    for msg in messages:
        keyboard = [[InlineKeyboardButton("✉️ پاسخ", callback_data=f"reply_{msg[0]}")]]
        await query.message.reply_text(
            f"📩 پیام از کاربر {msg[1]}:\n{msg[2]}",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

async def reply_to_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    message_id = query.data.split("_")[1]
    
    context.user_data["reply_msg_id"] = message_id
    await query.message.reply_text("پاسخ خود را وارد کنید:")
    return ADMIN_REPLY

async def process_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message_id = context.user_data["reply_msg_id"]
    reply_text = update.message.text
    
    msg_data = cursor.execute("""
        SELECT telegram_id, message 
        FROM support 
        WHERE id=?
    """, (message_id,)).fetchone()
    
    await context.bot.send_message(
        msg_data[0], 
        f"📬 پاسخ پشتیبانی:\n{reply_text}"
    )
    
    cursor.execute("""
        UPDATE support 
        SET reply=? 
        WHERE id=?
    """, (reply_text, message_id))
    conn.commit()
    
    await update.message.reply_text("✅ پاسخ با موفقیت ارسال شد!")
    return ConversationHandler.END

async def check_members(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    days = int(cursor.execute("""
        SELECT value 
        FROM settings 
        WHERE key='required_days'
    """).fetchone()[0])
    
    active_users = cursor.execute(f"""
        SELECT inviter_id, COUNT(*) 
        FROM referrals 
        WHERE julianday('now') - julianday(join_date) >= {days}
        GROUP BY inviter_id
    """).fetchall()
    
    report = "📊 گزارش اعضای فعال:\n"
    for user in active_users:
        report += f"👤 کاربر {user[0]}: {user[1]} عضو فعال\n"
    
    await query.message.reply_text(report)

async def reward_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    requests = cursor.execute("""
        SELECT u.username, r.amount 
        FROM reward_requests r
        JOIN users u ON r.user_id = u.telegram_id
        WHERE r.status='pending'
    """).fetchall()
    
    if not requests:
        await query.answer("⚠️ هیچ درخواست پاداشی وجود ندارد!")
        return
    
    report = "📜 لیست درخواست‌های پاداش:\n"
    for req in requests:
        report += f"• {req[0]}: {req[1]} سکه\n"
    
    await query.message.reply_text(report)

async def set_reward_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.message.reply_text("مقدار جدید پاداش برای هر دعوت را وارد کنید:")
    return SET_REWARD

async def process_reward(update: Update, context: ContextTypes.DEFAULT_TYPE):
    new_reward = update.message.text
    if not new_reward.isdigit():
        await update.message.reply_text("⚠️ لطفا یک عدد وارد کنید!")
        return
    
    cursor.execute("""
        UPDATE settings 
        SET value=? 
        WHERE key='reward_per_user'
    """, (new_reward,))
    conn.commit()
    
    await update.message.reply_text(f"✅ پاداش هر دعوت به {new_reward} سکه تنظیم شد!")
    return ConversationHandler.END

async def set_days_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.message.reply_text("تعداد روزهای لازم را وارد کنید:")
    return SET_DAYS

async def process_days(update: Update, context: ContextTypes.DEFAULT_TYPE):
    new_days = update.message.text
    if not new_days.isdigit():
        await update.message.reply_text("⚠️ لطفا یک عدد وارد کنید!")
        return
    
    cursor.execute("""
        UPDATE settings 
        SET value=? 
        WHERE key='required_days'
    """, (new_days,))
    conn.commit()
    
    await update.message.reply_text(f"✅ روزهای لازم به {new_days} روز تنظیم شد!")
    return ConversationHandler.END

# ============================
# بررسی دوره‌ای عضویت
# ============================
async def periodic_channel_check(context: ContextTypes.DEFAULT_TYPE):
    for user in cursor.execute("SELECT telegram_id FROM users").fetchall():
        user_id = user[0]
        for channel in CHANNELS:
            try:
                member = await context.bot.get_chat_member(channel, user_id)
                if member.status not in ["member", "creator", "administrator"]:
                    await context.bot.send_message(
                        user_id,
                        "⚠️ دسترسی شما به دلیل عدم عضویت در کانال‌ها محدود شد!"
                    )
            except Exception as e:
                logger.error(f"Channel check error: {e}")

# ============================
# تنظیمات اجرا
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
    application.add_handler(CommandHandler("reply", reply_to_support))
    
    application.add_handler(ConversationHandler(
        entry_points=[CallbackQueryHandler(support, pattern="^support$")],
        states={
            SUPPORT: [MessageHandler(filters.TEXT & ~filters.COMMAND, support_message)]
        },
        fallbacks=[CommandHandler("cancel", lambda u,c: ConversationHandler.END)]
    ))
    
    application.add_handler(ConversationHandler(
        entry_points=[CallbackQueryHandler(reply_to_message, pattern="^reply_")],
        states={
            ADMIN_REPLY: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_reply)]
        },
        fallbacks=[]
    ))
    
    application.add_handler(ConversationHandler(
        entry_points=[CallbackQueryHandler(set_reward_panel, pattern="^set_reward$")],
        states={
            SET_REWARD: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_reward)]
        },
        fallbacks=[]
    ))
    
    application.add_handler(ConversationHandler(
        entry_points=[CallbackQueryHandler(set_days_panel, pattern="^set_days$")],
        states={
            SET_DAYS: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_days)]
        },
        fallbacks=[]
    ))
    
    application.add_handler(CallbackQueryHandler(check_channels, pattern="^check_channels$"))
    application.add_handler(CallbackQueryHandler(get_invite_link, pattern="^get_invite_link$"))
    application.add_handler(CallbackQueryHandler(check_balance, pattern="^check_balance$"))
    application.add_handler(CallbackQueryHandler(members_count, pattern="^members_count$"))
    application.add_handler(CallbackQueryHandler(show_support_messages, pattern="^support_messages$"))
    application.add_handler(CallbackQueryHandler(check_members, pattern="^check_members$"))
    application.add_handler(CallbackQueryHandler(reward_list, pattern="^reward_list$"))
    
    # فعال‌سازی بررسی دوره‌ای
    application.job_queue.run_repeating(periodic_channel_check, interval=86400)

    # اجرای ربات
    application.run_webhook(
        listen="0.0.0.0",
        port=int(os.environ.get("PORT", 8443)),
        webhook_url=WEBHOOK_URL,
        url_path=TOKEN,
        secret_token="YOUR_SECRET_TOKEN"  # اختیاری
    )
