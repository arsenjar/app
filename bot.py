"""
TaskFlow Telegram bot.
Shares tasks.db with server.py → every change in bot or Mini App is instantly visible in the other.

Commands:
  /start, /help   — welcome & command list
  /app            — open Mini App (calendar, full UI)
  /today          — tasks due today + undated
  /week           — tasks due in the next 7 days
  /all            — all pending tasks
  /done <id>      — mark task done
  /del <id>       — delete task
  any text        — creates a new task (dates auto-parsed)
"""
import logging
import os
from datetime import datetime, timedelta

from dotenv import load_dotenv
from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    MenuButtonWebApp,
    Update,
    WebAppInfo,
)
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

import db
from parser import parse_task

load_dotenv()
BOT_TOKEN = os.environ["BOT_TOKEN"]
WEBAPP_URL = os.environ.get("WEBAPP_URL", "").rstrip("/")

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
)
log = logging.getLogger("taskflow")

TYPE_EMOJI = {"task": "📌", "deadline": "🔴", "meeting": "🟣"}


# ── Formatting ───────────────────────────────────────────────────────────

def fmt(t: dict) -> str:
    emoji = TYPE_EMOJI.get(t["type"], "📌")
    check = "✅ " if t["done"] else ""
    due = ""
    if t["due_at"]:
        try:
            dt = datetime.fromisoformat(t["due_at"])
            due = f"  ⏰ {dt.strftime('%d %b %H:%M')}"
        except ValueError:
            pass
    return f"{check}{emoji} [#{t['id']}] {t['text']}{due}"


def render_list(tasks: list[dict], header: str) -> str:
    if not tasks:
        return f"{header}\n\n_Пусто_"
    return header + "\n\n" + "\n".join(fmt(t) for t in tasks)


def webapp_button(text: str = "📅 Открыть планнер") -> InlineKeyboardMarkup | None:
    if not WEBAPP_URL:
        return None
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton(text, web_app=WebAppInfo(url=WEBAPP_URL))]]
    )


# ── Handlers ─────────────────────────────────────────────────────────────

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = (
        "👋 *TaskFlow* — планировщик\n\n"
        "Просто пришли мне любой текст — я сохраню его как задачу.\n"
        "Даты распознаются автоматически: _«позвонить Алексу завтра в 15:00»_\n\n"
        "*Команды:*\n"
        "/app — открыть мини-приложение\n"
        "/today — задачи на сегодня\n"
        "/week — ближайшие 7 дней\n"
        "/all — все задачи\n"
        "/done <id> — отметить выполненной\n"
        "/del <id> — удалить"
    )
    kb = webapp_button()
    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=kb)


async def cmd_app(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    kb = webapp_button("📅 Открыть планнер")
    if not kb:
        await update.message.reply_text(
            "⚠️ Мини-приложение не настроено. Укажи WEBAPP_URL в .env и перезапусти бота."
        )
        return
    await update.message.reply_text("Нажми кнопку, чтобы открыть планировщик:", reply_markup=kb)


async def cmd_today(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    today = datetime.now().date()
    tasks = [
        t for t in db.list_tasks(uid)
        if not t["done"] and (
            (t["due_at"] and datetime.fromisoformat(t["due_at"]).date() == today)
            or not t["due_at"]
        )
    ]
    await update.message.reply_text(render_list(tasks, "📅 *Сегодня*"), parse_mode="Markdown")


async def cmd_week(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    now = datetime.now()
    end = now + timedelta(days=7)
    tasks = [
        t for t in db.list_tasks(uid)
        if not t["done"] and t["due_at"]
        and now <= datetime.fromisoformat(t["due_at"]) <= end
    ]
    await update.message.reply_text(render_list(tasks, "📅 *Ближайшие 7 дней*"), parse_mode="Markdown")


async def cmd_all(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    tasks = [t for t in db.list_tasks(uid) if not t["done"]]
    await update.message.reply_text(render_list(tasks, "📋 *Все задачи*"), parse_mode="Markdown")


async def cmd_done(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not ctx.args or not ctx.args[0].isdigit():
        await update.message.reply_text("Использование: /done <id>")
        return
    task_id = int(ctx.args[0])
    if db.update_task(uid, task_id, done=1):
        await update.message.reply_text(f"✅ #{task_id} выполнено!")
    else:
        await update.message.reply_text("Задача не найдена.")


async def cmd_del(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not ctx.args or not ctx.args[0].isdigit():
        await update.message.reply_text("Использование: /del <id>")
        return
    task_id = int(ctx.args[0])
    if db.delete_task(uid, task_id):
        await update.message.reply_text(f"🗑 #{task_id} удалено.")
    else:
        await update.message.reply_text("Задача не найдена.")


# ── Create task via plain text ──────────────────────────────────────────

async def on_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    raw = (update.message.text or "").strip()
    if not raw:
        return

    parsed = parse_task(raw)
    due_iso = parsed["due_at"].strftime("%Y-%m-%dT%H:%M") if parsed["due_at"] else None
    task = db.create_task(
        user_id=uid,
        text=parsed["text"],
        task_type=parsed["task_type"],
        due_at=due_iso,
        duration=parsed["duration_min"],
    )

    emoji = TYPE_EMOJI.get(task["type"], "📌")
    due_str = ""
    if task["due_at"]:
        due_str = f"\n⏰ Когда: {datetime.fromisoformat(task['due_at']).strftime('%d %b %Y %H:%M')}"
    msg = f"{emoji} Добавлено #{task['id']}: *{task['text']}*{due_str}"

    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Готово", callback_data=f"done:{task['id']}"),
            InlineKeyboardButton("🗑 Удалить", callback_data=f"del:{task['id']}"),
        ]
    ])
    await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=kb)


async def on_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    action, _, sid = q.data.partition(":")
    if not sid.isdigit():
        return
    task_id = int(sid)

    if action == "done":
        db.update_task(uid, task_id, done=1)
        await q.edit_message_reply_markup(reply_markup=None)
        await q.message.reply_text(f"✅ #{task_id} выполнено!")
    elif action == "del":
        db.delete_task(uid, task_id)
        await q.edit_message_reply_markup(reply_markup=None)
        await q.message.reply_text(f"🗑 #{task_id} удалено.")


# ── Reminder background job ─────────────────────────────────────────────

async def reminder_tick(ctx: ContextTypes.DEFAULT_TYPE):
    for t in db.due_within(minutes=30):
        try:
            dt = datetime.fromisoformat(t["due_at"])
            mins = max(0, int((dt - datetime.now()).total_seconds() // 60))
            emoji = TYPE_EMOJI.get(t["type"], "📌")
            await ctx.bot.send_message(
                t["user_id"],
                f"⏰ Напоминание: {emoji} *{t['text']}* через ~{mins} мин",
                parse_mode="Markdown",
            )
            db.mark_reminded(t["id"])
        except Exception as e:
            log.warning("reminder send failed for #%s: %s", t["id"], e)


# ── Post-init: set menu button to Mini App ──────────────────────────────

async def on_startup(app: Application):
    if WEBAPP_URL:
        try:
            await app.bot.set_chat_menu_button(
                menu_button=MenuButtonWebApp(text="📅 Планнер", web_app=WebAppInfo(url=WEBAPP_URL))
            )
            log.info("Menu button set to Mini App: %s", WEBAPP_URL)
        except Exception as e:
            log.warning("Could not set menu button: %s", e)


# ── Main ─────────────────────────────────────────────────────────────────

def main():
    db.init_db()
    app = Application.builder().token(BOT_TOKEN).post_init(on_startup).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_start))
    app.add_handler(CommandHandler("app", cmd_app))
    app.add_handler(CommandHandler("today", cmd_today))
    app.add_handler(CommandHandler("week", cmd_week))
    app.add_handler(CommandHandler("all", cmd_all))
    app.add_handler(CommandHandler("done", cmd_done))
    app.add_handler(CommandHandler("del", cmd_del))
    app.add_handler(CallbackQueryHandler(on_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))

    app.job_queue.run_repeating(reminder_tick, interval=120, first=15)

    log.info("Bot started. Mini App URL: %s", WEBAPP_URL or "(not set)")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
