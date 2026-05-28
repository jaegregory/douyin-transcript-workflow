# Douyin Transcript Workflow

把抖音链接下载为本地媒体，并用 `faster-whisper` 转写成带时间戳的中文文案。

这个项目适合在本机配合 Codex 使用：你把抖音链接发给 Codex，Codex 调用本地脚本读取本机 cookie，下载媒体并生成转写文本。

## 重要说明

抖音网页通常需要“新鲜 cookie”才能拿到真实视频地址。这个项目不会内置 cookie，也不应该让别人把 cookie 发到聊天或提交到 GitHub。

推荐做法是：

1. 用户自己在浏览器里安装 cookie 导出扩展，例如 **get cookies txt**。
2. 登录或访问网页版抖音，让浏览器生成可用 cookie。
3. 用扩展导出 Netscape 格式 cookie 文件。
4. 把文件保存在本机默认路径：

```text
D:\Download\cookies_all.txt
```

脚本只读取这个本地文件。不要把 `cookies_all.txt` 上传到仓库，也不要把 cookie 内容发给任何人。`.gitignore` 已经默认排除了 cookie、媒体和转写结果。

## 默认路径

| 用途 | 路径 |
| --- | --- |
| Cookie | `D:\Download\cookies_all.txt` |
| 转写输出 | `D:\Projects\transcripts\` |
| 媒体输出 | `D:\Projects\transcripts\media\` |
| 调试 URL | `D:\Projects\douyin_urls.txt` |

脚本文件本身使用仓库内的相对路径。如果要把输出改到其他目录，修改 `douyin_pipeline.py` 顶部的 `OUTPUT_DIR`、`TRANSCRIPT_DIR`、`MEDIA_DIR`。

## 安装依赖

```powershell
pip install -r requirements.txt
playwright install chromium
```

系统依赖：

- **ffmpeg**：用于音频格式转换。 `winget install ffmpeg` 或从 [ffmpeg.org](https://ffmpeg.org/download.html) 下载。

如果使用 CUDA 转写，还需要本机 CUDA / GPU 环境能被 `ctranslate2` 和 `faster-whisper` 正常识别。

## 一键命令

```powershell
python -u D:\Projects\douyin_launcher.py "<抖音链接>"
```

成功后会生成：

- 媒体文件：`D:\Projects\transcripts\media\*.mp4`
- 转写文件：`D:\Projects\transcripts\*.txt`

## Codex 触发关键词

在 Codex 里，当用户提供抖音链接，并提到以下任意意图时，可以直接执行本工作流：

- 抖音转写
- 抖音文案
- 提取文案
- 下载音频
- 视频转文字
- 处理抖音
- 帮我扒一下这个抖音

## Cookie 导出步骤

以 Edge / Chrome 的 **get cookies txt** 扩展为例：

1. 安装并启用扩展。
2. 打开网页版抖音，并访问一次要处理的视频页面。
3. 点击浏览器右上角扩展按钮。
4. 选择 **get cookies txt**。
5. 导出当前站点或全部站点 cookie，保存为：

```text
D:\Download\cookies_all.txt
```

如果你导出的文件名是 `cookies_all (2).txt`，可以重命名为 `cookies_all.txt`，或者修改 `douyin_pipeline.py` 里的 `COOKIE_PATH`。

## 转写原理：分段方案

长音频整段喂给 faster-whisper 时，编码器-解码器的交叉注意力矩阵随音频长度线性增长。在 6GB 以下显存的 GPU 上，30 分钟以上的视频会触发显存峰值溢出，导致 CUDA driver 底层崩溃（不是普通的 OOM 报错）。

`transcribe_segmented.py` 的解决方案：

1. 用 ffmpeg 将下载的媒体转为 16kHz 单声道 WAV
2. 每 300 秒切一段，逐段送入 faster-whisper（CUDA float16）
3. 合并各段结果，时间戳对齐到全局时间轴
4. 优先 CUDA，失败后自动退回到 CPU int8

这个方案在 RTX 3060 Laptop (6GB) 上实测稳定，总耗时约 3-4 分钟（34 分钟视频）。

### 单独使用转写模块

```powershell
python transcribe_segmented.py <input.wav> <output.txt> [300]
```

## 失败兜底

如果一键脚本失败，先不要盲目重试超过 3 次。按顺序检查：

1. Cookie 是否过期，文件路径是否仍为 `D:\Download\cookies_all.txt`。
2. `D:\Projects\douyin_urls.txt` 是否抓到了真实媒体 URL。
3. 如果只抓到 0.2 MB 左右的占位视频，说明当前 cookie 或页面状态没有拿到正片地址。
4. 如果下载到了 video-only 流，脚本会自动跳过无音频轨的候选 URL。
5. 如果 CUDA 转写失败，脚本会自动回退到 CPU int8。
6. 最后再退回分步执行：

```powershell
python -u douyin_pipeline.py "<抖音链接>"   # 仅下载
python transcribe_segmented.py <media.wav> <output.txt>
```

## 安全提醒

- 不要提交 `cookies_all.txt`。
- 不要提交下载的视频、音频或转写结果，除非你确认有权限公开。
- 不要把 cookie 粘贴到 issue、README、聊天记录或 commit 里。
- 如果 cookie 不小心泄露，建议退出网页版抖音登录状态，重新登录刷新 cookie。

## License

MIT
