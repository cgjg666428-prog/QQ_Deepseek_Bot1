"""抖音链接下载与关键帧测试。运行 python video_test.py --help 查看选项。"""
from __future__ import annotations

import argparse
import base64
import html
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4


class VideoError(Exception):
    pass


def extract_douyin_url(text: str) -> str:
    for match in re.findall(r"https?://[^\s<>\"']+", html.unescape(text)):
        url = match.rstrip("。，、；：！？,.!?;)]}）】》")
        parsed = urlsplit(url)
        host = (parsed.hostname or "").lower()
        if (host == "douyin.com" or host.endswith(".douyin.com")) and not parsed.username:
            return url
    raise VideoError("没有找到抖音链接，请粘贴包含 https://v.douyin.com/ 或 douyin.com 的分享文案。")


def download_video(url: str, output_dir: Path, cookies: Path | None = None):
    try:
        import yt_dlp
    except ImportError as exc:
        raise VideoError("缺少 yt-dlp，请运行 python -m pip install -U yt-dlp opencv-python") from exc
    options = {
        "outtmpl": str(output_dir / "video.%(ext)s"),
        # 选择同时包含画面和音频的单文件格式，基础测试不需要 FFmpeg 合并。
        "format": "best[ext=mp4]/best",
        "noplaylist": True,
        "socket_timeout": 30,
        "retries": 2,
        "extractor_retries": 2,
        "windowsfilenames": True,
    }
    if cookies:
        if not cookies.is_file():
            raise VideoError(f"Cookie 文件不存在：{cookies}")
        options["cookiefile"] = str(cookies)
    try:
        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(url, download=True)
            if not info or info.get("_type") in ("playlist", "multi_video"):
                raise VideoError("请使用单个视频的分享链接。")
            video = Path(ydl.prepare_filename(info))
    except yt_dlp.utils.DownloadError as exc:
        raise VideoError(
            "抖音视频下载失败。可先更新 yt-dlp；若提示需要 fresh cookies，可使用自己的 "
            "Netscape 格式 Cookie 文件加 --cookies 参数，或用 --local 测试已保存的视频。\n"
            f"下载器信息：{exc}"
        ) from exc
    if not video.is_file():
        raise VideoError("下载器没有生成可读取的视频文件。")
    metadata = {key: info.get(key) for key in ("id", "title", "uploader", "duration", "webpage_url")}
    return video, metadata


def extract_frames(video_path: Path, output_dir: Path, frame_count: int = 6):
    try:
        import cv2
    except ImportError as exc:
        raise VideoError("缺少 OpenCV，请运行 python -m pip install -U yt-dlp opencv-python") from exc
    cap = cv2.VideoCapture(str(video_path))
    try:
        if not cap.isOpened():
            raise VideoError(f"无法打开视频：{video_path}")
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        fps = cap.get(cv2.CAP_PROP_FPS)
        if total <= 0:
            raise VideoError("无法读取视频帧数，请换用完整的 MP4 视频。")
        positions = sorted({min(total - 1, int(total * (i + 1) / (frame_count + 1))) for i in range(frame_count)})
        frames = []
        for position in positions:
            cap.set(cv2.CAP_PROP_POS_FRAMES, position)
            ok, frame = cap.read()
            if not ok:
                continue
            height, width = frame.shape[:2]
            if max(height, width) > 1280:
                scale = 1280 / max(height, width)
                frame = cv2.resize(frame, (max(1, round(width * scale)), max(1, round(height * scale))))
            path = output_dir / f"frame_{len(frames) + 1:02d}.jpg"
            ok, data = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
            if not ok:
                raise VideoError("保存关键帧失败。")
            # 用 Python 写文件以支持 Windows 中文目录。
            path.write_bytes(data.tobytes())
            frames.append({"file": path.name, "frame_index": position, "seconds": round(position / fps, 3) if fps > 0 else None})
        if not frames:
            raise VideoError("视频打开成功，但未能提取画面。")
        return frames
    finally:
        cap.release()


def image_to_data_url(image_path: str | Path) -> str:
    """后续接视觉模型时使用；本程序不会调用 API。"""
    return "data:image/jpeg;base64," + base64.b64encode(Path(image_path).read_bytes()).decode("ascii")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="输入抖音分享链接，下载视频并抽取关键帧（默认 6 张）。")
    parser.add_argument("share_text", nargs="?", help="链接或整段分享文案；省略时交互输入")
    parser.add_argument("--local", type=Path, help="改用本地视频，不下载")
    parser.add_argument("--frames", type=int, default=6, help="关键帧数量，1 到 30，默认 6")
    parser.add_argument("--cookies", type=Path, help="自己的 Netscape 格式 Cookie 文件")
    parser.add_argument("--output", type=Path, default=Path(__file__).resolve().parent / "video_results", help="结果根目录")
    args = parser.parse_args(argv)
    if not 1 <= args.frames <= 30:
        parser.error("--frames 必须在 1 到 30 之间")
    if args.local and args.share_text:
        parser.error("链接和 --local 只能选一个")
    try:
        if args.local:
            source = args.local.expanduser().resolve()
            if not source.is_file():
                raise VideoError(f"本地视频不存在：{source}")
        else:
            text = args.share_text or input("请粘贴抖音链接或分享文案，然后按回车：\n").strip()
            source = extract_douyin_url(text)
        run_dir = args.output.resolve() / (datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid4().hex[:6])
        run_dir.mkdir(parents=True, exist_ok=False)
        print(f"结果目录：{run_dir}")
        if args.local:
            video, metadata = source, {"source": "local"}
        else:
            print("正在下载视频……")
            video, metadata = download_video(source, run_dir, args.cookies)
        print("正在抽取关键帧……")
        frames = extract_frames(video, run_dir, args.frames)
        metadata.update({"video_path": str(video), "frames": frames})
        (run_dir / "info.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"完成：已保存 {len(frames)} 张关键帧。\n视频：{video}\n图片和记录：{run_dir}")
        if len(frames) < args.frames:
            print("提示：视频过短或部分帧无法读取，实际图片少于请求数量。")
        print("这是下载/抽帧测试，尚未接入 QQ、视觉模型或语音识别。")
        return 0
    except (VideoError, OSError, EOFError) as exc:
        print(f"失败：{exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\n已取消。", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
