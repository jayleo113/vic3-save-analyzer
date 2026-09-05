# -*- coding: utf-8 -*-
"""Start a token-protected public tunnel for the local Victoria 3 data API."""

from __future__ import annotations

import argparse
import re
import secrets
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parent
TOOLS_DIR = PROJECT_DIR / "tools"
CLOUDFLARED = TOOLS_DIR / "cloudflared.exe"
CLOUDFLARED_URL = "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe"


def find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def ensure_cloudflared() -> Path:
    if CLOUDFLARED.exists():
        return CLOUDFLARED
    TOOLS_DIR.mkdir(parents=True, exist_ok=True)
    print("正在准备公网隧道工具，位置在 F 盘项目 tools 目录...")
    urllib.request.urlretrieve(CLOUDFLARED_URL, CLOUDFLARED)
    return CLOUDFLARED


def wait_for_public_url(proc: subprocess.Popen[str], timeout: int = 90) -> str:
    pattern = re.compile(r"https://[a-zA-Z0-9-]+\.trycloudflare\.com")
    started = time.time()
    while time.time() - started < timeout:
        line = proc.stderr.readline() if proc.stderr else ""
        if not line:
            if proc.poll() is not None:
                raise RuntimeError("公网隧道启动失败")
            time.sleep(0.2)
            continue
        match = pattern.search(line)
        if match:
            return match.group(0)
    raise RuntimeError("公网隧道启动超时")


def main() -> None:
    parser = argparse.ArgumentParser(description="Victoria 3 public data API")
    parser.add_argument("--dataset", default="latest", help="默认给对话模型读取的数据包")
    parser.add_argument("--token", default="", help="访问密钥；不填则自动生成")
    args = parser.parse_args()

    token = args.token.strip() or secrets.token_urlsafe(24)
    port = find_free_port()
    cloudflared = ensure_cloudflared()

    api_proc = subprocess.Popen(
        [sys.executable, "api_server.py", "serve", "--host", "127.0.0.1", "--port", str(port), "--token", token],
        cwd=PROJECT_DIR,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    tunnel_proc: subprocess.Popen[str] | None = None
    try:
        time.sleep(1)
        if api_proc.poll() is not None:
            raise RuntimeError("本地 API 启动失败")
        tunnel_proc = subprocess.Popen(
            [str(cloudflared), "tunnel", "--url", f"http://127.0.0.1:{port}", "--no-autoupdate"],
            cwd=PROJECT_DIR,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        public_url = wait_for_public_url(tunnel_proc)
        package_url = f"{public_url}/api/package?dataset={args.dataset}&token={token}"
        root_url = f"{public_url}/?token={token}"
        print("\n公网 API 已启动")
        print(f"入口：{root_url}")
        print(f"给对话模型的单一数据地址：{package_url}")
        print("\n这个窗口不要关。按 Ctrl+C 停止公网 API。")
        while True:
            if api_proc.poll() is not None:
                raise RuntimeError("本地 API 已停止")
            if tunnel_proc.poll() is not None:
                raise RuntimeError("公网隧道已停止")
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n正在停止公网 API...")
    finally:
        if tunnel_proc and tunnel_proc.poll() is None:
            tunnel_proc.terminate()
        if api_proc.poll() is None:
            api_proc.terminate()


if __name__ == "__main__":
    main()
