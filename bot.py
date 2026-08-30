import os
import re
import tempfile
from pathlib import Path

import fitz  # PyMuPDF
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    ContextTypes,
    filters,
)

BOT_TOKEN = os.environ.get("BOT_TOKEN")
AUTHOR = "@Tarikhgan"

WAITING_FOR_NAME = 1


def safe_filename(name: str) -> str:
    name = name.strip()

    if name.lower().endswith(".pdf"):
        name = name[:-4].strip()

    name = re.sub(r'[<>:"/\\|?*]', '', name)
    name = name.rstrip(" .")

    return name or "Untitled"


def change_metadata(input_path: str, output_path: str, title: str):
    doc = fitz.open(input_path)

    metadata = doc.metadata
    metadata["title"] = title
    metadata["author"] = AUTHOR
    metadata["subject"] = ""

    doc.set_metadata(metadata)

    doc.save(
        output_path,
        garbage=4,
        deflate=True,
    )

    doc.close()


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()

    keyboard = [
        [
            InlineKeyboardButton(
                "📚 فایل‌های من",
                callback_data="list_files"
            )
        ]
    ]

    await update.message.reply_text(
        "سلام 👋\n\n"
        "PDFهای خودت را برای من بفرست.\n"
        "می‌توانی چند فایل پشت سر هم ارسال کنی.\n\n"
        "بعد از ارسال، روی «فایل‌های من» بزن.",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def receive_pdf(update: Update, context: ContextTypes.DEFAULT_TYPE):
    document = update.message.document

    if not document.file_name.lower().endswith(".pdf"):
        await update.message.reply_text(
            "❌ فقط فایل PDF قبول می‌کنم."
        )
        return

    files = context.user_data.setdefault("files", [])

    # file_id در خود تلگرام ذخیره می‌شود
    files.append({
        "file_id": document.file_id,
        "name": document.file_name,
    })

    await update.message.reply_text(
        f"✅ دریافت شد:\n{document.file_name}\n\n"
        f"تعداد فایل‌های فعلی: {len(files)}",
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "📚 فایل‌های من",
                    callback_data="list_files"
                )
            ]
        ]),
    )


async def list_files(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    files = context.user_data.get("files", [])

    if not files:
        await query.edit_message_text(
            "📭 هنوز فایلی ارسال نکرده‌ای."
        )
        return

    keyboard = []

    for i, file_info in enumerate(files):
        keyboard.append([
            InlineKeyboardButton(
                f"{i + 1}️⃣ {file_info['name']}",
                callback_data=f"select:{i}"
            )
        ])

    await query.edit_message_text(
        "📚 فایل‌های شما:\n\n"
        "برای تغییر نام، روی فایل موردنظر بزن:",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def select_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    index = int(query.data.split(":")[1])

    files = context.user_data.get("files", [])

    if index >= len(files):
        await query.edit_message_text("❌ فایل پیدا نشد.")
        return

    context.user_data["selected_index"] = index

    file_name = files[index]["name"]

    keyboard = [
        [
            InlineKeyboardButton(
                "✏️ تغییر نام",
                callback_data="rename"
            )
        ],
        [
            InlineKeyboardButton(
                "📤 ارسال فایل",
                callback_data="send"
            )
        ],
        [
            InlineKeyboardButton(
                "🗑 حذف از لیست",
                callback_data="delete"
            )
        ],
        [
            InlineKeyboardButton(
                "⬅️ بازگشت",
                callback_data="list_files"
            )
        ],
    ]

    await query.edit_message_text(
        f"📄 فایل انتخاب‌شده:\n\n"
        f"{file_name}",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def rename_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    index = context.user_data.get("selected_index")

    if index is None:
        await query.edit_message_text("❌ ابتدا یک فایل انتخاب کن.")
        return ConversationHandler.END

    files = context.user_data.get("files", [])

    if index >= len(files):
        await query.edit_message_text("❌ فایل پیدا نشد.")
        return ConversationHandler.END

    await query.edit_message_text(
        "✏️ نام جدید فایل را ارسال کن.\n\n"
        "مثال:\n"
        "تاریخ ایران باستان\n\n"
        "لازم نیست .pdf را بنویسی."
    )

    return WAITING_FOR_NAME


async def receive_new_name(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    new_name = safe_filename(update.message.text)

    index = context.user_data.get("selected_index")
    files = context.user_data.get("files", [])

    if index is None or index >= len(files):
        await update.message.reply_text("❌ فایل پیدا نشد.")
        return ConversationHandler.END

    file_info = files[index]

    await update.message.reply_text(
        "⏳ در حال تغییر نام و Metadata فایل..."
    )

    telegram_file = await context.bot.get_file(
        file_info["file_id"]
    )

    with tempfile.TemporaryDirectory() as temp_dir:

        original_path = Path(temp_dir) / "original.pdf"
        output_path = Path(temp_dir) / f"{new_name}.pdf"

        await telegram_file.download_to_drive(
            custom_path=str(original_path)
        )

        change_metadata(
            str(original_path),
            str(output_path),
            new_name,
        )

        await update.message.reply_document(
            document=str(output_path),
            caption=(
                f"📄 {new_name}.pdf\n\n"
                f"Title: {new_name}\n"
                f"Author: {AUTHOR}\n"
                f"Subject: خالی"
            ),
        )

    # نام جدید فقط در لیست ربات ذخیره می‌شود
    file_info["name"] = f"{new_name}.pdf"

    await update.message.reply_text(
        "✅ انجام شد.\n\n"
        "فایل موقت بلافاصله حذف شد."
    )

    return ConversationHandler.END


async def send_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    index = context.user_data.get("selected_index")
    files = context.user_data.get("files", [])

    if index is None or index >= len(files):
        await query.edit_message_text("❌ فایل پیدا نشد.")
        return

    file_info = files[index]

    await query.message.reply_document(
        document=file_info["file_id"],
        caption=f"📄 {file_info['name']}",
    )


async def delete_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    index = context.user_data.get("selected_index")
    files = context.user_data.get("files", [])

    if index is None or index >= len(files):
        await query.edit_message_text("❌ فایل پیدا نشد.")
        return

    deleted = files.pop(index)

    context.user_data.pop("selected_index", None)

    await query.edit_message_text(
        f"🗑 حذف شد:\n{deleted['name']}",
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "📚 فایل‌های من",
                    callback_data="list_files"
                )
            ]
        ]),
    )


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.pop("selected_index", None)

    await update.message.reply_text(
        "❌ عملیات لغو شد."
    )

    return ConversationHandler.END


def main():
    if not BOT_TOKEN:
        raise RuntimeError(
            "BOT_TOKEN environment variable is missing."
        )

    app = Application.builder().token(BOT_TOKEN).build()

    rename_conversation = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(
                rename_request,
                pattern="^rename$"
            )
        ],
        states={
            WAITING_FOR_NAME: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    receive_new_name
                )
            ]
        },
        fallbacks=[
            CommandHandler("cancel", cancel)
        ],
    )

    app.add_handler(CommandHandler("start", start))

    app.add_handler(
        MessageHandler(
            filters.Document.PDF,
            receive_pdf
        )
    )

    app.add_handler(rename_conversation)

    app.add_handler(
        CallbackQueryHandler(
            list_files,
            pattern="^list_files$"
        )
    )

    app.add_handler(
        CallbackQueryHandler(
            select_file,
            pattern="^select:"
        )
    )

    app.add_handler(
        CallbackQueryHandler(
            send_file,
            pattern="^send$"
        )
    )

    app.add_handler(
        CallbackQueryHandler(
            delete_file,
            pattern="^delete$"
        )
    )

    print("Bot is running...")

    app.run_polling()


if __name__ == "__main__":
    main()
