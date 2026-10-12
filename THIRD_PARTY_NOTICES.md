# 第三方组件与来源

Python 包许可证来自本机安装版本的包元数据；不是对完整依赖树的许可审计。本仓库只引用这些依赖，不重新分发其源码、安装包或二进制。第三方条款保持独立，不能用本仓库未来选择的许可证覆盖。

| 组件 | 本机版本 | 包元数据许可 | 上游来源 |
| --- | --- | --- | --- |
| openai | 3.24.0 | Apache-2.0 | https://github.com/openai/openai-python |
| requests | 2.34.2 | Apache-2.0 | https://github.com/psf/requests |
| websocket-client | 1.9.2 | Apache-2.0 | https://github.com/websocket-client/websocket-client |
| python-dotenv | 1.2.4 | BSD-3-Clause | https://github.com/theskumar/python-dotenv |
| yt-dlp | 2026.8.19 | Unlicense | https://github.com/yt-dlp/yt-dlp |
| opencv-python | 5.0.0.93 | Apache 2.0 | https://github.com/opencv/opencv-python |

- NapCatQQ：https://github.com/NapNeko/NapCatQQ 。外部安装，没有打包进本仓库；所用版本及该版本许可证未取得可靠证据，发布前应记录实际版本并查看上游 LICENSE，不在此猜测许可。
- DeepSeek API：https://api-docs.deepseek.com/ 。远端服务，其使用条款与本仓库代码许可证不同。
- Python / SQLite：使用 Python 运行时及标准库；没有打包运行时。
- OpenCV wheel 可能包含 FFmpeg 等二进制组件；yt-dlp 及其他包也有传递依赖。制作可执行文件、容器或离线安装包前，必须另查实际分发内容的 LICENSE / NOTICE，不能只依据上表。

原项目包含根据第三方截图整理的人设。截图出处及转载许可未确认，完整人设没有纳入此发布副本，替换为通用 AI 助手提示词。不包含截图、头像、表情包和视频素材。将来重新添加时需记录作者、原链接、许可及修改情况。

若用户曾从教程或仓库复制其他片段，应补充准确出处及许可，并保留要求的署名。当前对话记录不能证明所有源文件的完整来源。
