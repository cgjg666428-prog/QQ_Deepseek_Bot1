import sqlite3
import json
import websocket
import requests
import os
from dotenv import load_dotenv
from openai import OpenAI
import random
import time
from douyin_video import get_video_url, start_video_reply
processed_message_ids = set()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"))

API_KEY = os.getenv("DEEPSEEK_API_KEY")

if not API_KEY:
    raise RuntimeError("没有找到 DeepSeek API Key，请检查 .env")

# =========================
# 配置
# =========================



# NapCat 当前登录的机器人 QQ 号
BOT_QQ = int(os.environ["BOT_QQ"])

NAPCAT_HTTP = os.getenv("NAPCAT_HTTP", "http://127.0.0.1:3000").rstrip("/")
NAPCAT_WS = os.getenv("NAPCAT_WS", "ws://127.0.0.1:3001")
NAPCAT_TOKEN = os.getenv("NAPCAT_TOKEN", "").strip()
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-flash")


def napcat_headers():
    return {"Authorization": f"Bearer {NAPCAT_TOKEN}"} if NAPCAT_TOKEN else {}


MAX_HISTORY = 10
# ===== Doo 随机插嘴设置 =====
RANDOM_REPLY_CHANCE = float(os.getenv("RANDOM_REPLY_CHANCE", "0"))  # 发布版默认关闭随机插嘴
RANDOM_REPLY_COOLDOWN = 20   # 同一个群至少间隔 20 秒

last_random_reply = {}
DB_PATH = os.path.join(BASE_DIR, "doo_memory.db")

SYSTEM_PROMPT = """你叫 Doo，是 QQ 聊天中的 AI 助手。日常回复简短自然；认真问题以准确和实用为先。
不辱骂、不羞辱用户，不编造记忆或图片内容。无法确认的信息应明确说明。
图片或视频抽帧只能描述实际可见内容，不能声称听到了未提供的音频。"""

client = OpenAI(
    api_key=API_KEY,
    base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
)


def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_key TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    conn.commit()
    conn.close()


init_db()

# =========================
# 对话记忆
# =========================

# key:
# private_用户QQ
# group_群号
#
# value:
# [{"role": "...", "content": "..."}]

def save_message(chat_key, role, content):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute(
        "INSERT INTO messages (chat_key, role, content) VALUES (?, ?, ?)",
        (chat_key, role, content)
    )

    conn.commit()
    conn.close()


def get_history(chat_key):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("""
        SELECT role, content
        FROM messages
        WHERE chat_key = ?
        ORDER BY id DESC
        LIMIT ?
    """, (chat_key, MAX_HISTORY))

    rows = cursor.fetchall()
    conn.close()

    rows.reverse()

    return [
        {"role": role, "content": content}
        for role, content in rows
    ]


def clear_history(chat_key):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute(
        "DELETE FROM messages WHERE chat_key = ?",
        (chat_key,)
    )

    conn.commit()
    conn.close()


# =========================
# DeepSeek
# =========================

def ask_deepseek(chat_key, text):

    save_message(chat_key, "user", text)

    history = get_history(chat_key)

    messages = [
        {
            "role": "system",
            "content": SYSTEM_PROMPT
        }
    ] + history

    print("正在请求 DeepSeek...")

    response = client.chat.completions.create(
        model=DEEPSEEK_MODEL,
        messages=messages
    )

    reply = response.choices[0].message.content

    save_message(chat_key, "assistant", reply)

    return reply


def ask_deepseek_with_image(chat_key, text, image_urls):

    if not text:
        text = "看看这张图。"

    content = [
        {
            "type": "text",
            "text": text
        }
    ]

    for image_url in image_urls:
        content.append(
            {
                "type": "image_url",
                "image_url": {
                    "url": image_url,
                    "detail": "low"
                }
            }
        )

    messages = [
        {
            "role": "system",
            "content": SYSTEM_PROMPT
        },
        {
            "role": "user",
            "content": content
        }
    ]

    print(f"正在让 Doo 看图，共 {len(image_urls)} 张...")

    response = client.chat.completions.create(
        model=DEEPSEEK_MODEL,
        messages=messages
    )

    reply = response.choices[0].message.content

    # 把图片对话以文字形式记进历史
    save_message(
        chat_key,
        "user",
        f"[用户发送了{len(image_urls)}张图片] {text}"
    )

    save_message(
        chat_key,
        "assistant",
        reply
    )

    return reply

# =========================
# NapCat 发送消息
# =========================

def send_private(user_id, text):

    response = requests.post(
        f"{NAPCAT_HTTP}/send_private_msg",
        json={
            "user_id": int(user_id),
            "message": text
        },
        headers=napcat_headers(),
        timeout=10
    )

    print("私聊发送结果：", response.text)


def send_group(group_id, text):

    response = requests.post(
        f"{NAPCAT_HTTP}/send_group_msg",
        json={
            "group_id": int(group_id),
            "message": text
        },
        headers=napcat_headers(),
        timeout=10
    )

    print("群聊发送结果：", response.text)




def should_random_reply(group_id):
    now = time.time()

    # 冷却时间检查
    last_time = last_random_reply.get(group_id, 0)

    if now - last_time < RANDOM_REPLY_COOLDOWN:
        return False

    # 随机概率检查
    if random.random() < RANDOM_REPLY_CHANCE:
        last_random_reply[group_id] = now
        return True

    return False




# =========================
# 判断是否 @机器人
# =========================

def is_at_bot(data):

    message = data.get("message", [])

    if not isinstance(message, list):
        return False

    for segment in message:

        if segment.get("type") == "at":

            qq = str(
                segment.get("data", {}).get("qq", "")
            )

            if qq == str(BOT_QQ):
                return True

    return False




def get_images(data):
    images = []

    message = data.get("message", [])

    if not isinstance(message, list):
        return images

    for segment in message:
        if segment.get("type") == "image":

            image_data = segment.get("data", {})

            image_url = image_data.get("url")

            if image_url:
                images.append(image_url)

    return images


# =========================
# 提取纯文本
# =========================

def get_text(data):

    message = data.get("message", [])

    # OneBot 消息段
    if isinstance(message, list):

        texts = []

        for segment in message:

            if segment.get("type") == "text":

                text = segment.get(
                    "data", {}
                ).get("text", "")

                texts.append(text)

        return "".join(texts).strip()

    # 兼容 raw_message
    return data.get(
        "raw_message", ""
    ).strip()


# =========================
# 收到 QQ 事件
# =========================

def on_message(ws, message):
    try:
        data = json.loads(message)

        # ===== 消息去重 =====
        message_id = data.get("message_id")

        if message_id is not None:
            if message_id in processed_message_ids:
                print(f"忽略重复消息：{message_id}")
                return

            processed_message_ids.add(message_id)

            if len(processed_message_ids) > 1000:
                processed_message_ids.clear()

        if data.get("post_type") != "message":
            return

        message_type = data.get("message_type")
        user_id = data.get("user_id")

        # ↓ 这里继续你原来的代码
        # 防止机器人处理自己发出的消息
        if str(user_id) == str(BOT_QQ):
            return

        # =====================
        # 私聊
        # =====================

        if message_type == "private":

            text = get_text(data)
            video_url = get_video_url(data, text)

            if not text and not video_url:
                return

            key = f"private_{user_id}"

            print(
                f"\n[私聊] {user_id}: {text}"
            )

            if text == "/clear":

                clear_history(key)

                send_private(
                    user_id,
                    "对话记忆已清空。"
                )

                return

            if video_url:
                start_video_reply(
                    key, text, video_url, ask_deepseek_with_image,
                    lambda reply: send_private(user_id, reply)
                )
                return

            reply = ask_deepseek(
                key,
                text
            )

            print("DeepSeek:", reply)

            send_private(
                user_id,
                reply
            )

        # =====================
        # 群聊
        # =====================


        elif message_type == "group":


            group_id = data.get("group_id")
            text = get_text(data)
            images = get_images(data)
            video_url = get_video_url(data, text)


            if not text and not images and not video_url:
                return

            #每个群友有自己的上下文

            key = f"group_{group_id}_user_{user_id}"

            #判断有没有@Doo

            at_bot = is_at_bot(data)

            if at_bot:

                print(
                    f"\n[@Doo] 群 {group_id}|"
                    f"{user_id}: {text}"
                )

                if text == "/clear":

                    clear_history(key)
                    send_group(
                        group_id,
                        "你的对话记忆已清空"
                        )

                    return
                if video_url:
                    start_video_reply(
                        key, text, video_url, ask_deepseek_with_image,
                        lambda reply: send_group(group_id, reply)
                    )
                    return
                if images:

                    reply = ask_deepseek_with_image(
                        key,
                        text,
                        images
                    )
                else:
                    reply = ask_deepseek(
                        key,
                        text
                    )

                print("Deepseek:",reply)

                send_group(
                    group_id,
                    reply
                )

                return

            if not should_random_reply(group_id):
                return

            print(
                f"\n[随机插嘴] 群 {group_id} | "
                f"{user_id}: {text}"
            )

            prompt_text = f"""
这是QQ群里某个群友刚刚说的话：

{text}

没有人主动询问你，你只是恰好看到了这句话。

请以Doo的性格自然地插一句话。

要求：
- 回复非常短，通常一句即可
- 像真正的QQ群友
- 可以轻松接梗或发表简短反应，但不得攻击、羞辱用户
- 不要解释自己为什么突然说话
- 不要表现得像AI客服
- 如果这句话实在没什么值得回应的，也尽量只给一个很短的反应
"""


            if video_url:
                start_video_reply(
                    key, prompt_text, video_url, ask_deepseek_with_image,
                    lambda reply: send_group(group_id, reply), explicit=False
                )
                return
            if images:

                reply = ask_deepseek_with_image(
                    key,
                    prompt_text,
                    images
                )
            else:
                reply = ask_deepseek(
                    key,
                    prompt_text
                )
            print("Doo随机插嘴:",reply)

            send_group(
                group_id,
                reply
            )
            return


        
    except Exception as e:

        print("\n发生错误：")
        print(repr(e))


# =========================
# WebSocket
# =========================

def on_open(ws):
    print("=" * 40)
    print("DeepSeek QQ Bot 已启动")
    print("私聊：直接发送消息")
    print("群聊：@机器人 + 问题")
    print("抖音视频：私聊发链接，或群聊 @机器人 + 抖音分享")
    print("清空记忆：/clear")
    print("=" * 40)


def on_error(ws, error):
    print("WebSocket错误：", error)


def on_close(ws, code, msg):
    print(
        "WebSocket连接关闭：",
        code,
        msg
    )


ws = websocket.WebSocketApp(
    NAPCAT_WS,
    header=napcat_headers(),
    on_open=on_open,
    on_message=on_message,
    on_error=on_error,
    on_close=on_close
)

ws.run_forever()
