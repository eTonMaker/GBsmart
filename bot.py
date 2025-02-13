import logging
import sqlite3
import random
import string
from dotenv import load_dotenv
load_dotenv()
import os
from datetime import datetime, timedelta
from flask import Flask, request
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
    ConversationHandler,
)

# ============================
# تنظیمات
# ============================
from dotenv import load_dotenv
load_dotenv()

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")  # استفاده از نام صحیح متغیر محیطی
if not TOKEN:
    raise ValueError("❌ توکن ربات در محیط تنظیم نشده است!")

WEBHOOK_URL = f"https://gbsmart-49kl.onrender.com/{TOKEN}"
CHANNELS = ["@smartmodircom", "@ershadsajadian"]
ADMINS = [992366512]

# تعریف حالت‌های مکالمه
# برای بخش پشتیبانی، دریافت کیف پول، پاسخ ادمین، تنظیم پاداش، تنظیم روزها و دریافت پاداش جدید
SUPPORT, WALLET_ADDRESS, ADMIN_REPLY, SET_REWARD, SET_DAYS, RECEIVE_REWARD = range(6)

# متغیرهای دکمه (متنی)
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
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
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
# دستورات کاربران
# ============================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    telegram_id = user.id
    username = user.username or user.first_name

    # ثبت کاربر در پایگاه داده در صورت عدم ثبت
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

    # ساخت متن جهت دعوت به عضویت کانال‌ها
    channels_text = "لطفاً در کانال‌های زیر عضو شوید:\n"
    for chan in CHANNELS:
        channels_text += f"{chan} (https://t.me/{chan.lstrip('@')})\n"
    channels_text += "\nسپس دکمه زیر را فشار دهید:"
    
    # نمایش کیبورد با دکمه تایید عضویت
    reply_kb = [[BTN_VERIFY]]
    markup = ReplyKeyboardMarkup(reply_kb, resize_keyboard=True, one_time_keyboard=True)
    await update.message.reply_text(channels_text, reply_markup=markup)

async def verify_membership(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """بررسی عضویت کاربر در کانال‌ها و نمایش منوی اصلی در صورت تأیید"""
    user_id = update.message.from_user.id
    all_joined = True
    for channel in CHANNELS:
        try:
            member = await context.bot.get_chat_member(channel, user_id)
            if member.status not in ["member", "creator", "administrator"]:
                all_joined = False
                break
        except Exception as e:
            logger.error(f"خطای بررسی کانال: {e}")
            all_joined = False
    if all_joined:
        main_menu = [
            [BTN_INVITE, BTN_REFERRAL_LIST],
            [BTN_REWARD, BTN_SUPPORT]
        ]
        markup = ReplyKeyboardMarkup(main_menu, resize_keyboard=True)
        await update.message.reply_text("✅ عضویت تأیید شد! از منوی زیر انتخاب کنید:", reply_markup=markup)
    else:
        await update.message.reply_text("❌ هنوز در همه کانال‌ها عضو نشده‌اید!")

async def get_invite_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    referral_code = cursor.execute("SELECT referral_code FROM users WHERE telegram_id=?", (user_id,)).fetchone()[0]
    bot_username = (await context.bot.get_me()).username
    invite_link = f"https://t.me/{bot_username}?start={referral_code}"
    await update.message.reply_text(f"🔗 لینک دعوت شما:\n{invite_link}")

async def referral_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    total_ref = cursor.execute("SELECT COUNT(*) FROM referrals WHERE inviter_id=?", (user_id,)).fetchone()[0]
    days = int(cursor.execute("SELECT value FROM settings WHERE key='required_days'").fetchone()[0])
    active_ref = cursor.execute(f"""
        SELECT COUNT(*) 
        FROM referrals 
        WHERE inviter_id=? 
        AND julianday('now') - julianday(join_date) >= {days}
    """, (user_id,)).fetchone()[0]
    await update.message.reply_text(
        f"📊 لیست دعوت شدگان:\n\n"
        f"• کل دعوت شدگان: {total_ref}\n"
        f"• دعوت شدگان فعال ({days}+ روز): {active_ref}"
    )

# ============================
# بخش پاداش کاربری (با دکمه دریافت پاداش جدید)
# ============================
async def user_reward(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    days = int(cursor.execute("SELECT value FROM settings WHERE key='required_days'").fetchone()[0])
    active_ref = cursor.execute(f"""
        SELECT COUNT(*) 
        FROM referrals 
        WHERE inviter_id=? 
        AND julianday('now') - julianday(join_date) >= {days}
    """, (user_id,)).fetchone()[0]
    reward_per = int(cursor.execute("SELECT value FROM settings WHERE key='reward_per_user'").fetchone()[0])
    total_reward = active_ref * reward_per
    # ارسال کیبورد با دکمه "💳 دریافت پاداش"
    reply_kb = [[BTN_RECEIVE_REWARD]]
    markup = ReplyKeyboardMarkup(reply_kb, resize_keyboard=True, one_time_keyboard=True)
    await update.message.reply_text(
         f"💰 پاداش شما:\n{total_reward} سکه\n\nبرای دریافت پاداش، لطفاً دکمه زیر را فشار دهید:",
         reply_markup=markup
    )
    return RECEIVE_REWARD

async def receive_reward(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # پس از فشردن دکمه "💳 دریافت پاداش" درخواست آدرس کیف پول ارسال می‌شود
    await update.message.reply_text("لطفاً آدرس کیف پول خود را ارسال کنید:")
    return WALLET_ADDRESS

async def process_wallet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    wallet = update.message.text
    cursor.execute("UPDATE users SET wallet_address=? WHERE telegram_id=?", (wallet, user_id))
    conn.commit()
    await update.message.reply_text("✅ درخواست شما ثبت شد!")
    # نمایش مجدد منوی اصلی پس از اتمام مکالمه
    main_menu = [
        [BTN_INVITE, BTN_REFERRAL_LIST],
        [BTN_REWARD, BTN_SUPPORT]
    ]
    markup = ReplyKeyboardMarkup(main_menu, resize_keyboard=True)
    await update.message.reply_text("منوی اصلی:", reply_markup=markup)
    return ConversationHandler.END

# ============================
# بخش پشتیبانی
# ============================
async def support_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """شروع مکالمه پشتیبانی پس از فشردن دکمه پشتیبانی"""
    user_id = update.message.from_user.id
    # (اختیاری) بررسی عضویت در کانال‌ها
    all_joined = True
    for channel in CHANNELS:
        try:
            member = await context.bot.get_chat_member(channel, user_id)
            if member.status not in ["member", "creator", "administrator"]:
                all_joined = False
                break
        except Exception as e:
            logger.error(f"خطای بررسی کانال: {e}")
            all_joined = False
    if not all_joined:
        await update.message.reply_text("❌ برای استفاده از پشتیبانی باید در کانال‌ها عضو باشید!")
        return ConversationHandler.END
    await update.message.reply_text("📩 لطفاً پیام خود را وارد کنید (برای لغو /cancel):")
    return SUPPORT

async def support_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    message_text = update.message.text
    try:
        cursor.execute("INSERT INTO support (telegram_id, message) VALUES (?,?)", (user_id, message_text))
        conn.commit()
        support_id = cursor.lastrowid
        # ارسال پیام به ادمین‌ها جهت اطلاع‌رسانی (به صورت ساده)
        for admin in ADMINS:
            await context.bot.send_message(
                admin,
                f"🚨 پیام جدید پشتیبانی (ID: {support_id}):\nاز کاربر: {user_id}\nمتن پیام: {message_text}"
            )
        await update.message.reply_text("✅ پیام شما ثبت شد. پاسخ شما در اسرع وقت ارسال خواهد شد.")
    except Exception as e:
        logger.error(f"خطا در ثبت پیام پشتیبانی: {str(e)}")
        await update.message.reply_text("⛔ خطایی در ثبت پیام رخ داد!")
    return ConversationHandler.END

# ============================
# پنل ادمین (بدون تغییر قابل توجه)
# ============================
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMINS:
        return
    admin_menu = [
        ["👥 تعداد اعضا", "📩 پیام‌های پشتیبانی"],
        ["✅ چک کردن اعضا", "🎁 لیست پاداش‌ها"],
        ["💰 تنظیم پاداش", "📆 تنظیم روزهای لازم"],
        ["📊 آمار دعوت‌ها"]
    ]
    markup = ReplyKeyboardMarkup(admin_menu, resize_keyboard=True)
    await update.message.reply_text("🛠 پنل مدیریت ادمین:", reply_markup=markup)

# تابع نمایش تعداد اعضای ثبت‌شده
async def admin_members_count(update: Update, context: ContextTypes.DEFAULT_TYPE):
    count = cursor.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    await update.message.reply_text(f"👥 تعداد کل اعضا: {count} نفر")

# تابع نمایش پیام‌های پشتیبانی (پیام‌هایی که هنوز پاسخی دریافت نکرده‌اند)
async def admin_support_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    messages = cursor.execute("SELECT id, telegram_id, message FROM support WHERE reply IS NULL").fetchall()
    if not messages:
        await update.message.reply_text("⚠️ هیچ پیام پشتیبانی ثبت نشده است!")
    else:
        text = "📩 پیام‌های پشتیبانی:\n"
        for msg in messages:
            text += f"ID: {msg[0]} | کاربر: {msg[1]} | پیام: {msg[2]}\n"
        await update.message.reply_text(text)

# تابع بررسی اعضای فعال (بر اساس تعداد روز مورد نیاز)
async def admin_check_members(update: Update, context: ContextTypes.DEFAULT_TYPE):
    days = int(cursor.execute("SELECT value FROM settings WHERE key='required_days'").fetchone()[0])
    active_users = cursor.execute(f"""
        SELECT inviter_id, COUNT(*) 
        FROM referrals 
        WHERE julianday('now') - julianday(join_date) >= {days}
        GROUP BY inviter_id
    """).fetchall()
    if not active_users:
        await update.message.reply_text("⚠️ هیچ عضو فعالی یافت نشد!")
    else:
        text = "✅ گزارش اعضای فعال:\n"
        for user in active_users:
            text += f"کاربر {user[0]}: {user[1]} عضو فعال\n"
        await update.message.reply_text(text)

# تابع نمایش لیست درخواست‌های پاداش
async def admin_reward_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rewards = cursor.execute("""
        SELECT u.username, r.amount 
        FROM reward_requests r
        JOIN users u ON r.user_id = u.telegram_id
        WHERE r.status='pending'
    """).fetchall()
    if not rewards:
        await update.message.reply_text("⚠️ هیچ درخواست پاداشی وجود ندارد!")
    else:
        text = "🎁 لیست درخواست‌های پاداش:\n"
        for reward in rewards:
            text += f"{reward[0]}: {reward[1]} سکه\n"
        await update.message.reply_text(text)

# تابع درخواست تنظیم مقدار پاداش (تنظیم پاداش برای هر دعوت)
async def admin_set_reward(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("💰 مقدار جدید پاداش برای هر دعوت را وارد کنید:")

# تابع درخواست تنظیم تعداد روزهای لازم برای فعال شدن دعوت
async def admin_set_required_days(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📆 تعداد روزهای لازم را وارد کنید:")

# تابع نمایش آمار کلی دعوت‌ها
async def admin_referral_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    total_users = cursor.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    active_users = cursor.execute("SELECT COUNT(*) FROM referrals WHERE julianday('now') - julianday(join_date) >= 30").fetchone()[0]
    await update.message.reply_text(f"📊 آمار کلی:\n• کل کاربران: {total_users}\n• کاربران فعال (30+ روز): {active_users}")

# افزودن Handlerها برای دکمه‌های ادمین
# (این Handlerها باید در بخش ثبت handlerهای application در برنامه اصلی اضافه شوند)
application.add_handler(MessageHandler(filters.Regex("^👥 تعداد اعضا$"), admin_members_count))
application.add_handler(MessageHandler(filters.Regex("^📩 پیام‌های پشتیبانی$"), admin_support_messages))
application.add_handler(MessageHandler(filters.Regex("^✅ چک کردن اعضا$"), admin_check_members))
application.add_handler(MessageHandler(filters.Regex("^🎁 لیست پاداش‌ها$"), admin_reward_list))
application.add_handler(MessageHandler(filters.Regex("^💰 تنظیم پاداش$"), admin_set_reward))
application.add_handler(MessageHandler(filters.Regex("^📆 تنظیم روزهای لازم$"), admin_set_required_days))
application.add_handler(MessageHandler(filters.Regex("^📊 آمار دعوت‌ها$"), admin_referral_stats))

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
    
    # دستورات اصلی کاربری
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.Regex(f"^{BTN_VERIFY}$"), verify_membership))
    application.add_handler(MessageHandler(filters.Regex(f"^{BTN_INVITE}$"), get_invite_link))
    application.add_handler(MessageHandler(filters.Regex(f"^{BTN_REFERRAL_LIST}$"), referral_list))
    
    reward_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex(f"^{BTN_REWARD}$"), user_reward)],
        states={
            RECEIVE_REWARD: [MessageHandler(filters.Regex(f"^{BTN_RECEIVE_REWARD}$"), receive_reward)],
            WALLET_ADDRESS: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_wallet)]
        },
        fallbacks=[CommandHandler("cancel", lambda update, context: ConversationHandler.END)],
        per_user=True
    )
    application.add_handler(reward_conv)
    
    support_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex(f"^{BTN_SUPPORT}$"), support_start)],
        states={
            SUPPORT: [MessageHandler(filters.TEXT & ~filters.COMMAND, support_message)]
        },
        fallbacks=[CommandHandler("cancel", lambda update, context: ConversationHandler.END)],
        per_user=True
    )
    application.add_handler(support_conv)
    
    # دستورات ادمین
    application.add_handler(CommandHandler("admin", admin_panel))
    application.add_handler(CommandHandler("reply", reply_to_support))
    
    application.run_webhook(
        listen="0.0.0.0",
        port=int(os.environ.get("PORT", 8443)),
        webhook_url=WEBHOOK_URL,
        url_path=TOKEN,
        secret_token="YOUR_SECRET_TOKEN"
    )
