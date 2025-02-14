import logging
import sqlite3
import random
import string
from dotenv import load_dotenv
load_dotenv()
import os
from flask import Flask, request
from telegram import (
    Update,
    ReplyKeyboardMarkup,
    InlineKeyboardButton,
    InlineKeyboardMarkup
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes,
    ConversationHandler,
)

# ============================
# تنظیمات اولیه
# ============================
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
WEBHOOK_URL = f"https://gbsmart-49kl.onrender.com/{TOKEN}"
CHANNELS = ["@smartmodircom", "@ershadsajadian"]
ADMINS = [992366512]

# حالت‌های مکالمه
SUPPORT, WALLET_ADDRESS, ADMIN_REPLY = range(3)

# متغیرهای دکمه
BTN_VERIFY = "✅ تایید عضویت"
BTN_INVITE = "🎁 دریافت لینک دعوت"
BTN_REFERRAL_LIST = "📊 لیست دعوت شدگان"
BTN_REWARD = "💰 پاداش شما"
BTN_RECEIVE_REWARD = "💳 دریافت پاداش"
BTN_SUPPORT = "📞 پشتیبانی"

# ============================
# تنظیمات لاگ
# ============================
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ============================
# پایگاه داده
# ============================
conn = sqlite3.connect("database.db", check_same_thread=False)
cursor = conn.cursor()

def init_db():
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
        CREATE TABLE IF NOT EXISTS support (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id INTEGER,
            message TEXT,
            reply TEXT,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)
    conn.commit()
init_db()

# ============================
# دستورات کاربری
# ============================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
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

    channels_text = "\n".join([f"{chan} (https://t.me/{chan.lstrip('@')})" for chan in CHANNELS])
    await update.message.reply_text(
        f"لطفاً در کانال‌های زیر عضو شوید:\n{channels_text}\n\nسپس دکمه تایید را بزنید:",
        reply_markup=ReplyKeyboardMarkup([[BTN_VERIFY]], resize_keyboard=True)
    )

async def verify_membership(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    try:
        for channel in CHANNELS:
            member = await context.bot.get_chat_member(channel, user_id)
            if member.status not in ["member", "creator", "administrator"]:
                await update.message.reply_text("❌ هنوز در همه کانال‌ها عضو نشده‌اید!")
                return
                
        await update.message.reply_text(
            "✅ عضویت تأیید شد!",
            reply_markup=ReplyKeyboardMarkup(
                [
                    [BTN_INVITE, BTN_REFERRAL_LIST],
                    [BTN_REWARD, BTN_SUPPORT]
                ],
                resize_keyboard=True
            )
        )
    except Exception as e:
        logger.error(f"خطا در بررسی عضویت: {str(e)}")
        await update.message.reply_text("❌ خطا در بررسی عضویت!")

# ============================
# سیستم پشتیبانی پیشرفته
# ============================
async def support_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📩 لطفاً پیام خود را وارد کنید:")
    return SUPPORT

async def support_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    message = update.message.text
    
    try:
        cursor.execute(
            "INSERT INTO support (telegram_id, message) VALUES (?,?)",
            (user_id, message)
        )
        support_id = cursor.lastrowid
        conn.commit()
        
        keyboard = [[InlineKeyboardButton("📩 پاسخ به این پیام", callback_data=f"reply_{support_id}")]]
        
        for admin in ADMINS:
            await context.bot.send_message(
                admin,
                f"🚨 پیام جدید پشتیبانی (ID: {support_id})\nاز: {user_id}\nمتن: {message}",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            
        await update.message.reply_text("✅ پیام شما ثبت شد!")
        
    except Exception as e:
        logger.error(f"خطا در ثبت پیام: {str(e)}")
        await update.message.reply_text("❌ خطا در ثبت پیام!")
    
    return ConversationHandler.END

async def handle_admin_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    support_id = query.data.split("_")[1]
    context.user_data["support_id"] = support_id
    
    await query.message.reply_text("لطفاً پاسخ خود را وارد کنید:")
    return ADMIN_REPLY

async def process_admin_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    support_id = context.user_data.get("support_id")
    reply_text = update.message.text
    
    try:
        cursor.execute(
            "SELECT telegram_id, message FROM support WHERE id = ?",
            (support_id,)
        )
        user_id, original_message = cursor.fetchone()
        
        cursor.execute(
            "UPDATE support SET reply = ? WHERE id = ?",
            (reply_text, support_id)
        )
        conn.commit()
        
        await context.bot.send_message(
            user_id,
            f"📬 پاسخ پشتیبانی:\n{original_message}\n\n📤 پاسخ ادمین:\n{reply_text}"
        )
        
        await update.message.reply_text("✅ پاسخ با موفقیت ارسال شد!")
        
    except Exception as e:
        logger.error(f"خطا در ارسال پاسخ: {str(e)}")
        await update.message.reply_text("❌ خطا در ارسال پاسخ!")
    
    return ConversationHandler.END

# ============================
# اجرای ربات
# ============================
app = Flask(__name__)

@app.route(f"/{TOKEN}", methods=["POST"])
def webhook():
    update = Update.de_json(request.get_json(), app.bot)
    app.update_queue.put(update)
    return "OK", 200

if __name__ == "__main__":
    application = Application.builder().token(TOKEN).build()
    
    # دستورات اصلی
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.Regex(f"^{BTN_VERIFY}$"), verify_membership))
    
    # مکالمه پشتیبانی
    support_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex(f"^{BTN_SUPPORT}$"), support_start)],
        states={SUPPORT: [MessageHandler(filters.TEXT & ~filters.COMMAND, support_message)]},
        fallbacks=[CommandHandler("cancel", lambda u, c: ConversationHandler.END)]
    )
    application.add_handler(support_conv)
    
    # مکالمه پاسخ ادمین
    admin_reply_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(handle_admin_reply, pattern=r"^reply_")],
        states={ADMIN_REPLY: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_admin_reply)]},
        fallbacks=[CommandHandler("cancel", lambda u, c: ConversationHandler.END)]
    )
    application.add_handler(admin_reply_conv)
    
    application.run_webhook(
        listen="0.0.0.0",
        port=int(os.environ.get("PORT", 8443)),
        webhook_url=WEBHOOK_URL,
        secret_token="YOUR_SECRET_TOKEN",
        drop_pending_updates=True
    )
