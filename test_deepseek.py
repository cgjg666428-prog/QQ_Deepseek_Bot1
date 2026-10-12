"""手动 API 连通性检查：会调用付费接口；不会读取或发送 QQ 聊天。"""
import os
from pathlib import Path
from dotenv import load_dotenv
from openai import OpenAI


def main():
    load_dotenv(Path(__file__).resolve().parent / ".env")
    key = os.getenv("DEEPSEEK_API_KEY")
    if not key:
        raise RuntimeError("请先配置本地 .env 中的 DEEPSEEK_API_KEY")
    client = OpenAI(api_key=key, base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"))
    response = client.chat.completions.create(
        model=os.getenv("DEEPSEEK_MODEL", "deepseek-flash"),
        messages=[{"role": "user", "content": "请用一句话打招呼。"}],
    )
    print(response.choices[0].message.content)


if __name__ == "__main__":
    main()
