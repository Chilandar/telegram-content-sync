"""
اسکریپت اصلی انتقال محتوا از تلگرام به روبیکا (پشتیبانی از چند کانال مبدا/مقصد)

کارش:
1. لیست جفت‌های «کانال مبدا تلگرام → کانال مقصد روبیکا» رو از تنظیمات می‌خونه
2. برای هر جفت، آخرین شناسه‌ی پیام پردازش‌شده رو جدا نگه می‌داره
3. پیام‌های جدید هر کانال مبدا رو می‌خونه و به همون کانال مقصدش می‌فرسته
4. شناسه‌ی آخرین پیام هر کانال رو دوباره ذخیره می‌کنه

نحوه‌ی تنظیم چند کانال:
    متغیر محیطی CHANNEL_MAPPINGS باید یه JSON از این شکل باشه:
    [
      {"source": -1001969747781, "destination": "c0BE58O0069ec7e2a03509bc849a5095"},
      {
        "source": -1009999999999,
        "destination": "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
        "strip_links": true,
        "own_tag": "🏛️ @Tarikhgan"
      }
    ]

    strip_links (اختیاری، پیش‌فرض false): اگه true باشه، همه‌ی لینک‌ها و منشن‌های
    یوزرنیم (@something) از متن پیام حذف می‌شن.
    own_tag (اختیاری): اگه بذاری، بعد از پاک‌سازی، این متن به انتهای پیام اضافه می‌شه
    (مثلاً برای جایگزین‌کردن آیدی حذف‌شده با آیدی خودت).

نحوه‌ی اجرا:
    python bridge.py
"""

import asyncio
import os
import json
import base64
import re
from telethon import TelegramClient
from telethon.sessions import StringSession
from rubpy import Client as RubikaClient

# --- رفع باگ rubpy: الگوی بولد/ایتالیک و... اصلی روی متن‌های چندخطی کار نمی‌کنه ---
import rubpy.parser.markdown as _rubpy_markdown

_rubpy_markdown.MARKDOWN_RE = re.compile(
    r"(?:^(?:> ?[^\n]*\n?)+)"
    r"|```([\s\S]*?)```"
    r"|\*\*([\s\S]+?)\*\*"
    r"|`([^\n`]+?)`"
    r"|__([\s\S]+?)__"
    r"|--([\s\S]+?)--"
    r"|~~([\s\S]+?)~~"
    r"|\|\|([\s\S]+?)\|\|"
    r"|\[([^\]]+?)\]\((\S+)\)",
    flags=re.DOTALL | re.MULTILINE,
)

# --- تنظیمات تلگرام ---
TG_API_ID = int(os.environ.get("TG_API_ID"))
TG_API_HASH = os.environ.get("TG_API_HASH")

# --- تنظیمات روبیکا ---
RUBIKA_SESSION_NAME = "rubika_session"

# --- لیست جفت‌های مبدا/مقصد ---
CHANNEL_MAPPINGS = json.loads(os.environ.get("CHANNEL_MAPPINGS", "[]"))

LAST_IDS_FILE = "last_ids.json"
FAIL_COUNT_FILE = "fail_counts.json"
MAX_ATTEMPTS = 3


def get_tg_session_string():
    env_value = os.environ.get("TG_SESSION")
    if env_value:
        return env_value.strip()
    with open("session.txt", "r") as f:
        return f.read().strip()


def prepare_rubika_session_file():
    b64_value = os.environ.get("RUBIKA_SESSION_B64")
    if b64_value:
        session_bytes = base64.b64decode(b64_value)
        with open(f"{RUBIKA_SESSION_NAME}.rp", "wb") as f:
            f.write(session_bytes)


def load_last_ids():
    """دیکشنری {شناسه‌ی کانال مبدا: آخرین شناسه‌ی پیام پردازش‌شده}"""
    if os.path.exists(LAST_IDS_FILE):
        with open(LAST_IDS_FILE, "r") as f:
            content = f.read().strip()
            if content:
                return {int(k): v for k, v in json.loads(content).items()}
    return {}


def save_last_ids(last_ids):
    with open(LAST_IDS_FILE, "w") as f:
        json.dump({str(k): v for k, v in last_ids.items()}, f)


def load_fail_counts():
    """دیکشنری {"source_channel:message_id": تعداد شکست}"""
    if os.path.exists(FAIL_COUNT_FILE):
        with open(FAIL_COUNT_FILE, "r") as f:
            content = f.read().strip()
            if content:
                return json.loads(content)
    return {}


def save_fail_counts(counts):
    with open(FAIL_COUNT_FILE, "w") as f:
        json.dump(counts, f)


async def handle_poll(tg_client, rubika_client, message, destination_guid):
    """نظرسنجی/کوییز تلگرام رو می‌خونه و روی روبیکا دوباره می‌سازه."""

    def plain_text(value):
        return getattr(value, "text", value)

    tg_poll = message.poll.poll
    question = plain_text(tg_poll.question)
    answers = tg_poll.answers
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
            destination_guid,
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
            destination_guid,
            question=question,
            options=options,
            type="Regular",
        )


def get_download_target(message, default_name):
    original_name = message.file.name if message.file else None
    if original_name:
        return original_name
    ext = message.file.ext if message.file and message.file.ext else ""
    return f"{default_name}{ext}"


def clean_caption(text, mapping):
    """اگه mapping بخواد، لینک/آیدی/منشن و متن‌های دلخواه رو از متن حذف می‌کنه و آیدی خودمون رو جایگزین می‌کنه."""
    remove_texts = mapping.get("remove_texts") or []
    strip_links = mapping.get("strip_links", False)

    if not strip_links and not remove_texts:
        return text

    if strip_links:
        # حذف لینک‌های تلگرام، روبیکا و هر لینک http/https دیگه
        text = re.sub(r"https?://\S+", "", text)
        text = re.sub(r"t\.me/\S+", "", text)
        # حذف منشن‌های یوزرنیم (مثلاً @channel_name)
        text = re.sub(r"@[\w\d_]+", "", text)

    # حذف متن‌های دقیقی که خودت مشخص کردی (هر تعداد که بخوای)
    for phrase in remove_texts:
        text = text.replace(phrase, "")

    # پاک‌کردن فاصله‌های اضافی که از حذف‌ها باقی می‌مونه
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = text.strip()

    own_tag = mapping.get("own_tag")
    if own_tag:
        text = f"{text}\n\n{own_tag}" if text else own_tag

    return text


async def process_message(tg_client, rubika_client, message, destination_guid, mapping):
    """یک پیام رو بر اساس نوعش به کانال مقصد روبیکا می‌فرسته."""
    caption = clean_caption(message.text or "", mapping)

    if message.poll:
        await handle_poll(tg_client, rubika_client, message, destination_guid)

    elif message.photo:
        file_path = await tg_client.download_media(message, file=get_download_target(message, "photo.jpg"))
        await rubika_client.send_message(
            destination_guid, caption, file_inline=file_path, type="Image", parse_mode="markdown",
        )
        os.remove(file_path)

    elif message.video:
        file_path = await tg_client.download_media(message, file=get_download_target(message, "video.mp4"))
        await rubika_client.send_video(destination_guid, file_path, caption=caption, parse_mode="markdown")
        os.remove(file_path)

    elif message.gif:
        file_path = await tg_client.download_media(message, file=get_download_target(message, "gif.mp4"))
        await rubika_client.send_gif(destination_guid, file_path, caption=caption, parse_mode="markdown")
        os.remove(file_path)

    elif message.voice:
        file_path = await tg_client.download_media(message, file=get_download_target(message, "voice.ogg"))
        await rubika_client.send_voice(destination_guid, file_path, caption=caption, parse_mode="markdown")
        os.remove(file_path)

    elif message.sticker:
        print(f"پیام {message.id} استیکر است — انتقال استیکر فعلاً پشتیبانی نمی‌شود، رد شد.")

    elif message.document:
        file_path = await tg_client.download_media(message, file=get_download_target(message, "file"))
        await rubika_client.send_document(destination_guid, file_path, caption=caption, parse_mode="markdown")
        os.remove(file_path)

    elif caption:
        await rubika_client.send_message(destination_guid, caption, parse_mode="markdown")

    else:
        print(f"پیام {message.id} نوع ناشناخته یا خالی — رد شد.")


async def process_mapping(tg_client, rubika_client, mapping, last_ids, fail_counts):
    source_channel = int(mapping["source"])
    destination_guid = mapping["destination"]
    last_id = last_ids.get(source_channel, 0)
    print(f"\n=== کانال {source_channel} → {destination_guid} (آخرین شناسه: {last_id}) ===")

    new_messages = []
    async for message in tg_client.iter_messages(source_channel, min_id=last_id):
        new_messages.append(message)
    new_messages.reverse()

    if not new_messages:
        print("پیام جدیدی برای انتقال نیست.")
        return

    for message in new_messages:
        key = f"{source_channel}:{message.id}"
        print(f"در حال پردازش پیام {message.id} ...")

        try:
            await process_message(tg_client, rubika_client, message, destination_guid, mapping)
            last_ids[source_channel] = message.id
            save_last_ids(last_ids)
            fail_counts.pop(key, None)
            save_fail_counts(fail_counts)
            print(f"پیام {message.id} با موفقیت منتقل شد.")

        except Exception as e:
            attempts_so_far = fail_counts.get(key, 0) + 1
            fail_counts[key] = attempts_so_far
            save_fail_counts(fail_counts)
            print(f"خطا در پردازش پیام {message.id} (تلاش {attempts_so_far}/{MAX_ATTEMPTS}): {e}")

            if attempts_so_far >= MAX_ATTEMPTS:
                print(f"پیام {message.id} بعد از {MAX_ATTEMPTS} تلاش ناموفق رد شد و پردازش ادامه پیدا می‌کند.")
                last_ids[source_channel] = message.id
                save_last_ids(last_ids)
                fail_counts.pop(key, None)
                save_fail_counts(fail_counts)
                continue
            else:
                break


async def main():
    if not CHANNEL_MAPPINGS:
        print("خطا: CHANNEL_MAPPINGS خالی یا تنظیم نشده است.")
        return

    prepare_rubika_session_file()
    tg_session_string = get_tg_session_string()

    tg_client = TelegramClient(StringSession(tg_session_string), TG_API_ID, TG_API_HASH)
    await tg_client.start()

    last_ids = load_last_ids()
    fail_counts = load_fail_counts()

    async with RubikaClient(name=RUBIKA_SESSION_NAME) as rubika_client:
        for mapping in CHANNEL_MAPPINGS:
            await process_mapping(tg_client, rubika_client, mapping, last_ids, fail_counts)

    await tg_client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
