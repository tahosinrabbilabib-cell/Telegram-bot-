import logging
import sqlite3
import random
import string
from datetime import datetime
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    ReplyKeyboardMarkup, KeyboardButton
)
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes, ConversationHandler
)

# ─────────────────────────────────────────
#  কনফিগারেশন
# ─────────────────────────────────────────
BOT_TOKEN   = "8781858328:AAEH0GF30AAy_bFQu0XXN33KAWnHlr3uc68"
ADMIN_ID    = 6280694247

MIN_WITHDRAW      = 100      # সর্বনিম্ন উত্তোলন (টাকা)
REFERRAL_BONUS    = 20       # রেফার বোনাস (টাকা)
TASK_REWARD       = {        # টাস্ক রিওয়ার্ড
    "instagram": 15,
    "gmail":     10,
    "facebook":  12,
}

# ConversationHandler states
(WITHDRAW_METHOD, WITHDRAW_ACCOUNT, WITHDRAW_AMOUNT,
 SUPPORT_MSG) = range(4)

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ─────────────────────────────────────────
#  ডেটাবেজ সেটআপ
# ─────────────────────────────────────────
def init_db():
    conn = sqlite3.connect("earning_bot.db")
    c = conn.cursor()
    c.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            user_id     INTEGER PRIMARY KEY,
            username    TEXT,
            full_name   TEXT,
            balance     REAL    DEFAULT 0,
            total_earned REAL   DEFAULT 0,
            refer_code  TEXT    UNIQUE,
            referred_by INTEGER DEFAULT NULL,
            joined_at   TEXT
        );

        CREATE TABLE IF NOT EXISTS tasks (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     INTEGER,
            task_type   TEXT,
            reward      REAL,
            status      TEXT    DEFAULT 'pending',
            done_at     TEXT
        );

        CREATE TABLE IF NOT EXISTS withdrawals (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     INTEGER,
            method      TEXT,
            account     TEXT,
            amount      REAL,
            status      TEXT    DEFAULT 'pending',
            requested_at TEXT
        );

        CREATE TABLE IF NOT EXISTS referrals (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            referrer_id INTEGER,
            referred_id INTEGER,
            bonus       REAL,
            created_at  TEXT
        );
    """)
    conn.commit()
    conn.close()

def get_conn():
    return sqlite3.connect("earning_bot.db")

# ─────────────────────────────────────────
#  ইউজার হেল্পার
# ─────────────────────────────────────────
def generate_refer_code(user_id: int) -> str:
    suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=5))
    return f"REF{user_id}{suffix}"

def get_or_create_user(user_id: int, username: str, full_name: str,
                       referred_by: int = None) -> dict:
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE user_id=?", (user_id,))
    row = c.fetchone()
    if row:
        conn.close()
        return dict(zip(
            ["user_id","username","full_name","balance","total_earned",
             "refer_code","referred_by","joined_at"], row
        ))

    refer_code = generate_refer_code(user_id)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    c.execute(
        "INSERT INTO users VALUES (?,?,?,0,0,?,?,?)",
        (user_id, username, full_name, refer_code, referred_by, now)
    )

    # রেফার বোনাস
    if referred_by:
        c.execute("UPDATE users SET balance=balance+?, total_earned=total_earned+? WHERE user_id=?",
                  (REFERRAL_BONUS, REFERRAL_BONUS, referred_by))
        c.execute("INSERT INTO referrals VALUES (NULL,?,?,?,?)",
                  (referred_by, user_id, REFERRAL_BONUS, now))

    conn.commit()
    conn.close()

    return get_or_create_user(user_id, username, full_name)

def get_user(user_id: int) -> dict | None:
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE user_id=?", (user_id,))
    row = c.fetchone()
    conn.close()
    if not row:
        return None
    return dict(zip(
        ["user_id","username","full_name","balance","total_earned",
         "refer_code","referred_by","joined_at"], row
    ))

def update_balance(user_id: int, amount: float):
    conn = get_conn()
    c = conn.cursor()
    c.execute("UPDATE users SET balance=balance+?, total_earned=total_earned+? WHERE user_id=?",
              (amount, amount if amount > 0 else 0, user_id))
    conn.commit()
    conn.close()

def get_referral_list(user_id: int) -> list:
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        SELECT u.full_name, r.bonus, r.created_at
        FROM referrals r JOIN users u ON r.referred_id=u.user_id
        WHERE r.referrer_id=?
        ORDER BY r.created_at DESC
    """, (user_id,))
    rows = c.fetchall()
    conn.close()
    return rows

# ─────────────────────────────────────────
#  মেইন মেনু কীবোর্ড
# ─────────────────────────────────────────
def main_menu_keyboard():
    return ReplyKeyboardMarkup([
        [KeyboardButton("💼 কাজ করুন"), KeyboardButton("💰 ব্যালেন্স")],
        [KeyboardButton("🏦 টাকা উত্তোলন"), KeyboardButton("🖇️ My Referrals")],
        [KeyboardButton("🆘 সাপোর্ট")],
    ], resize_keyboard=True)

# ─────────────────────────────────────────
#  /start কমান্ড
# ─────────────────────────────────────────
async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user   = update.effective_user
    args   = ctx.args
    ref_by = None

    if args:
        conn = get_conn()
        c = conn.cursor()
        c.execute("SELECT user_id FROM users WHERE refer_code=?", (args[0],))
        row = c.fetchone()
        conn.close()
        if row and row[0] != user.id:
            ref_by = row[0]

    profile = get_or_create_user(user.id, user.username or "", user.full_name, ref_by)

    welcome = (
        f"🎉 *স্বাগতম, {user.first_name}!*\n\n"
        f"আপনি *GSM Earning Bot* এ যোগ দিয়েছেন।\n"
        f"টাস্ক করুন, রেফার করুন এবং টাকা আয় করুন! 💸\n\n"
        f"{'✅ রেফার বোনাস পেয়েছেন: ৳' + str(REFERRAL_BONUS) if ref_by else ''}"
    )

    await update.message.reply_text(
        welcome, parse_mode="Markdown",
        reply_markup=main_menu_keyboard()
    )

# ─────────────────────────────────────────
#  💼 কাজ সেকশন
# ─────────────────────────────────────────
async def show_tasks(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(f"📸 Instagram Task — ৳{TASK_REWARD['instagram']}", callback_data="task_instagram")],
        [InlineKeyboardButton(f"📧 Gmail Task — ৳{TASK_REWARD['gmail']}",          callback_data="task_gmail")],
        [InlineKeyboardButton(f"👥 Facebook Task — ৳{TASK_REWARD['facebook']}",    callback_data="task_facebook")],
    ])
    await update.message.reply_text(
        "💼 *কাজ বেছে নিন:*\n\nনিচের যেকোনো একটি টাস্ক সম্পন্ন করুন এবং রিওয়ার্ড পান।",
        parse_mode="Markdown", reply_markup=keyboard
    )

async def task_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query      = update.callback_query
    await query.answer()
    user_id    = query.from_user.id
    task_type  = query.data.replace("task_", "")
    reward     = TASK_REWARD[task_type]

    # প্রতিদিন একই টাস্ক সীমাবদ্ধ করুন
    conn = get_conn()
    c = conn.cursor()
    today = datetime.now().strftime("%Y-%m-%d")
    c.execute("""
        SELECT id FROM tasks
        WHERE user_id=? AND task_type=? AND status='completed'
        AND done_at LIKE ?
    """, (user_id, task_type, f"{today}%"))
    done_today = c.fetchone()
    conn.close()

    if done_today:
        await query.edit_message_text(
            f"⏳ আপনি আজকের *{task_type.capitalize()}* টাস্ক ইতিমধ্যে করেছেন।\n"
            "আগামীকাল আবার চেষ্টা করুন।",
            parse_mode="Markdown"
        )
        return

    task_instructions = {
        "instagram": (
            "📸 *Instagram Task*\n\n"
            "১. নিচের লিংকে যান এবং আমাদের পেজ Follow করুন\n"
            "২. একটি Story তে আমাদের মেনশন করুন\n"
            "৩. নিচের বাটনে ক্লিক করে রিওয়ার্ড নিন।\n\n"
            "👉 [Instagram Page](https://instagram.com)"
        ),
        "gmail": (
            "📧 *Gmail Task*\n\n"
            "১. নিচের ইমেইল এ একটি মেইল পাঠান\n"
            "২. Subject: 'GSM Bot Task'\n"
            "৩. সম্পন্ন হলে নিচের বাটনে ক্লিক করুন।\n\n"
            "📮 `support@gsmbot.com`"
        ),
        "facebook": (
            "👥 *Facebook Task*\n\n"
            "১. আমাদের Facebook পেজে Like দিন\n"
            "২. একটি পোস্ট Share করুন\n"
            "৩. নিচের বাটনে ক্লিক করে রিওয়ার্ড নিন।\n\n"
            "👉 [Facebook Page](https://facebook.com)"
        ),
    }

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(f"✅ টাস্ক সম্পন্ন — ৳{reward} নিন", callback_data=f"claim_{task_type}")],
        [InlineKeyboardButton("🔙 ফিরে যান", callback_data="back_tasks")],
    ])

    await query.edit_message_text(
        task_instructions[task_type],
        parse_mode="Markdown",
        reply_markup=keyboard,
        disable_web_page_preview=True
    )

async def claim_task(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query     = update.callback_query
    await query.answer()
    user_id   = query.from_user.id
    task_type = query.data.replace("claim_", "")
    reward    = TASK_REWARD[task_type]
    now       = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    conn = get_conn()
    c = conn.cursor()
    today = datetime.now().strftime("%Y-%m-%d")
    c.execute("""
        SELECT id FROM tasks
        WHERE user_id=? AND task_type=? AND status='completed'
        AND done_at LIKE ?
    """, (user_id, task_type, f"{today}%"))
    if c.fetchone():
        conn.close()
        await query.edit_message_text("⚠️ আপনি ইতিমধ্যে এই টাস্কের রিওয়ার্ড নিয়েছেন।")
        return

    c.execute("INSERT INTO tasks VALUES (NULL,?,?,?,'completed',?)",
              (user_id, task_type, reward, now))
    c.execute("UPDATE users SET balance=balance+?, total_earned=total_earned+? WHERE user_id=?",
              (reward, reward, user_id))
    conn.commit()
    conn.close()

    user = get_user(user_id)
    await query.edit_message_text(
        f"🎉 *অভিনন্দন!*\n\n"
        f"✅ *{task_type.capitalize()} Task* সম্পন্ন!\n"
        f"💰 আপনি ৳*{reward}* পেয়েছেন!\n\n"
        f"💼 বর্তমান ব্যালেন্স: ৳*{user['balance']:.2f}*",
        parse_mode="Markdown"
    )

    # অ্যাডমিনকে নোটিফাই
    await ctx.bot.send_message(
        ADMIN_ID,
        f"📋 *নতুন টাস্ক সম্পন্ন*\n"
        f"👤 {query.from_user.full_name} (`{user_id}`)\n"
        f"🔧 Task: {task_type}\n"
        f"💰 Reward: ৳{reward}",
        parse_mode="Markdown"
    )

async def back_tasks(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(f"📸 Instagram Task — ৳{TASK_REWARD['instagram']}", callback_data="task_instagram")],
        [InlineKeyboardButton(f"📧 Gmail Task — ৳{TASK_REWARD['gmail']}",          callback_data="task_gmail")],
        [InlineKeyboardButton(f"👥 Facebook Task — ৳{TASK_REWARD['facebook']}",    callback_data="task_facebook")],
    ])
    await query.edit_message_text(
        "💼 *কাজ বেছে নিন:*",
        parse_mode="Markdown", reply_markup=keyboard
    )

# ─────────────────────────────────────────
#  💰 ব্যালেন্স
# ─────────────────────────────────────────
async def show_balance(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user    = get_user(user_id)
    if not user:
        await update.message.reply_text("⚠️ প্রথমে /start দিন।")
        return

    # রেফার সংখ্যা
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM referrals WHERE referrer_id=?", (user_id,))
    ref_count = c.fetchone()[0]

    c.execute("SELECT COUNT(*), SUM(reward) FROM tasks WHERE user_id=? AND status='completed'", (user_id,))
    task_row = c.fetchone()
    conn.close()

    task_count  = task_row[0] or 0
    task_earned = task_row[1] or 0

    await update.message.reply_text(
        f"💰 *আপনার ব্যালেন্স*\n\n"
        f"┌─────────────────────\n"
        f"│ 💵 বর্তমান ব্যালেন্স: ৳*{user['balance']:.2f}*\n"
        f"│ 📈 মোট আয়: ৳*{user['total_earned']:.2f}*\n"
        f"│ 📋 টাস্ক সম্পন্ন: *{task_count}* টি\n"
        f"│ 💼 টাস্ক থেকে আয়: ৳*{task_earned:.2f}*\n"
        f"│ 🖇️ মোট রেফার: *{ref_count}* জন\n"
        f"└─────────────────────\n\n"
        f"🏦 সর্বনিম্ন উত্তোলন: ৳*{MIN_WITHDRAW}*",
        parse_mode="Markdown"
    )

# ─────────────────────────────────────────
#  🏦 টাকা উত্তোলন (Conversation)
# ─────────────────────────────────────────
async def withdraw_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user    = get_user(update.effective_user.id)
    if not user:
        await update.message.reply_text("⚠️ প্রথমে /start দিন।")
        return ConversationHandler.END

    if user["balance"] < MIN_WITHDRAW:
        await update.message.reply_text(
            f"❌ আপনার ব্যালেন্স ৳*{user['balance']:.2f}*\n"
            f"সর্বনিম্ন উত্তোলন: ৳*{MIN_WITHDRAW}*\n\n"
            "আরও কাজ করুন এবং পরে আবার চেষ্টা করুন।",
            parse_mode="Markdown"
        )
        return ConversationHandler.END

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📱 bKash",  callback_data="method_bkash")],
        [InlineKeyboardButton("💳 Nagad",  callback_data="method_nagad")],
        [InlineKeyboardButton("₿ USDT",    callback_data="method_usdt")],
        [InlineKeyboardButton("❌ বাতিল",  callback_data="method_cancel")],
    ])
    await update.message.reply_text(
        "🏦 *উত্তোলন পদ্ধতি বেছে নিন:*",
        parse_mode="Markdown", reply_markup=keyboard
    )
    return WITHDRAW_METHOD

async def withdraw_method(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "method_cancel":
        await query.edit_message_text("❌ উত্তোলন বাতিল করা হয়েছে।")
        return ConversationHandler.END

    ctx.user_data["withdraw_method"] = query.data.replace("method_", "").upper()
    labels = {"bkash": "bKash নম্বর", "nagad": "Nagad নম্বর", "usdt": "USDT ওয়ালেট ঠিকানা"}
    method_key = query.data.replace("method_", "")
    await query.edit_message_text(
        f"📝 আপনার *{ctx.user_data['withdraw_method']}* {labels[method_key]} লিখুন:",
        parse_mode="Markdown"
    )
    return WITHDRAW_ACCOUNT

async def withdraw_account(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["withdraw_account"] = update.message.text.strip()
    user = get_user(update.effective_user.id)
    await update.message.reply_text(
        f"💵 উত্তোলনের পরিমাণ লিখুন:\n"
        f"_(সর্বনিম্ন: ৳{MIN_WITHDRAW} | আপনার ব্যালেন্স: ৳{user['balance']:.2f})_",
        parse_mode="Markdown"
    )
    return WITHDRAW_AMOUNT

async def withdraw_amount(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user    = get_user(user_id)

    try:
        amount = float(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("⚠️ সঠিক পরিমাণ লিখুন।")
        return WITHDRAW_AMOUNT

    if amount < MIN_WITHDRAW:
        await update.message.reply_text(f"❌ সর্বনিম্ন উত্তোলন ৳{MIN_WITHDRAW}")
        return WITHDRAW_AMOUNT

    if amount > user["balance"]:
        await update.message.reply_text(
            f"❌ অপর্যাপ্ত ব্যালেন্স।\nআপনার ব্যালেন্স: ৳{user['balance']:.2f}"
        )
        return WITHDRAW_AMOUNT

    method  = ctx.user_data["withdraw_method"]
    account = ctx.user_data["withdraw_account"]
    now     = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    conn = get_conn()
    c = conn.cursor()
    c.execute("INSERT INTO withdrawals VALUES (NULL,?,?,?,?,'pending',?)",
              (user_id, method, account, amount, now))
    c.execute("UPDATE users SET balance=balance-? WHERE user_id=?", (amount, user_id))
    wid = c.lastrowid
    conn.commit()
    conn.close()

    await update.message.reply_text(
        f"✅ *উত্তোলন অনুরোধ পাঠানো হয়েছে!*\n\n"
        f"🔖 ID: `#{wid}`\n"
        f"💳 পদ্ধতি: *{method}*\n"
        f"📱 অ্যাকাউন্ট: `{account}`\n"
        f"💵 পরিমাণ: ৳*{amount:.2f}*\n\n"
        f"⏳ ২৪–৪৮ ঘণ্টার মধ্যে প্রক্রিয়া করা হবে।",
        parse_mode="Markdown",
        reply_markup=main_menu_keyboard()
    )

    # অ্যাডমিনকে নোটিফাই
    await ctx.bot.send_message(
        ADMIN_ID,
        f"🏦 *নতুন উত্তোলন অনুরোধ*\n"
        f"🔖 ID: `#{wid}`\n"
        f"👤 {update.effective_user.full_name} (`{user_id}`)\n"
        f"💳 পদ্ধতি: {method}\n"
        f"📱 অ্যাকাউন্ট: `{account}`\n"
        f"💵 পরিমাণ: ৳{amount:.2f}",
        parse_mode="Markdown"
    )
    return ConversationHandler.END

async def withdraw_cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "❌ উত্তোলন বাতিল করা হয়েছে।",
        reply_markup=main_menu_keyboard()
    )
    return ConversationHandler.END

# ─────────────────────────────────────────
#  🖇️ My Referrals
# ─────────────────────────────────────────
async def show_referrals(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user    = get_user(user_id)
    refs    = get_referral_list(user_id)

    bot_info = await ctx.bot.get_me()
    ref_link = f"https://t.me/{bot_info.username}?start={user['refer_code']}"

    ref_text = ""
    if refs:
        ref_text = "\n\n📋 *আপনার রেফার লিস্ট:*\n"
        for i, (name, bonus, date) in enumerate(refs[:10], 1):
            ref_text += f"{i}. {name} — ৳{bonus} ({date[:10]})\n"
    else:
        ref_text = "\n\n_এখনো কেউ আপনার লিংক দিয়ে জয়েন করেনি।_"

    await update.message.reply_text(
        f"🖇️ *My Referrals*\n\n"
        f"🔗 আপনার রেফার লিংক:\n`{ref_link}`\n\n"
        f"💰 প্রতি রেফারে বোনাস: ৳*{REFERRAL_BONUS}*\n"
        f"👥 মোট রেফার: *{len(refs)}* জন"
        f"{ref_text}",
        parse_mode="Markdown",
        disable_web_page_preview=True
    )

# ─────────────────────────────────────────
#  🆘 সাপোর্ট (Conversation)
# ─────────────────────────────────────────
async def support_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    cancel_kb = ReplyKeyboardMarkup(
        [[KeyboardButton("❌ বাতিল")]],
        resize_keyboard=True, one_time_keyboard=True
    )
    await update.message.reply_text(
        "🆘 *সাপোর্ট*\n\nআপনার সমস্যা বা প্রশ্ন লিখুন।\nআমরা শীঘ্রই উত্তর দেব।\n\n_বাতিল করতে ❌ বাতিল চাপুন।_",
        parse_mode="Markdown",
        reply_markup=cancel_kb
    )
    return SUPPORT_MSG

async def support_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "❌ বাতিল":
        await update.message.reply_text(
            "❌ বাতিল করা হয়েছে।",
            reply_markup=main_menu_keyboard()
        )
        return ConversationHandler.END

    user    = update.effective_user
    message = update.message.text

    await ctx.bot.send_message(
        ADMIN_ID,
        f"📩 *নতুন সাপোর্ট মেসেজ*\n\n"
        f"👤 {user.full_name} (`{user.id}`)\n"
        f"@{user.username or 'N/A'}\n\n"
        f"💬 {message}",
        parse_mode="Markdown"
    )

    await update.message.reply_text(
        "✅ *মেসেজ পাঠানো হয়েছে!*\n\nআমরা শীঘ্রই আপনার সাথে যোগাযোগ করব। ধন্যবাদ। 🙏",
        parse_mode="Markdown",
        reply_markup=main_menu_keyboard()
    )
    return ConversationHandler.END

# ─────────────────────────────────────────
#  🔐 অ্যাডমিন কমান্ড
# ─────────────────────────────────────────
def admin_only(func):
    async def wrapper(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if update.effective_user.id != ADMIN_ID:
            await update.message.reply_text("⛔ আপনি অ্যাডমিন নন।")
            return
        return await func(update, ctx)
    return wrapper

@admin_only
async def admin_stats(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT COUNT(*), SUM(balance), SUM(total_earned) FROM users")
    u = c.fetchone()
    c.execute("SELECT COUNT(*) FROM tasks WHERE status='completed'")
    t = c.fetchone()
    c.execute("SELECT COUNT(*), SUM(amount) FROM withdrawals WHERE status='pending'")
    w = c.fetchone()
    conn.close()

    await update.message.reply_text(
        f"📊 *অ্যাডমিন স্ট্যাটস*\n\n"
        f"👥 মোট ইউজার: *{u[0]}*\n"
        f"💰 মোট ব্যালেন্স: ৳*{(u[1] or 0):.2f}*\n"
        f"📈 মোট আয়: ৳*{(u[2] or 0):.2f}*\n"
        f"✅ মোট টাস্ক: *{t[0]}*\n"
        f"⏳ পেন্ডিং উত্তোলন: *{w[0]}* টি (৳{(w[1] or 0):.2f})",
        parse_mode="Markdown"
    )

@admin_only
async def admin_approve(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """ব্যবহার: /approve <withdrawal_id>"""
    args = ctx.args
    if not args:
        await update.message.reply_text("ব্যবহার: /approve <id>")
        return
    wid = args[0]
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT user_id, amount, method FROM withdrawals WHERE id=? AND status='pending'", (wid,))
    row = c.fetchone()
    if not row:
        conn.close()
        await update.message.reply_text("❌ অনুরোধ পাওয়া যায়নি বা ইতিমধ্যে প্রক্রিয়া করা হয়েছে।")
        return
    user_id, amount, method = row
    c.execute("UPDATE withdrawals SET status='approved' WHERE id=?", (wid,))
    conn.commit()
    conn.close()

    await update.message.reply_text(f"✅ #{wid} অনুমোদিত হয়েছে।")
    await ctx.bot.send_message(
        user_id,
        f"✅ *উত্তোলন অনুমোদিত!*\n\n"
        f"🔖 ID: `#{wid}`\n"
        f"💳 পদ্ধতি: {method}\n"
        f"💵 পরিমাণ: ৳{amount:.2f}\n\n"
        "শীঘ্রই আপনার অ্যাকাউন্টে পৌঁছাবে। 🎉",
        parse_mode="Markdown"
    )

@admin_only
async def admin_reject(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """ব্যবহার: /reject <withdrawal_id>"""
    args = ctx.args
    if not args:
        await update.message.reply_text("ব্যবহার: /reject <id>")
        return
    wid = args[0]
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT user_id, amount FROM withdrawals WHERE id=? AND status='pending'", (wid,))
    row = c.fetchone()
    if not row:
        conn.close()
        await update.message.reply_text("❌ অনুরোধ পাওয়া যায়নি।")
        return
    user_id, amount = row
    c.execute("UPDATE withdrawals SET status='rejected' WHERE id=?", (wid,))
    c.execute("UPDATE users SET balance=balance+? WHERE user_id=?", (amount, user_id))
    conn.commit()
    conn.close()

    await update.message.reply_text(f"❌ #{wid} বাতিল করা হয়েছে এবং ব্যালেন্স ফেরত দেওয়া হয়েছে।")
    await ctx.bot.send_message(
        user_id,
        f"❌ *উত্তোলন বাতিল*\n\n"
        f"🔖 ID: `#{wid}`\n"
        f"💵 ৳{amount:.2f} আপনার ব্যালেন্সে ফেরত দেওয়া হয়েছে।\n"
        "যেকোনো সমস্যায় সাপোর্টে যোগাযোগ করুন।",
        parse_mode="Markdown"
    )

@admin_only
async def admin_broadcast(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """ব্যবহার: /broadcast <বার্তা>"""
    if not ctx.args:
        await update.message.reply_text("ব্যবহার: /broadcast <বার্তা>")
        return
    msg = " ".join(ctx.args)
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT user_id FROM users")
    users = c.fetchall()
    conn.close()

    sent, failed = 0, 0
    for (uid,) in users:
        try:
            await ctx.bot.send_message(uid, f"📢 *অ্যাডমিন বার্তা:*\n\n{msg}", parse_mode="Markdown")
            sent += 1
        except Exception:
            failed += 1

    await update.message.reply_text(f"✅ পাঠানো: {sent} | ❌ ব্যর্থ: {failed}")

# ─────────────────────────────────────────
#  অজানা মেসেজ হ্যান্ডলার
# ─────────────────────────────────────────
async def unknown_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "💼 কাজ করুন":
        await show_tasks(update, ctx)
    elif text == "💰 ব্যালেন্স":
        await show_balance(update, ctx)
    elif text == "🖇️ My Referrals":
        await show_referrals(update, ctx)
    else:
        await update.message.reply_text(
            "⚠️ অজানা কমান্ড। নিচের মেনু ব্যবহার করুন।",
            reply_markup=main_menu_keyboard()
        )

# ─────────────────────────────────────────
#  মেইন ফাংশন
# ─────────────────────────────────────────
def main():
    init_db()
    logger.info("✅ বট চালু হচ্ছে...")

    app = Application.builder().token(BOT_TOKEN).build()

    # উত্তোলন ConversationHandler
    withdraw_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^🏦 টাকা উত্তোলন$"), withdraw_start)],
        states={
            WITHDRAW_METHOD:  [CallbackQueryHandler(withdraw_method, pattern="^method_")],
            WITHDRAW_ACCOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, withdraw_account)],
            WITHDRAW_AMOUNT:  [MessageHandler(filters.TEXT & ~filters.COMMAND, withdraw_amount)],
        },
        fallbacks=[
            CommandHandler("cancel", withdraw_cancel),
            MessageHandler(filters.Regex("^❌ বাতিল$"), withdraw_cancel),
        ],
    )

    # সাপোর্ট ConversationHandler
    support_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^🆘 সাপোর্ট$"), support_start)],
        states={
            SUPPORT_MSG: [MessageHandler(filters.TEXT & ~filters.COMMAND, support_message)],
        },
        fallbacks=[
            CommandHandler("cancel", withdraw_cancel),
            MessageHandler(filters.Regex("^❌ বাতিল$"), withdraw_cancel),
        ],
    )

    # হ্যান্ডলার রেজিস্ট্রেশন
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("stats", admin_stats))
    app.add_handler(CommandHandler("approve", admin_approve))
    app.add_handler(CommandHandler("reject", admin_reject))
    app.add_handler(CommandHandler("broadcast", admin_broadcast))

    app.add_handler(withdraw_conv)
    app.add_handler(support_conv)

    app.add_handler(MessageHandler(filters.Regex("^💼 কাজ করুন$"), show_tasks))
    app.add_handler(MessageHandler(filters.Regex("^💰 ব্যালেন্স$"), show_balance))
    app.add_handler(MessageHandler(filters.Regex("^🖇️ My Referrals$"), show_referrals))

    app.add_handler(CallbackQueryHandler(task_callback, pattern="^task_"))
    app.add_handler(CallbackQueryHandler(claim_task, pattern="^claim_"))
    app.add_handler(CallbackQueryHandler(back_tasks, pattern="^back_tasks$"))

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, unknown_message))

    logger.info("🚀 বট সফলভাবে চালু হয়েছে!")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
