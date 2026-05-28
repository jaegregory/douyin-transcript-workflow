# Douyin Transcript Workflow

把抖音链接下载为本地媒体，并用 faster-whisper 转写成带时间戳的中文文案。

当前脚本按你的 Windows 本机路径配置：

- Cookie：`D:\Download\cookies_all.txt`
- 输出目录：`D:\Projects\transcripts\`
- 媒体目录：`D:\Projects\transcripts\media\`

不要把 cookie、下载视频或转写结果提交到仓库；`.gitignore` 已经默认排除这些文件。

## 触发关键词

在 Codex 里，当用户提供抖音链接，并提到以下任意意图时，直接执行本工作流：

- 抖音转写
- 抖音文案
- 提取文案
- 下载音频
- 视频转文字
- 处理抖音
- 帮我扒一下这个抖音

## 一键命令

```powershell
python -u D:\Projects\douyin_launcher.py "<抖音链接>"
```

如果把仓库 clone 到别的位置，需要同步修改 `douyin_launcher.py` 里的 `pipelinePath`，以及 `douyin_pipeline.py` 顶部的 `COOKIE_PATH`、`OUTPUT_DIR` 等路径。

## 安装依赖

```powershell
pip install -r requirements.txt
playwright install chromium
```

## 默认路径

| 用途 | 路径 |
| --- | --- |
| 工作流入口 | `D:\Projects\douyin_launcher.py` |
| 主脚本 | `D:\Projects\douyin_pipeline.py` |
| Cookie | `D:\Download\cookies_all.txt` |
| 转写输出 | `D:\Projects\transcripts\` |
| 媒体输出 | `D:\Projects\transcripts\media\` |
| 调试 URL | `D:\Projects\douyin_urls.txt` |

## 失败兜底

如果一键脚本失败，先不要盲目重试超过 3 次。按顺序检查：

1. Cookie 是否过期或文件路径是否仍为 `D:\Download\cookies_all.txt`。
2. `D:\Projects\douyin_urls.txt` 是否抓到了真实媒体 URL。
3. 如果只抓到 0.2 MB 左右的占位视频，说明当前 cookie 或页面状态没有拿到正片地址。
4. 最后再退回两步法：

```powershell
python -u D:\Projects\douyin_dl.py "<抖音链接>"
python -X faulthandler -u D:\Projects\transcribe.py D:\Projects\temp_douyin_audio.mp3
```
