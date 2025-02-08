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

# توکن ربات (توکن دریافتی از BotFather)
TOKEN = "7482034609:AAFK9VBVIc2UUoAXD2KFpJxSEVAdZl1uefI"  # حتماً این قسمت را با توکن واقعی جایگزین کنید

# لیست کانال‌ها (شناسه یا یوزرنیم کانال‌ها، به صورت @yourchannel)
CHANNELS = ["@yourchannel1", "@yourchannel2"]

# لیست ایدی‌های ادمین (به عنوان مثال)
ADMINS = [992366512]  # شناسه‌های واقعی ادمین را وارد کنید

# تنظیمات لاگ
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# ============================
# پایگاه داده (SQLite)
# ============================

# اتصال به پایگاه داده (فایل bot_database.db در همان مسیر)
conn = sqlite3.connect("bot_database.db", check_same_thread=False)
cursor = conn.cursor()


def init_db():
    # جدول کاربران
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            telegram_id INTEGER PRIMARY KEY,
            username TEXT,
            referral_code TEXT UNIQUE,
            inviter_id INTEGER,
            join_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            wallet_address TEXT
        )
        """
    )
    # جدول دعوت‌ها
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS referrals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            inviter_id INTEGER,
            invited_id INTEGER,
            join_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            verified INTEGER DEFAULT 0,
            verified_date TIMESTAMP,
            reward_claimed INTEGER DEFAULT 0
        )
        """
    )
    # جدول تنظیمات
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
        """
    )
    # جدول پشتیبانی
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS support (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id INTEGER,
            message TEXT,
            reply TEXT,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    # مقداردهی اولیه به تنظیمات (در صورت نبود مقدار قبلی)
    cursor.execute(
        "INSERT OR IGNORE INTO settings (key, value) VALUES (?,?)",
        ("reward_per_user", "10"),
    )
    cursor.execute(
        "INSERT OR IGNORE INTO settings (key, value) VALUES (?,?)",
        ("required_days", "30"),
    )
    conn.commit()


def generate_referral_code(length=6):
    """تولید کد دعوت تصادفی"""
    return "".join(random.choices(string.ascii_uppercase + string.digits, k=length))


# ============================
# حالات مکالمه (Conversation States)
# ============================
SUPPORT_MESSAGE, WALLET_INPUT = range(2)

# برای ذخیره‌سازی عملیات ادمین (مثلاً تنظیم پاداش یا روز)
admin_operation = {}

# ============================
# دستورات و هندلرهای ربات
# ============================

# /start : ثبت کاربر جدید، بررسی پارامتر دعوت و نمایش دکمه‌های عضویت در کانال‌ها
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
            cursor.execute(
                "SELECT telegram_id FROM users WHERE referral_code=?", (inviter_code,)
            )
            inviter = cursor.fetchone()
            if inviter:
                inviter_id = inviter[0]
        cursor.execute(
            "INSERT INTO users (telegram_id, username, referral_code, inviter_id) VALUES (?,?,?,?)",
            (telegram_id, username, referral_code, inviter_id),
        )
        conn.commit()
        # اگر دعوت‌کننده وجود داشته باشد، رکورد دعوت ثبت می‌شود
        if inviter_id:
            cursor.execute(
                "INSERT INTO referrals (inviter_id, invited_id) VALUES (?,?)",
                (inviter_id, telegram_id),
            )
            conn.commit()

    # نمایش پیام خوشامدگویی و دکمه‌های عضویت در کانال‌ها
    join_keyboard = [
        [
            InlineKeyboardButton(
                "عضویت در کانال شماره 1",
                url=f"https://t.me/{CHANNELS[0].lstrip('@')}",
            )
        ],
        [
            InlineKeyboardButton(
                "عضویت در کانال شماره 2",
                url=f"https://t.me/{CHANNELS[1].lstrip('@')}",
            )
        ],
        [InlineKeyboardButton("تایید عضویت در کانال‌ها", callback_data="check_channels")],
    ]
    reply_markup = InlineKeyboardMarkup(join_keyboard)
    await update.message.reply_text(
        "لطفاً ابتدا در کانال‌های زیر عضو شوید و سپس روی تایید عضویت کلیک کنید:",
        reply_markup=reply_markup,
    )


# بررسی عضویت کاربر در کانال‌ها
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


# نمایش لیست دعوت‌ها
async def referral_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    telegram_id = query.from_user.id
    cursor.execute("SELECT COUNT(*) FROM referrals WHERE inviter_id=?", (telegram_id,))
    total_invited = cursor.fetchone()[0]
    cursor.execute(
        "SELECT COUNT(*) FROM referrals WHERE inviter_id=? AND verified=1", (telegram_id,)
    )
    valid_invited = cursor.fetchone()[0]
    await query.answer()
    await query.message.reply_text(
        f"تعداد دعوت شدگان: {total_invited}\nتعداد دعوت شدگان معتبر (۳۰ روز): {valid_invited}"
    )


# نمایش اطلاعات پاداش کاربر
async def reward_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    telegram_id = query.from_user.id
    cursor.execute("SELECT value FROM settings WHERE key='reward_per_user'")
    reward_per_user = float(cursor.fetchone()[0])
    cursor.execute(
        "SELECT COUNT(*) FROM referrals WHERE inviter_id=? AND verified=1", (telegram_id,)
    )
    valid_invited = cursor.fetchone()[0]
    total_reward = valid_invited * reward_per_user
    keyboard = [[InlineKeyboardButton("دریافت پاداش", callback_data="claim_reward")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.answer()
    await query.message.reply_text(
        f"پاداش شما: {total_reward} تون کوین", reply_markup=reply_markup
    )


# درخواست دریافت پاداش (کاربر باید آدرس کیف پول خود را وارد کند)
async def claim_reward(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.message.reply_text("لطفاً آدرس کیف پول خود را وارد کنید:")
    return WALLET_INPUT  # رفتن به حالت دریافت آدرس کیف پول


# دریافت و ثبت آدرس کیف پول
async def wallet_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_id = update.message.from_user.id
    wallet_address = update.message.text.strip()
    # در اینجا می‌توانید اعتبارسنجی آدرس کیف پول را اضافه کنید
    cursor.execute(
        "UPDATE users SET wallet_address=? WHERE telegram_id=?",
        (wallet_address, telegram_id),
    )
    conn.commit()
    await update.message.reply_text(
        "آدرس کیف پول ثبت شد. پاداش شما به زودی واریز خواهد شد."
    )
    return ConversationHandler.END


# درخواست پیام پشتیبانی
async def support_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.message.reply_text("لطفاً پیام خود را برای پشتیبانی ارسال کنید:")
    return SUPPORT_MESSAGE  # رفتن به حالت دریافت پیام پشتیبانی


# دریافت پیام پشتیبانی از کاربر
async def support_message_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_id = update.message.from_user.id
    message_text = update.message.text
    cursor.execute(
        "INSERT INTO support (telegram_id, message) VALUES (?,?)",
        (telegram_id, message_text),
    )
    conn.commit()
    # ارسال پیام به ادمین‌ها
    for admin_id in ADMINS:
        try:
            await context.bot.send_message(
                admin_id,
                f"پیام پشتیبانی از کاربر {telegram_id}:\n{message_text}",
            )
        except Exception as e:
            logger.error(f"خطا در ارسال پیام پشتیبانی به ادمین {admin_id}: {e}")
    await update.message.reply_text(
        "پیام شما ارسال شد. پشتیبانی به زودی با شما تماس خواهد گرفت."
    )
    return ConversationHandler.END


# هندلر لغو (برای مواقعی که کاربر یا ادمین عملیات را لغو کند)
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("عملیات لغو شد.")
    return ConversationHandler.END


# ============================
# پنل ادمین
# ============================

# دستور /admin برای نمایش منوی ادمین
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.id not in ADMINS:
        await update.message.reply_text("شما اجازه دسترسی به پنل ادمین را ندارید.")
        return
    keyboard = [
        [InlineKeyboardButton("تعداد اعضا", callback_data="admin_total_users")],
        [InlineKeyboardButton("پاسخ به پیام اعضا", callback_data="admin_support")],
        [InlineKeyboardButton("چک کردن اعضا", callback_data="admin_check_user")],
        [InlineKeyboardButton("لیست کاربران برای پاداش", callback_data="admin_reward_list")],
        [InlineKeyboardButton("تنظیم میزان پاداش برای هر نفر", callback_data="admin_set_reward")],
        [InlineKeyboardButton("تنظیم تعداد روز", callback_data="admin_set_days")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("پنل ادمین:", reply_markup=reply_markup)


# نمایش تعداد کل اعضا
async def admin_total_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    cursor.execute("SELECT COUNT(*) FROM users")
    total_users = cursor.fetchone()[0]
    await query.answer()
    await query.message.reply_text(f"تعداد اعضا: {total_users}")


# برای تنظیم میزان پاداش و تعداد روز (ورودی از ادمین گرفته می‌شود)
async def admin_set_reward_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.message.reply_text("لطفاً میزان پاداش برای هر نفر را وارد کنید:")
    admin_operation[query.from_user.id] = "set_reward"
    return 1


async def admin_set_days_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.message.reply_text("لطفاً تعداد روز مورد نیاز برای تایید عضویت را وارد کنید:")
    admin_operation[query.from_user.id] = "set_days"
    return 1


# هندلر ورودی‌های متنی ادمین برای تنظیم مقادیر یا جستجوی کاربر
async def admin_input_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    operation = admin_operation.get(user_id)
    if operation == "set_reward":
        try:
            new_reward = float(update.message.text.strip())
            cursor.execute(
                "UPDATE settings SET value=? WHERE key='reward_per_user'",
                (str(new_reward),),
            )
            conn.commit()
            await update.message.reply_text(f"میزان پاداش برای هر نفر به {new_reward} تغییر کرد.")
        except ValueError:
            await update.message.reply_text("مقدار وارد شده صحیح نیست.")
    elif operation == "set_days":
        try:
            new_days = int(update.message.text.strip())
            cursor.execute(
                "UPDATE settings SET value=? WHERE key='required_days'",
                (str(new_days),),
            )
            conn.commit()
            await update.message.reply_text(f"تعداد روز مورد نیاز به {new_days} تغییر کرد.")
        except ValueError:
            await update.message.reply_text("مقدار وارد شده صحیح نیست.")
    elif operation == "check_user":
        # جستجوی کاربر بر اساس آیدی یا نام کاربری
        identifier = update.message.text.strip()
        cursor.execute(
            "SELECT telegram_id, username, referral_code, inviter_id FROM users WHERE telegram_id=? OR username=?",
            (identifier, identifier),
        )
        user_data = cursor.fetchone()
        if user_data:
            telegram_id, username, referral_code, inviter_id = user_data
            cursor.execute(
                "SELECT COUNT(*), SUM(verified) FROM referrals WHERE inviter_id=?",
                (telegram_id,),
            )
            data = cursor.fetchone()
            total_invites = data[0] if data[0] else 0
            valid_invites = data[1] if data[1] else 0
            await update.message.reply_text(
                f"کاربر: {username} (ID: {telegram_id})\nکد دعوت: {referral_code}\nدعوت شدگان: {total_invites}\nدعوت شدگان معتبر: {valid_invites}"
            )
        else:
            await update.message.reply_text("کاربر مورد نظر یافت نشد.")
    admin_operation.pop(user_id, None)
    return ConversationHandler.END


# درخواست جستجوی کاربر توسط ادمین
async def admin_check_user_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.message.reply_text("لطفاً نام کاربری یا آیدی کاربر را وارد کنید:")
    admin_operation[query.from_user.id] = "check_user"
    return 1


# نمایش لیست کاربران و تعداد دعوت‌های معتبر آن‌ها (برای پاداش)
async def admin_reward_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    cursor.execute(
        """
        SELECT u.telegram_id, u.username,
        (SELECT COUNT(*) FROM referrals WHERE inviter_id=u.telegram_id AND verified=1) as valid_count
        FROM users u
        """
    )
    rows = cursor.fetchall()
    message_text = "لیست کاربران و تعداد دعوت‌های معتبر:\n"
    for row in rows:
        telegram_id, username, valid_count = row
        message_text += f"{username} (ID: {telegram_id}): {valid_count}\n"
    await query.answer()
    await query.message.reply_text(message_text)


# ============================
# وظیفه زمان‌بندی شده برای بررسی دعوت‌ها (۳۰ روز)
# ============================

async def check_referrals_job(context: ContextTypes.DEFAULT_TYPE):
    # دریافت تعداد روز مورد نیاز از تنظیمات
    cursor.execute("SELECT value FROM settings WHERE key='required_days'")
    required_days = int(cursor.fetchone()[0])
    now = datetime.datetime.now()
    cursor.execute(
        "SELECT id, invited_id, join_date, verified FROM referrals WHERE verified=0"
    )
    rows = cursor.fetchall()
    for row in rows:
        ref_id, invited_id, join_date_str, verified = row
        join_date = datetime.datetime.strptime(join_date_str, "%Y-%m-%d %H:%M:%S")
        diff = now - join_date
        if diff.days >= required_days:
            # بررسی عضویت دعوت‌شونده در تمامی کانال‌ها
            all_joined = True
            for channel in CHANNELS:
                try:
                    member = await context.bot.get_chat_member(channel, invited_id)
                    if member.status not in ["member", "creator", "administrator"]:
                        all_joined = False
                        break
                except Exception as e:
                    logger.error(f"خطا در بررسی عضویت {invited_id} در {channel}: {e}")
                    all_joined = False
                    break
            if all_joined:
                # به‌روزرسانی وضعیت دعوت به عنوان معتبر
                cursor.execute(
                    "UPDATE referrals SET verified=1, verified_date=? WHERE id=?",
                    (now.strftime("%Y-%m-%d %H:%M:%S"), ref_id),
                )
                conn.commit()


# ============================
# راه‌اندازی ربات
# ============================

def main():
    init_db()

    application = Application.builder().token(TOKEN).build()

    # ثبت هندلرهای دستورات
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("admin", admin_panel))

    # هندلرهای CallbackQuery برای منوی اصلی
    application.add_handler(CallbackQueryHandler(check_channels, pattern="^check_channels$"))
    application.add_handler(CallbackQueryHandler(referral_link, pattern="^referral_link$"))
    application.add_handler(CallbackQueryHandler(referral_list, pattern="^referral_list$"))
    application.add_handler(CallbackQueryHandler(reward_info, pattern="^reward_info$"))
    application.add_handler(CallbackQueryHandler(claim_reward, pattern="^claim_reward$"))
    application.add_handler(CallbackQueryHandler(support_request, pattern="^support$"))

    # هندلرهای CallbackQuery مربوط به پنل ادمین
    application.add_handler(CallbackQueryHandler(admin_total_users, pattern="^admin_total_users$"))
    application.add_handler(CallbackQueryHandler(admin_reward_list, pattern="^admin_reward_list$"))
    application.add_handler(CallbackQueryHandler(admin_set_reward_prompt, pattern="^admin_set_reward$"))
    application.add_handler(CallbackQueryHandler(admin_set_days_prompt, pattern="^admin_set_days$"))
    application.add_handler(CallbackQueryHandler(admin_check_user_prompt, pattern="^admin_check_user$"))

    # ConversationHandler برای دریافت آدرس کیف پول (در حالت دریافت پاداش)
    conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(claim_reward, pattern="^claim_reward$")],
        states={
            WALLET_INPUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, wallet_received)]
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    application.add_handler(conv_handler)

    # ConversationHandler برای دریافت پیام پشتیبانی
    support_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(support_request, pattern="^support$")],
        states={
            SUPPORT_MESSAGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, support_message_received)]
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    application.add_handler(support_conv)

    # ConversationHandler برای ورودی‌های ادمین (تنظیم پاداش، روز، یا جستجوی کاربر)
    admin_conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(admin_set_reward_prompt, pattern="^admin_set_reward$"),
            CallbackQueryHandler(admin_set_days_prompt, pattern="^admin_set_days$"),
            CallbackQueryHandler(admin_check_user_prompt, pattern="^admin_check_user$")
        ],
        states={
            1: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_input_handler)]
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    application.add_handler(admin_conv)

    # زمان‌بندی وظیفه بررسی دعوت‌ها (هر ساعت یکبار)
    job_queue = application.job_queue
    job_queue.run_repeating(check_referrals_job, interval=3600, first=10)

    # شروع ربات (حالت polling)
   


if __name__ == "__main__":
    main()

import os
from flask import Flask, request
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters

TOKEN = os.getenv("TOKEN")  # دریافت توکن از متغیر محیطی
WEBHOOK_URL = os.getenv("WEBHOOK_URL")  # لینک وبهوک روی Render
PORT = int(os.getenv("PORT", 5000))  # پورت اجرا

app = Flask(__name__)

application = Application.builder().token(TOKEN).build()

async def start(update: Update, context):
    await update.message.reply_text("سلام! ربات فعال است.")

application.add_handler(CommandHandler("start", start))

@app.route(f"/{TOKEN}", methods=["POST"])
def webhook():
    """این تابع درخواست‌های ورودی تلگرام را پردازش می‌کند"""
    update = Update.de_json(request.get_json(), application.bot)
    application.process_update(update)
    return "OK", 200

@app.route('/')
def home():
    return "Bot is running!", 200

if __name__ == "__main__":
    # تنظیم Webhook هنگام شروع برنامه
    application.bot.set_webhook(url=f"{WEBHOOK_URL}/{TOKEN}")
    
    # اجرای Flask
    app.run(host="0.0.0.0", port=PORT)

# اجرای سرور Flask
if __name__ == '__main__':
    app.run(host="0.0.0.0", port=PORT)

from flask import Flask, request
from telegram import Update
from telegram.ext import Application, CommandHandler

TOKEN = "7482034609:AAFK9VBVIc2UUoAXD2KFpJxSEVAdZl1uefI"
WEBHOOK_URL = "https://gbsmart-49kl.onrender.com"

app = Flask(__name__)

# مقداردهی bot
application = Application.builder().token(TOKEN).build()

@app.route("/", methods=["GET"])
def home():
    return "Bot is running!"

@app.route(f"/{TOKEN}", methods=["POST"])
def webhook():
    update = Update.de_json(request.get_json(), application.bot)
    application.process_update(update)
    return "OK", 200

def set_webhook():
    application.bot.set_webhook(url=f"{WEBHOOK_URL}/{TOKEN}")

if __name__ == "__main__":
    set_webhook()
    app.run(host="0.0.0.0", port=8080)

