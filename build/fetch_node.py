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
    "https://mirrors.tuna.tsinghua.edu.cn/nodejs-release/{ver}/node-{ver}-win-x64.zip",
    "https://mirrors.aliyun.com/nodejs-release/{ver}/node-{ver}-win-x64.zip",
]

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TARGET = os.path.join(ROOT, "node.exe")


def download(url: str) -> bytes:
    print(f"  下载 {url}")
    req = urllib.request.Request(url, headers={"User-Agent": "mxd186-script-tool"})
    with urllib.request.urlopen(req, timeout=300) as resp:
        return resp.read()


def main():
    if os.path.exists(TARGET):
        print(f"node.exe 已存在，跳过：{TARGET}")
        return 0

    ver = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_VERSION
    data = None
    last_err = None
    for tpl in MIRRORS:
        try:
            data = download(tpl.format(ver=ver))
            break
        except Exception as e:
            last_err = e
            print(f"  失败：{type(e).__name__}: {e}")
    if data is None:
        print()
        print("所有镜像下载均失败，最后一个错误：")
        print(f"  {type(last_err).__name__}: {last_err}")
        print()
        print("请手动处理（任选其一）：")
        print("  1. 自行下载 Node.js Windows x64 zip，解压后把 node.exe 放到项目根目录")
        print("  2. 若本机已装 Node，直接把 node.exe 复制到项目根目录")
        return 1

    print("  解压 node.exe ...")
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            name = next((n for n in z.namelist()
                         if n.endswith("/node.exe") or n == "node.exe"), None)
            if not name:
                print("压缩包中未找到 node.exe，文件列表前几项：")
                for n in z.namelist()[:10]:
                    print("   ", n)
                return 1
            with z.open(name) as src, open(TARGET, "wb") as dst:
                dst.write(src.read())
    except zipfile.BadZipFile as e:
        print(f"下载内容不是有效的 zip（可能被网络拦截）：{e}")
        return 1

    size = os.path.getsize(TARGET) / 1024 / 1024
    print(f"完成：{TARGET}（{size:.1f} MB）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
