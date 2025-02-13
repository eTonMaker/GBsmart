import logging
import sqlite3
import random
import string
from dotenv import load_dotenv
load_dotenv()
import os
from datetime import datetime
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
# تنظیمات
# ============================
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
WEBHOOK_URL = f"https://gbsmart-49kl.onrender.com/{TOKEN}"
CHANNELS = ["@smartmodircom", "@ershadsajadian"]
ADMINS = [992366512]

# حالت‌های مکالمه
SUPPORT, WALLET_ADDRESS, ADMIN_REPLY, SET_REWARD, SET_DAYS, RECEIVE_REWARD = range(6)

# متغیرهای دکمه
BTN_VERIFY = "✅ تایید عضویت"
BTN_INVITE = "🎁 دریافت لینک دعوت"
BTN_REFERRAL_LIST = "📊 لیست دعوت شدگان"
BTN_REWARD = "💰 پاداش شما"
BTN_RECEIVE_REWARD = "💳 دریافت پاداش"
BTN_SUPPORT = "📞 پشتیبانی"

# ============================
# تنظیمات پایگاه داده
# ============================
conn = sqlite3.connect("database.db", check_same_thread=False)
cursor = conn.cursor()

def init_db():
    cursor.executescript("""
        CREATE TABLE IF NOT EXISTS support (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id INTEGER,
            message TEXT,
            reply TEXT,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        -- دیگر جداول (بقیه جداول بدون تغییر)
    """)
    conn.commit()
init_db()

# ============================
# سیستم پشتیبانی پیشرفته
# ============================
async def support_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    # بررسی عضویت در کانال‌ها
    for channel in CHANNELS:
        try:
            member = await context.bot.get_chat_member(channel, user_id)
            if member.status not in ["member", "creator", "administrator"]:
                await update.message.reply_text("❌ برای استفاده از پشتیبانی باید در کانال‌ها عضو باشید!")
                return ConversationHandler.END
        except Exception as e:
            logger.error(f"خطای بررسی کانال: {e}")
            await update.message.reply_text("❌ خطا در بررسی عضویت!")
            return ConversationHandler.END
    
    await update.message.reply_text("📩 لطفاً پیام خود را وارد کنید (برای لغو /cancel):")
    return SUPPORT

async def support_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    message_text = update.message.text
    
    try:
        cursor.execute(
            "INSERT INTO support (telegram_id, message) VALUES (?,?)",
            (user_id, message_text)
        )
        conn.commit()
        support_id = cursor.lastrowid
        
        # ایجاد دکمه پاسخ اینلاین
        keyboard = [[InlineKeyboardButton("📩 پاسخ به این پیام", callback_data=f"reply_{support_id}")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        # ارسال به ادمین‌ها با دکمه پاسخ
        for admin in ADMINS:
            await context.bot.send_message(
                chat_id=admin,
                text=f"🚨 پیام جدید پشتیبانی (ID: {support_id}):\n"
                     f"کاربر: {user_id}\n"
                     f"متن پیام: {message_text}",
                reply_markup=reply_markup
            )
        
        await update.message.reply_text("✅ پیام شما ثبت شد. منتظر پاسخ باشید.")
    
    except Exception as e:
        logger.error(f"خطا در ثبت پیام: {str(e)}")
        await update.message.reply_text("⛔ خطایی رخ داد!")
    
    return ConversationHandler.END

async def handle_admin_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    support_id = query.data.split("_")[1]
    context.user_data['support_id'] = support_id
    
    await query.message.reply_text("لطفاً پاسخ خود را وارد کنید:")
    return ADMIN_REPLY

async def process_admin_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    support_id = context.user_data.get('support_id')
    admin_reply = update.message.text
    
    try:
        # دریافت اطلاعات پیام اصلی
        cursor.execute(
            "SELECT telegram_id, message FROM support WHERE id = ?",
            (support_id,)
        )
        user_id, original_message = cursor.fetchone()
        
        # ذخیره پاسخ در دیتابیس
        cursor.execute(
            "UPDATE support SET reply = ? WHERE id = ?",
            (admin_reply, support_id)
        )
        conn.commit()
        
        # ارسال پاسخ به کاربر
        await context.bot.send_message(
            chat_id=user_id,
            text=f"📬 پاسخ پشتیبانی:\n"
                 f"پیام شما: {original_message}\n\n"
                 f"📤 پاسخ ادمین: {admin_reply}"
        )
        
        await update.message.reply_text("✅ پاسخ با موفقیت ارسال شد!")
    
    except Exception as e:
        logger.error(f"خطا در پردازش پاسخ: {str(e)}")
        await update.message.reply_text("⚠️ خطایی در ارسال پاسخ رخ داد!")
    
    return ConversationHandler.END

# ============================
# تنظیمات اجرایی
# ============================
app = Flask(__name__)

@app.route(f"/{TOKEN}", methods=["POST"])
def webhook():
    update = Update.de_json(request.get_json(), application.bot)
    application.update_queue.put(update)
    return "OK", 200

if __name__ == "__main__":
    application = Application.builder().token(TOKEN).build()
    
    # مکالمه پشتیبانی
    support_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex(f"^{BTN_SUPPORT}$"), support_start)],
        states={
            SUPPORT: [MessageHandler(filters.TEXT & ~filters.COMMAND, support_message)]
        },
        fallbacks=[CommandHandler("cancel", lambda update, context: ConversationHandler.END)],
        per_user=True
    )
    
    # مکالمه پاسخ ادمین
    admin_reply_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(handle_admin_reply, pattern=r"^reply_")],
        states={
            ADMIN_REPLY: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_admin_reply)]
        },
        fallbacks=[CommandHandler("cancel", lambda update, context: ConversationHandler.END)],
        per_user=True
    )
    
    application.add_handler(support_conv)
    application.add_handler(admin_reply_conv)
    
    application.run_webhook(
        listen="0.0.0.0",
        port=int(os.environ.get("PORT", 8443)),
        webhook_url=WEBHOOK_URL,
        url_path=TOKEN,
        secret_token="YOUR_SECRET_TOKEN"
    )
