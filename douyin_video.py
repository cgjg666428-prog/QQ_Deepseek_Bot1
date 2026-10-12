"""QQ 机器人的抖音视频处理模块，复用 video_test.py。"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading

from video_test import VideoError, extract_douyin_url, image_to_data_url

BASE_DIR = Path(__file__).resolve().parent
_video_slot = threading.BoundedSemaphore(1)


def describe_video_failure(details):
    """按下载器的实际报错给出可操作提示。"""
    # video_test 的通用失败说明含有 Cookie 建议，不能当作错误依据。
    # 优先使用下载器自己的 ERROR 行；依赖、文件及抽帧错误没有此行。
    errors = [line for line in details.splitlines() if line.lstrip().startswith("ERROR:")]
    text = ("\n".join(errors) if errors else details).lower()
    if "unsupported url" in text and "/note/" in text:
        return "这条分享是抖音图文作品，不是视频。当前下载器不支持图文页，请换一个视频链接，或直接把图片发给 Doo 看。"
    if "unsupported url" in text or "不支持" in text:
        return "下载器暂不支持这个链接，请使用单个视频的抖音分享链接，并更新 yt-dlp 后重试。"
    if "does not look like a netscape format cookies file" in text:
        return "cookies.txt 格式不正确，请导出 Netscape 格式的 Cookie 文件，不能使用空文件或 JSON 格式。"
    if "fresh cookies" in text or "cookies are needed" in text or "cookie" in text and "需要" in text:
        return "抖音下载器要求有效的浏览器 Cookie（不一定需要登录）。请配置自己的 cookies.txt 和 .env 中的 DOUYIN_COOKIES_FILE，再重启机器人；已有文件则需重新导出。"
    if "cookie 文件不存在" in text:
        return "配置的 Cookie 文件不存在，请检查 .env 中 DOUYIN_COOKIES_FILE 的路径。"
    if "no module named" in text or "缺少" in text:
        return "视频处理缺少 Python 依赖，请在机器人的 Python 环境运行 python -m pip install -U yt-dlp opencv-python。"
    if any(word in text for word in ("timed out", "connection", "proxyerror", "unable to download webpage", "name resolution")):
        return "连接抖音页面失败，请检查电脑网络或代理后重试。"
    if any(word in text for word in ("无法打开视频", "无法读取视频帧数", "未能提取画面", "保存关键帧失败")):
        return "视频文件无法抽帧，请用 video_test.py 测试该链接，检查视频是否完整。"
    return "视频处理失败，具体报错已保存到机器人目录 video_last_error.txt，请把其中的报错发来排查。"


def get_video_url(data, text=""):
    """支持普通分享文案和 OneBot JSON 分享卡片。"""
    candidates = [text]
    segments = data.get("message", [])
    if isinstance(segments, list):
        for segment in segments:
            if segment.get("type") == "json":
                raw = segment.get("data", {}).get("data", "")
                try:
                    card = json.loads(raw) if isinstance(raw, str) else raw
                except (ValueError, TypeError):
                    continue
                def collect(value):
                    if isinstance(value, str):
                        candidates.append(value)
                    elif isinstance(value, dict):
                        for item in value.values():
                            collect(item)
                    elif isinstance(value, list):
                        for item in value:
                            collect(item)
                collect(card)
    for candidate in candidates:
        try:
            return extract_douyin_url(candidate)
        except (VideoError, ValueError):
            continue
    return None


def prepare_video(url):
    # 子进程可强制超时；临时目录在成功或失败后都会清理。
    temp_root = BASE_DIR / ".video_temp"
    temp_root.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="doo_video_", dir=temp_root) as temporary:
        root = Path(temporary)
        command = [sys.executable, str(BASE_DIR / "video_test.py"), url, "--output", str(root)]
        cookies = os.getenv("DOUYIN_COOKIES_FILE", "").strip()
        if cookies:
            path = Path(cookies).expanduser()
            if not path.is_absolute():
                path = BASE_DIR / path
            command.extend(["--cookies", str(path)])
        try:
            result = subprocess.run(
                command, cwd=str(BASE_DIR), capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=180,
                env={**os.environ, "PYTHONIOENCODING": "utf-8"},
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except subprocess.TimeoutExpired as exc:
            raise VideoError("视频下载或抽帧超过 3 分钟，请换一条较短的视频重试。") from exc
        records = list(root.glob("*/info.json"))
        if result.returncode != 0 or len(records) != 1:
            details = (result.stderr + "\n" + result.stdout)[-12000:]
            print("视频处理失败：", details)
            # 保留诊断信息，临时目录清理后仍可查看；不记录 .env 或 Cookie 内容。
            try:
                (BASE_DIR / "video_last_error.txt").write_text(
                    f"子进程退出码：{result.returncode}\n{details}", encoding="utf-8"
                )
            except OSError as exc:
                print("保存视频报错失败：", repr(exc))
            raise VideoError(describe_video_failure(details))
        record = records[0]
        info = json.loads(record.read_text(encoding="utf-8"))
        frames = info.get("frames", [])
        if not frames:
            raise VideoError("未获得可用的视频画面。")
        images = [image_to_data_url(record.parent / frame["file"]) for frame in frames]
        timeline = "、".join(str(frame.get("seconds")) + "秒" for frame in frames)
        return images, timeline


def start_video_reply(chat_key, text, url, ask_image, send_reply, explicit=True):
    """一次只处理一个视频；工作线程避免阻塞 QQ 的其他消息。"""
    if not _video_slot.acquire(blocking=False):
        if explicit:
            send_reply("Doo 正在看另一段视频，等一会儿再发这条。")
        return

    def worker():
        try:
            images, timeline = prepare_video(url)
            prompt = (
                "下面的图片来自同一段抖音视频，按时间顺序排列。"
                f"抽帧时间点：{timeline}。\n"
                "请根据实际画面回应用户；这些只是部分抽帧，没有音频，"
                "不能声称听到了台词，也不要猜测未展示的情节。\n"
                f"用户消息：{text or '看看这个视频。'}"
            )
            reply = ask_image(chat_key, prompt, images)
        except VideoError as exc:
            reply = str(exc)
            if not explicit:
                print("随机视频回复取消：", reply)
                return
        except Exception as exc:
            print("视频理解发生错误：", repr(exc))
            if not explicit:
                return
            reply = "视频理解失败了，请检查电脑终端中的报错和现有看图接口。"
        finally:
            _video_slot.release()
        try:
            send_reply(reply)
        except Exception as exc:
            print("视频回复发送失败：", repr(exc))

    try:
        threading.Thread(target=worker, name="doo-video", daemon=True).start()
    except Exception:
        _video_slot.release()
        raise
