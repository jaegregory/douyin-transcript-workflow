"""Stable launcher for the Douyin workflow."""
import importlib.util
import sys


def main():
    """通过 import 调用 pipeline，避开直接执行主脚本时的 Windows 入口异常。"""
    if len(sys.argv) < 2:
        print("Usage: python douyin_launcher.py <douyin_link>")
        return 1

    pipelinePath = r"D:\Projects\douyin_pipeline.py"
    spec = importlib.util.spec_from_file_location("douyin_pipeline", pipelinePath)
    pipelineModule = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(pipelineModule)
    return pipelineModule.main(sys.argv[1])


if __name__ == "__main__":
    sys.exit(main())
