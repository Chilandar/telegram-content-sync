"""
اسکریپت اصلی انتقال محتوا از تلگرام به روبیکا

کارش:
1. آخرین شناسه‌ی پیام پردازش‌شده رو از فایل last_id.txt می‌خونه
2. پیام‌های جدیدتر از اون رو از کانال تلگرام می‌گیره
3. هر پیام رو (متن + عکس، اگه داشت) به کانال روبیکا می‌فرسته
4. شناسه‌ی آخرین پیام پردازش‌شده رو دوباره ذخیره می‌کنه

نحوه‌ی اجرا:
    python bridge.py

این اسکریپت رو می‌شه هر چند وقت یک‌بار (دستی یا با زمان‌بندی) اجرا کرد؛
هر بار فقط پیام‌های جدید از دفعه‌ی قبل رو منتقل می‌کنه.
"""

import asyncio
import os
import base64
from telethon import TelegramClient
from telethon.sessions import StringSession
from rubpy import Client as RubikaClient

# --- تنظیمات تلگرام ---
# اول از متغیر محیطی (GitHub Secrets) می‌خونه؛ اگه نبود، از فایل محلی
TG_API_ID = int(os.environ.get("TG_API_ID", "12345678"))
TG_API_HASH = os.environ.get("TG_API_HASH", "your_api_hash_here")
SOURCE_CHANNEL = -1001969747781  # شناسه‌ی عددی کانال منبع تلگرام

# --- تنظیمات روبیکا ---
RUBIKA_SESSION_NAME = "rubika_session"
RUBIKA_CHANNEL_GUID = "c0BE58O0069ec7e2a03509bc849a5095"

LAST_ID_FILE = "last_id.txt"


def get_tg_session_string():
    env_value = os.environ.get("TG_SESSION")
    if env_value:
        return env_value.strip()
    with open("session.txt", "r") as f:
        return f.read().strip()


def prepare_rubika_session_file():
    """اگه RUBIKA_SESSION_B64 توی محیط بود، فایل session روبیکا رو از روش می‌سازه."""
    b64_value = os.environ.get("RUBIKA_SESSION_B64")
    if b64_value:
        session_bytes = base64.b64decode(b64_value)
        with open(f"{RUBIKA_SESSION_NAME}.rp", "wb") as f:
            f.write(session_bytes)


def get_last_processed_id():
    if os.path.exists(LAST_ID_FILE):
        with open(LAST_ID_FILE, "r") as f:
            content = f.read().strip()
            if content:
                return int(content)
    return 0


def save_last_processed_id(message_id):
    with open(LAST_ID_FILE, "w") as f:
        f.write(str(message_id))


async def main():
    prepare_rubika_session_file()
    tg_session_string = get_tg_session_string()

    last_id = get_last_processed_id()
    print(f"آخرین شناسه‌ی پردازش‌شده: {last_id}")

    tg_client = TelegramClient(StringSession(tg_session_string), TG_API_ID, TG_API_HASH)
    await tg_client.start()

    async with RubikaClient(name=RUBIKA_SESSION_NAME) as rubika_client:
        # پیام‌های جدیدتر از last_id رو به ترتیب قدیم‌به‌جدید می‌گیریم
        new_messages = []
        async for message in tg_client.iter_messages(SOURCE_CHANNEL, min_id=last_id):
            new_messages.append(message)
        new_messages.reverse()  # قدیمی‌ترین اول پردازش بشه

        if not new_messages:
            print("پیام جدیدی برای انتقال نیست.")

        for message in new_messages:
            print(f"در حال پردازش پیام {message.id} ...")

            caption = message.text or ""

            try:
                if message.photo:
                    # دانلود عکس و ارسال آن با کپشن به روبیکا
                    file_path = await tg_client.download_media(message, file="temp_photo.jpg")
                    await rubika_client.send_message(
                        RUBIKA_CHANNEL_GUID,
                        caption,
                        file_inline=file_path,
                        type="Image",
                    )
                    os.remove(file_path)
                elif caption:
                    # پیام فقط متنی
                    await rubika_client.send_message(RUBIKA_CHANNEL_GUID, caption)
                else:
                    print(f"پیام {message.id} نه متن دارد نه عکس — رد شد (شاید نظرسنجی/ویدیو باشد).")

                save_last_processed_id(message.id)
                print(f"پیام {message.id} با موفقیت منتقل شد.")

            except Exception as e:
                print(f"خطا در پردازش پیام {message.id}: {e}")
                # چون خطا داده، last_id رو آپدیت نمی‌کنیم تا دفعه‌ی بعد دوباره امتحان بشه
                break

    await tg_client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
