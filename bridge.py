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
SOURCE_CHANNEL = int(os.environ.get("SOURCE_CHANNEL", "-1001969747781"))

# --- تنظیمات روبیکا ---
RUBIKA_SESSION_NAME = "rubika_session"
RUBIKA_CHANNEL_GUID = os.environ.get("RUBIKA_CHANNEL_GUID", "c0BE58O0069ec7e2a03509bc849a5095")

LAST_ID_FILE = "last_id.txt"
FAIL_COUNT_FILE = "fail_counts.txt"
MAX_ATTEMPTS = 3


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


def load_fail_counts():
    counts = {}
    if os.path.exists(FAIL_COUNT_FILE):
        with open(FAIL_COUNT_FILE, "r") as f:
            for line in f:
                line = line.strip()
                if line and ":" in line:
                    mid, cnt = line.split(":")
                    counts[int(mid)] = int(cnt)
    return counts


def save_fail_counts(counts):
    with open(FAIL_COUNT_FILE, "w") as f:
        for mid, cnt in counts.items():
            f.write(f"{mid}:{cnt}\n")


async def handle_poll(tg_client, rubika_client, message):
    """نظرسنجی/کوییز تلگرام رو می‌خونه و روی روبیکا دوباره می‌سازه."""

    def plain_text(value):
        """بعضی نسخه‌های تلگرام متن رو به‌صورت TextWithEntities برمی‌گردونن، نه رشته‌ی ساده."""
        return getattr(value, "text", value)

    tg_poll = message.poll.poll
    question = plain_text(tg_poll.question)
    answers = tg_poll.answers  # لیست PollAnswer با .text و .option (bytes)
    options = [plain_text(answer.text) for answer in answers]

    is_quiz = tg_poll.quiz
    correct_index = None
    explanation = None
    poll_results = message.poll.results

    def extract_correct_index(results):
        if not results or not results.results:
            return None, None
        option_to_index = {answer.option: idx for idx, answer in enumerate(answers)}
        for voter_result in results.results:
            if getattr(voter_result, "correct", False):
                idx = option_to_index.get(voter_result.option)
                sol = plain_text(getattr(results, "solution", None)) if getattr(results, "solution", None) else None
                return idx, sol
        return None, None

    if is_quiz:
        already_voted = bool(poll_results and poll_results.results and
                              any(getattr(r, "chosen", False) for r in poll_results.results))

        if already_voted:
            correct_index, explanation = extract_correct_index(poll_results)
        else:
            # هنوز رأی داده نشده — خودمون با گزینه‌ی اول رأی می‌دیم تا جواب درست آشکار بشه
            from telethon.tl.functions.messages import SendVoteRequest
            try:
                await tg_client(SendVoteRequest(
                    peer=message.peer_id,
                    msg_id=message.id,
                    options=[answers[0].option],
                ))
                await asyncio.sleep(2)
                refreshed = await tg_client.get_messages(message.peer_id, ids=message.id)
                correct_index, explanation = extract_correct_index(refreshed.poll.results)
            except Exception as vote_error:
                print(f"رأی خودکار روی کوییز {message.id} ناموفق بود: {vote_error}")

    if is_quiz and correct_index is not None:
        print(f"پیام {message.id} کوییز است — با گزینه‌ی درست شماره {correct_index} منتقل می‌شود.")
        await rubika_client.create_poll(
            RUBIKA_CHANNEL_GUID,
            question=question,
            options=options,
            type="Quiz",
            allows_multiple_answers=False,
            correct_option_index=correct_index,
            explanation=explanation or "",
        )
    else:
        if is_quiz:
            print(f"پیام {message.id} کوییز است ولی گزینه‌ی درست پیدا نشد — به‌صورت نظرسنجی معمولی منتقل می‌شود.")
        await rubika_client.create_poll(
            RUBIKA_CHANNEL_GUID,
            question=question,
            options=options,
            type="Regular",
        )


def get_download_target(message, default_name):
    """اسم اصلی فایل رو از پیام تلگرام می‌گیره؛ اگه نداشت، از یه اسم پیش‌فرض استفاده می‌کنه."""
    original_name = message.file.name if message.file else None
    if original_name:
        return original_name
    ext = message.file.ext if message.file and message.file.ext else ""
    return f"{default_name}{ext}"


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

        fail_counts = load_fail_counts()

        for message in new_messages:
            print(f"در حال پردازش پیام {message.id} ...")

            caption = message.text or ""
            print(f"متن خام پیام (برای بررسی): {caption!r}")

            try:
                if message.poll:
                    await handle_poll(tg_client, rubika_client, message)

                elif message.photo:
                    file_path = await tg_client.download_media(message, file=get_download_target(message, "photo.jpg"))
                    await rubika_client.send_message(
                        RUBIKA_CHANNEL_GUID,
                        caption,
                        file_inline=file_path,
                        type="Image",
                        parse_mode="markdown",
                    )
                    os.remove(file_path)

                elif message.video:
                    file_path = await tg_client.download_media(message, file=get_download_target(message, "video.mp4"))
                    await rubika_client.send_video(RUBIKA_CHANNEL_GUID, file_path, caption=caption, parse_mode="markdown")
                    os.remove(file_path)

                elif message.gif:
                    file_path = await tg_client.download_media(message, file=get_download_target(message, "gif.mp4"))
                    await rubika_client.send_gif(RUBIKA_CHANNEL_GUID, file_path, caption=caption, parse_mode="markdown")
                    os.remove(file_path)

                elif message.voice:
                    file_path = await tg_client.download_media(message, file=get_download_target(message, "voice.ogg"))
                    await rubika_client.send_voice(RUBIKA_CHANNEL_GUID, file_path, caption=caption, parse_mode="markdown")
                    os.remove(file_path)

                elif message.sticker:
                    # نگاشت استیکرهای تلگرام به استیکرهای روبیکا پیاده‌سازی نشده — فعلاً رد می‌شود
                    print(f"پیام {message.id} استیکر است — انتقال استیکر فعلاً پشتیبانی نمی‌شود، رد شد.")

                elif message.document:
                    # هر نوع فایل/سند دیگری که در دسته‌های بالا نبود
                    file_path = await tg_client.download_media(message, file=get_download_target(message, "file"))
                    await rubika_client.send_document(RUBIKA_CHANNEL_GUID, file_path, caption=caption, parse_mode="markdown")
                    os.remove(file_path)

                elif caption:
                    await rubika_client.send_message(RUBIKA_CHANNEL_GUID, caption, parse_mode="markdown")

                else:
                    print(f"پیام {message.id} نوع ناشناخته یا خالی — رد شد.")

                save_last_processed_id(message.id)
                fail_counts.pop(message.id, None)
                save_fail_counts(fail_counts)
                print(f"پیام {message.id} با موفقیت منتقل شد.")

            except Exception as e:
                attempts_so_far = fail_counts.get(message.id, 0) + 1
                fail_counts[message.id] = attempts_so_far
                save_fail_counts(fail_counts)
                print(f"خطا در پردازش پیام {message.id} (تلاش {attempts_so_far}/{MAX_ATTEMPTS}): {e}")

                if attempts_so_far >= MAX_ATTEMPTS:
                    print(f"پیام {message.id} بعد از {MAX_ATTEMPTS} تلاش ناموفق رد شد و پردازش ادامه پیدا می‌کند.")
                    save_last_processed_id(message.id)
                    fail_counts.pop(message.id, None)
                    save_fail_counts(fail_counts)
                    continue
                else:
                    # هنوز فرصت باقیه — این‌بار متوقف می‌شیم تا دفعه‌ی بعد دوباره امتحان بشه
                    break

    await tg_client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
