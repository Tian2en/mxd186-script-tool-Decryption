# -*- coding: utf-8 -*-
"""
下载 Node.js Windows x64 运行时，并取出 node.exe 放到项目根目录。

用法：
    python build/fetch_node.py [版本号]

默认版本见 DEFAULT_VERSION。node.exe 已在 .gitignore 中排除，不会进仓库。
"""
import io
import os
import sys
import zipfile
import urllib.request

DEFAULT_VERSION = "v22.11.0"
MIRRORS = [
    "https://nodejs.org/dist/{ver}/node-{ver}-win-x64.zip",
    "https://npmmirror.com/mirrors/node/{ver}/node-{ver}-win-x64.zip",
]

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TARGET = os.path.join(ROOT, "node.exe")


def download(url: str) -> bytes:
    print(f"  下载 {url}")
    req = urllib.request.Request(url, headers={"User-Agent": "mxd186-script-tool"})
    with urllib.request.urlopen(req, timeout=180) as resp:
        return resp.read()


def main():
    if os.path.exists(TARGET):
        print(f"node.exe 已存在，跳过：{TARGET}")
        return 0

    ver = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_VERSION
    data = None
    for tpl in MIRRORS:
        try:
            data = download(tpl.format(ver=ver))
            break
        except Exception as e:
            print(f"  失败：{e}")
    if data is None:
        print("所有镜像下载失败，请手动下载 Node.js 并把 node.exe 放到项目根目录。")
        return 1

    print("  解压 node.exe ...")
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        name = next((n for n in z.namelist()
                     if n.endswith("/node.exe") or n == "node.exe"), None)
        if not name:
            print("压缩包中未找到 node.exe")
            return 1
        with z.open(name) as src, open(TARGET, "wb") as dst:
            dst.write(src.read())

    size = os.path.getsize(TARGET) / 1024 / 1024
    print(f"完成：{TARGET}（{size:.1f} MB）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
