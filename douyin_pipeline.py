"""Douyin -> media download -> Chinese transcript pipeline."""
import asyncio
import faulthandler
import html as htmlLib
import json
import os
import re
import subprocess
import sys
from datetime import datetime

from transcribe_segmented import transcribe_segmented

faulthandler.enable()

COOKIE_PATH = r"D:\Download\cookies_all.txt"
OUTPUT_DIR = r"D:\Projects"
TRANSCRIPT_DIR = r"D:\Projects\transcripts"
MEDIA_DIR = r"D:\Projects\transcripts\media"
DEBUG_URLS_PATH = os.path.join(OUTPUT_DIR, "douyin_urls.txt")
HF_ENDPOINT = "https://hf-mirror.com"
MIN_MEDIA_MB = 0.5

os.environ["HF_ENDPOINT"] = HF_ENDPOINT


def loadCookies(cookiePath):
    """读取 Netscape cookie 文件，只注入抖音相关 cookie，避免无关站点 cookie 干扰浏览器上下文。"""
    cookies = []
    if not os.path.exists(cookiePath):
        return cookies

    with open(cookiePath, "r", encoding="utf-8-sig") as cookieFile:
        for rawLine in cookieFile:
            line = rawLine.strip()
            if not line or line.startswith("#"):
                continue

            parts = line.split("\t")
            if len(parts) < 7:
                continue

            domain = parts[0].lstrip(".")
            if "douyin.com" not in domain and "iesdouyin.com" not in domain:
                continue

            name, value = parts[5], parts[6]
            if not name or not value or not name.isascii() or len(value) > 2048:
                continue

            cookies.append({
                "name": name,
                "value": value,
                "domain": domain,
                "path": parts[2] if parts[2] else "/",
            })

    return cookies[:80]


def normalizeUrl(url):
    """统一处理页面中转义过的 URL，方便后续去重和下载。"""
    if not isinstance(url, str):
        return ""
    return url.replace("\\u002F", "/").replace("\\/", "/").strip()


def addCandidate(candidateList, source, url, contentType="", contentLength=""):
    """只收集可能指向媒体资源的 URL，减少调试文件中的噪声。"""
    normalizedUrl = normalizeUrl(url)
    if not normalizedUrl.startswith("http"):
        return
    candidateList.append((source, normalizedUrl, contentType, contentLength))


def extractUrlsFromJson(jsonData, candidateList, depth=0):
    """递归扫描抖音页面 JSON，抓取常见视频/音频字段中的播放地址。"""
    if depth > 20:
        return

    if isinstance(jsonData, dict):
        for key in [
            "play_addr",
            "playAddr",
            "download_addr",
            "url_list",
            "play_api",
            "Source",
            "src",
            "playUrl",
            "video_url",
            "bit_rate",
        ]:
            if key not in jsonData:
                continue

            value = jsonData[key]
            if isinstance(value, dict):
                if "url_list" in value and value["url_list"]:
                    addCandidate(candidateList, "JSON", value["url_list"][0])
                if "Source" in value:
                    addCandidate(candidateList, "JSON", value["Source"])
                if "play_addr" in value:
                    addCandidate(candidateList, "JSON", str(value["play_addr"]))
            elif isinstance(value, list) and value:
                firstItem = value[0]
                if isinstance(firstItem, str):
                    addCandidate(candidateList, "JSON", firstItem)
                elif isinstance(firstItem, dict):
                    for nestedKey in ["url_list", "src", "play_addr", "Source"]:
                        nestedValue = firstItem.get(nestedKey)
                        if isinstance(nestedValue, list) and nestedValue:
                            addCandidate(candidateList, "JSON", nestedValue[0])
                        elif isinstance(nestedValue, str):
                            addCandidate(candidateList, "JSON", nestedValue)
            elif isinstance(value, str):
                addCandidate(candidateList, "JSON", value)

        for value in jsonData.values():
            extractUrlsFromJson(value, candidateList, depth + 1)
    elif isinstance(jsonData, list):
        for item in jsonData:
            extractUrlsFromJson(item, candidateList, depth + 1)


async def collectMediaCandidates(shortUrl):
    """打开抖音页面，同时从网络请求、响应、DOM 和页面 JSON 中收集候选媒体地址。"""
    from playwright.async_api import async_playwright

    candidateList = []
    videoId = None

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled"],
        )
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 Chrome/131.0.0.0 Safari/537.36 Edg/131.0.0.0"
            ),
            viewport={"width": 1920, "height": 1080},
            locale="zh-CN",
        )

        cookies = loadCookies(COOKIE_PATH)
        if cookies:
            await context.add_cookies(cookies)
            print(f"  Loaded cookies: {len(cookies)}")

        page = await context.new_page()
        await page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined});")

        async def onRequest(request):
            url = request.url
            if any(marker in url for marker in [".mp4", ".m4a", ".mp3", "video", "play", "aweme", "download"]):
                addCandidate(candidateList, "REQ", url)

        async def onResponse(response):
            url = response.url
            contentType = response.headers.get("content-type", "")
            contentLength = response.headers.get("content-length", "")
            isLargeResponse = contentLength.isdigit() and int(contentLength) > 500000
            if any(marker in contentType for marker in ["video", "audio", "octet-stream"]) or isLargeResponse:
                addCandidate(candidateList, "RESP", url, contentType, contentLength)

        page.on("request", onRequest)
        page.on("response", onResponse)

        print("  [1/4] Loading page...")
        try:
            await page.goto(shortUrl, wait_until="domcontentloaded", timeout=30000)
        except Exception as exc:
            print(f"  Page load warning: {type(exc).__name__}")

        try:
            await page.wait_for_selector("video", timeout=20000)
            print("  Video element found")
        except Exception:
            print("  No <video> tag before timeout")

        await asyncio.sleep(5)

        finalUrl = page.url
        videoMatch = re.search(r"/video/(\d+)", finalUrl)
        if videoMatch:
            videoId = videoMatch.group(1)
            print(f"  Video ID: {videoId}")

        if videoId and not any(".mp4" in str(item).lower() or "video" in str(item).lower() for item in candidateList):
            mobileUrl = f"https://www.iesdouyin.com/share/video/{videoId}/?region=CN&mid={videoId}"
            print("  Trying mobile share page...")
            try:
                await page.goto(mobileUrl, wait_until="domcontentloaded", timeout=30000)
                await asyncio.sleep(8)
            except Exception as exc:
                print(f"  Mobile page warning: {type(exc).__name__}")

        try:
            domSrc = await page.evaluate(
                """() => {
                    const video = document.querySelector('video');
                    if (video && video.src) return video.src;
                    const sources = document.querySelectorAll('video source');
                    for (const source of sources) {
                        if (source.src) return source.src;
                    }
                    return null;
                }"""
            )
            if domSrc:
                addCandidate(candidateList, "DOM", domSrc)
                print("  Found video src in DOM")
        except Exception:
            pass

        pageHtml = await page.content()
        renderMatch = re.search(r'<script id="RENDER_DATA"[^>]*>(.*?)</script>', pageHtml, re.DOTALL)
        if not renderMatch:
            renderMatch = re.search(r"window\.__UNIVERSAL_DATA__\s*=\s*({.*?});", pageHtml, re.DOTALL)
        if not renderMatch:
            renderMatch = re.search(r'self\.__pace_f\.push\(\[0,"(.*?)"\]\)', pageHtml)

        if renderMatch:
            try:
                rawJson = htmlLib.unescape(renderMatch.group(1))
                extractUrlsFromJson(json.loads(rawJson[:1000000]), candidateList)
                print("  Parsed render data")
            except Exception as exc:
                print(f"  JSON parse: {type(exc).__name__}")

        for url in re.findall(r'https?://[^"\'\\s]+\.(?:mp4|m4a|mp3|aac|wav|ts)[^"\'\\s]*', pageHtml):
            addCandidate(candidateList, "REGEX", url)

        await browser.close()

    return videoId, candidateList


def rankCandidateUrls(candidateList):
    """按稳定性排序候选地址：DOM 优先，其次大响应、明确 mp4 请求，再做兜底。"""
    rankedUrls = []

    def pushUrl(url):
        normalizedUrl = normalizeUrl(url)
        if normalizedUrl.startswith("http") and normalizedUrl not in rankedUrls:
            rankedUrls.append(normalizedUrl)

    for _source, url, _contentType, _contentLength in candidateList:
        loweredUrl = url.lower()
        if any(marker in loweredUrl for marker in ["audio", ".m4a", ".mp3", ".aac", "mp4a"]):
            pushUrl(url)

    for source, url, _contentType, _contentLength in candidateList:
        if source == "DOM":
            pushUrl(url)

    for source, url, contentType, contentLength in candidateList:
        isLargeResponse = contentLength.isdigit() and int(contentLength) > 500000
        if source == "RESP" and (any(marker in contentType for marker in ["video", "audio", "octet-stream"]) or isLargeResponse):
            pushUrl(url)

    for source, url, _contentType, _contentLength in candidateList:
        loweredUrl = url.lower()
        if source in ("REQ", "REGEX") and any(ext in loweredUrl for ext in [".mp4", ".m4a", ".mp3", ".aac"]):
            pushUrl(url)

    for _source, url, _contentType, _contentLength in candidateList:
        loweredUrl = url.lower()
        if any(marker in loweredUrl for marker in ["video", "play", "aweme", ".mp4", ".m4a", ".mp3", ".aac"]):
            pushUrl(url)

    return rankedUrls


def hasAudioStream(mediaPath):
    """下载后检查媒体是否真的包含音频轨，避免把无声 video-only 流交给 Whisper。"""
    try:
        import av

        with av.open(mediaPath) as container:
            return bool(container.streams.audio)
    except Exception:
        return False


def saveDebugUrls(candidateList):
    """保存候选 URL 便于排查，但不打印 cookie 或其他凭证。"""
    with open(DEBUG_URLS_PATH, "w", encoding="utf-8") as debugFile:
        for item in candidateList[:80]:
            debugFile.write(str(item)[:500] + "\n")


def downloadBestMedia(candidateUrls, mediaPath):
    """逐个尝试候选媒体地址，只有下载体积达标才认为成功，避免 0.2MB 占位视频误判。"""
    import requests as requestsLib

    os.makedirs(os.path.dirname(mediaPath), exist_ok=True)

    for index, candidateUrl in enumerate(candidateUrls, 1):
        print(f"  [2/4] Downloading candidate {index}/{len(candidateUrls)}...")
        try:
            response = requestsLib.get(
                candidateUrl,
                stream=True,
                timeout=300,
                headers={
                    "User-Agent": "Mozilla/5.0",
                    "Referer": "https://www.douyin.com/",
                },
            )
            response.raise_for_status()

            with open(mediaPath, "wb") as mediaFile:
                for chunk in response.iter_content(16384):
                    if chunk:
                        mediaFile.write(chunk)

            sizeMb = os.path.getsize(mediaPath) / 1024 / 1024
            print(f"  Downloaded: {sizeMb:.1f} MB")
            if sizeMb >= MIN_MEDIA_MB and hasAudioStream(mediaPath):
                return candidateUrl, sizeMb
            if sizeMb >= MIN_MEDIA_MB:
                print("  Candidate has no audio stream, trying next URL...")
        except Exception as exc:
            print(f"  Candidate failed: {type(exc).__name__}")

    return None, 0


def _convertToWav(mediaPath, wavPath):
    """Convert downloaded media to 16kHz mono WAV for faster-whisper."""
    result = subprocess.run(
        [
            "ffmpeg", "-y", "-v", "error",
            "-i", mediaPath,
            "-ac", "1", "-ar", "16000", "-sample_fmt", "s16",
            wavPath,
        ],
        text=True,
        timeout=300,
    )
    if result.returncode != 0 or not os.path.exists(wavPath):
        raise RuntimeError("ffmpeg conversion to WAV failed")
    return wavPath


def _detectDevice(device):
    """Resolve device='auto' to a concrete (device, compute_type) pair."""
    if device in ("cuda", "cpu"):
        computeType = "float16" if device == "cuda" else "int8"
        return device, computeType

    import torch
    if torch.cuda.is_available():
        return "cuda", "float16"
    return "cpu", "int8"


def transcribeMedia(mediaPath, transcriptPath, device="auto"):
    """Transcribe media using segmented faster-whisper.

    Converts media to 16kHz mono WAV, then splits into 300s segments
    to avoid VRAM overflow on GPUs with ≤6 GB.

    device: 'cuda' (GPU only), 'cpu' (CPU int8), or 'auto' (detect).
    """
    resolvedDevice, computeType = _detectDevice(device)
    wavPath = mediaPath.rsplit(".", 1)[0] + ".wav"

    _convertToWav(mediaPath, wavPath)
    print(f"  [3/4] WAV prepared: {wavPath}")
    print(f"  [3/4] Transcribing ({resolvedDevice}, {computeType})...")

    transcribe_segmented(
        wavPath,
        transcriptPath,
        segment_s=300,
        model_size="small",
        device=resolvedDevice,
        compute_type=computeType,
        language="zh",
    )
    return transcriptPath


def main(shortUrl, device="auto"):
    print(f"Douyin Pipeline\n  URL: {shortUrl}\n")

    os.makedirs(TRANSCRIPT_DIR, exist_ok=True)
    os.makedirs(MEDIA_DIR, exist_ok=True)

    videoId, candidateList = asyncio.run(collectMediaCandidates(shortUrl))
    saveDebugUrls(candidateList)

    candidateUrls = rankCandidateUrls(candidateList)
    if not candidateUrls:
        print(f"ERROR: Could not find media URL. Debug file: {DEBUG_URLS_PATH}")
        return None, None

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    baseName = f"douyin_{videoId or timestamp}_{timestamp}"
    mediaPath = os.path.join(MEDIA_DIR, baseName + ".mp4")
    transcriptPath = os.path.join(TRANSCRIPT_DIR, baseName + ".txt")

    usedUrl, _sizeMb = downloadBestMedia(candidateUrls, mediaPath)
    if not usedUrl:
        print(f"ERROR: Downloaded media was too small or invalid. Debug file: {DEBUG_URLS_PATH}")
        return None, None

    print(f"  Media saved: {mediaPath}")
    transcribeMedia(mediaPath, transcriptPath, device=device)

    print("  [4/4] Finished")
    print(f"\nTranscript: {transcriptPath}")
    print(f"Media: {mediaPath}")
    return transcriptPath, mediaPath


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python douyin_pipeline.py <douyin_short_link> [--device auto|cuda|cpu]")
        sys.exit(1)
    dev = "auto"
    args = sys.argv[1:]
    if "--device" in args:
        idx = args.index("--device")
        if idx + 1 < len(args):
            dev = args[idx + 1]
        args.pop(idx)
        if idx < len(args):
            args.pop(idx)
    if not args or dev not in ("auto", "cuda", "cpu"):
        print("Usage: python douyin_pipeline.py <douyin_short_link> [--device auto|cuda|cpu]")
        sys.exit(1)
    _, _ = main(args[0], device=dev)
