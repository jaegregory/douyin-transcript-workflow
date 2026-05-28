"""Batch launcher for the Douyin transcript workflow.

Single URL (backward-compatible):
    python douyin_launcher.py "<link>"
    python douyin_launcher.py --device cuda "<link>"

Batch:
    python douyin_launcher.py "<link1>" "<link2>" "<link3>"
    python douyin_launcher.py --urls-file urls.txt
    python douyin_launcher.py --device cpu --urls-file urls.txt

Device options:
    auto (default)  – detect CUDA, fall back to CPU
    cuda            – GPU only, error if unavailable
    cpu             – CPU int8 only
"""

import importlib.util
import os
import sys


def resolveDevice(device):
    """Validate and resolve device choice. Raise SystemExit for invalid choices."""
    if device not in ("auto", "cuda", "cpu"):
        print(f"ERROR: --device must be 'auto', 'cuda', or 'cpu' (got '{device}')")
        sys.exit(2)
    return device


def loadPipeline():
    pipelinePath = os.path.join(os.path.dirname(__file__), "douyin_pipeline.py")
    spec = importlib.util.spec_from_file_location("douyin_pipeline", pipelinePath)
    pipelineModule = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(pipelineModule)
    return pipelineModule


def collectUrls(args):
    """Parse positional URLs and optional --urls-file into a flat list."""
    urls = []
    urlsFile = None
    i = 0
    while i < len(args):
        if args[i] == "--urls-file" and i + 1 < len(args):
            urlsFile = args[i + 1]
            i += 2
        elif args[i].startswith("--"):
            i += 2 if i + 1 < len(args) else 1
        else:
            urls.append(args[i])
            i += 1

    if urlsFile:
        if not os.path.exists(urlsFile):
            print(f"ERROR: --urls-file not found: {urlsFile}")
            sys.exit(1)
        with open(urlsFile, "r", encoding="utf-8") as f:
            for line in f:
                stripped = line.strip()
                if stripped and not stripped.startswith("#"):
                    urls.append(stripped)

    return urls


def parseDevice(args):
    """Extract --device value from args, default 'auto'."""
    for i, a in enumerate(args):
        if a == "--device" and i + 1 < len(args):
            return resolveDevice(args[i + 1])
    return "auto"


def main():
    args = sys.argv[1:]

    if not args or "-h" in args or "--help" in args:
        print(__doc__)
        return 0

    device = parseDevice(args)
    urls = collectUrls(args)

    if not urls:
        print("ERROR: No URLs provided. Use positional args or --urls-file.")
        print(__doc__)
        return 1

    pipeline = loadPipeline()
    results = []
    total = len(urls)

    print(f"Batch transcript: {total} URL(s), device = {device}\n")

    for idx, url in enumerate(urls, 1):
        print(f"{'='*60}")
        print(f"[{idx}/{total}] {url}")
        print(f"{'='*60}")
        try:
            transcriptPath, mediaPath = pipeline.main(url, device=device)
            if transcriptPath:
                results.append((url, "OK", transcriptPath))
            else:
                results.append((url, "FAILED", None))
        except Exception as exc:
            print(f"  ERROR: {exc}")
            results.append((url, "ERROR", str(exc)))

    # Summary
    print(f"\n{'='*60}")
    print("SUMMARY")
    print(f"{'='*60}")
    ok = sum(1 for _, status, _ in results if status == "OK")
    failed = total - ok
    print(f"Total: {total}  OK: {ok}  Failed: {failed}\n")
    for url, status, detail in results:
        marker = "[OK]" if status == "OK" else "[FAIL]"
        detailStr = f" -> {detail}" if detail else ""
        print(f"  {marker} {url}{detailStr}")

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
