# -*- coding: utf-8 -*-
"""
MXD186 脚本解密 + 去混淆工具  v1.2
------------------------------------------------
功能：
  1) 单个 .jse 文件：解密（AES）→ 去混淆（可读化），输出统一为 <名>.js
  2) 整个文件夹：批量解密 + 去混淆（支持递归子目录、多进程并行）
  3) 支持把 .jse 文件 / 文件夹直接拖拽到窗口

解密：AES-128/ECB/PKCS5Padding + Base64（密钥由服务端脚本密钥派生，已固定）
去混淆：内置 Node 引擎 + Babel 反混淆器（批量走单进程队列，多进程并行）
"""
import os
import sys
import base64
import shutil
import tempfile
import subprocess
import threading
import queue
import traceback
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

try:
    from Crypto.Cipher import AES
except Exception:
    AES = None

try:
    from tkinterdnd2 import TkinterDnD, DND_FILES
    HAS_DND = True
except Exception:
    HAS_DND = False

# ============ 固定密钥（由服务端脚本密钥 RyZuxRfceVKJBGuwn0MTDIdz0NASMBRC 派生） ============
AES_KEY_HEX = "fb0b16dbfd16a96367c6a99a34bbaed7"
CPU = os.cpu_count() or 4
DEFAULT_WORKERS = max(2, min(8, CPU - 2))

BG = "#11161c"
PANEL = "#1a222b"
PANEL2 = "#222c37"
LINE = "#2e3a47"
TXT = "#d8e2ec"
SUB = "#8fa1b5"
ACCENT = "#4ea1ff"
OK = "#37d6a0"
ERR = "#ff6b6b"


def _candidate_dirs():
    """资源查找目录：兼容「PyInstaller 冻结」与「源码直接运行」两种布局"""
    dirs = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        dirs.append(meipass)
    here = os.path.dirname(os.path.abspath(__file__))
    parent = os.path.dirname(here)
    dirs += [
        here,                          # src/
        os.path.join(here, "assets"),  # src/assets/
        os.path.join(parent, "assets"),  # 项目根/assets/
        parent,                        # 项目根/
        os.getcwd(),
    ]
    return dirs


def resource_path(name: str) -> str:
    for d in _candidate_dirs():
        p = os.path.join(d, name)
        if os.path.exists(p):
            return p
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, name)


def find_node() -> str:
    cand = resource_path("node.exe")
    if os.path.exists(cand):
        return cand
    for c in (shutil.which("node"), shutil.which("node.exe")):
        if c:
            return c
    return ""


class EmptyScript(Exception):
    """空文件 / 无有效密文，应跳过而非报错"""
    pass


def decrypt_bytes(raw: bytes) -> bytes:
    """AES-128-ECB 解密 + 去 PKCS5 填充"""
    text = raw.strip()
    if not text:
        raise EmptyScript("空文件（0 字节）")
    try:
        data = base64.b64decode(b"".join(text.split()))
    except Exception as e:
        raise ValueError(f"不是有效的 Base64（{e}）")
    if not data:
        raise EmptyScript("Base64 解码后为空")
    if len(data) % 16 != 0:
        raise ValueError(f"密文长度 {len(data)} 不是 16 的倍数")
    pt = AES.new(bytes.fromhex(AES_KEY_HEX), AES.MODE_ECB).decrypt(data)
    if not pt:
        raise EmptyScript("解密结果为空")
    pad = pt[-1]
    if 1 <= pad <= 16 and len(pt) >= pad and pt[-pad:] == bytes([pad]) * pad:
        pt = pt[:-pad]
    return pt


class Deobfuscator:
    """调用内置 Node 反混淆器"""

    def __init__(self):
        self.node = find_node()
        self.bundle = resource_path("deob_bundle.js")

    @property
    def available(self) -> bool:
        return bool(self.node) and os.path.exists(self.bundle)

    def run(self, in_path: str, out_path: str) -> tuple:
        """单文件去混淆"""
        r = subprocess.run(
            [self.node, self.bundle, in_path, out_path],
            capture_output=True, text=True, timeout=300,
            encoding="utf-8", errors="replace",
        )
        ok = r.returncode == 0 and os.path.exists(out_path)
        return ok, (r.stdout or "") + (r.stderr or "")

    def run_batch(self, pairs, workers=DEFAULT_WORKERS, on_progress=None):
        """
        批量去混淆：把 (输入, 输出) 列表切块，多进程并行执行 node --batch
        pairs: [(in_path, out_path), ...]
        返回 (ok_count, failed_pairs)
        """
        if not pairs:
            return 0, []
        if not self.available:
            return 0, list(pairs)

        # 每块至少 120 个文件，块数不超过 并发×4，避免频繁启动 node
        min_chunk = 120
        nchunks = max(1, min(workers * 4, (len(pairs) + min_chunk - 1) // min_chunk))
        size = max(1, (len(pairs) + nchunks - 1) // nchunks)
        chunks = [pairs[i:i + size] for i in range(0, len(pairs), size)]

        tmpdir = tempfile.mkdtemp(prefix="mxd_deob_")
        jobs = []
        try:
            for ci, chunk in enumerate(chunks):
                lst = os.path.join(tmpdir, f"list_{ci}.txt")
                with open(lst, "w", encoding="utf-8") as fh:
                    fh.write("\n".join(f"{a}\t{b}" for a, b in chunk))
                jobs.append((lst, chunk))

            failed = []
            done = 0
            lock = threading.Lock()

            def work(job):
                nonlocal done
                lst, chunk = job
                try:
                    r = subprocess.run(
                        [self.node, self.bundle, "--batch", lst],
                        capture_output=True, text=True, timeout=3600,
                        encoding="utf-8", errors="replace",
                    )
                    out = (r.stdout or "") + (r.stderr or "")
                    bad = {}
                    for line in out.splitlines():
                        if line.startswith("FAIL\t"):
                            parts = line.split("\t")
                            if len(parts) >= 2:
                                bad[parts[1]] = parts[2] if len(parts) > 2 else "unknown"
                    with lock:
                        for a, b in chunk:
                            if a in bad or not os.path.exists(b):
                                failed.append((a, b))
                except Exception as e:
                    with lock:
                        failed.extend(chunk)
                finally:
                    with lock:
                        done += len(chunk)
                        if on_progress:
                            on_progress(done, len(pairs))

            with ThreadPoolExecutor(max_workers=workers) as ex:
                list(ex.map(work, jobs))

            return len(pairs) - len(failed), failed
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


def process_one(deob: Deobfuscator, jse_path: Path, out_dir: Path,
                do_decrypt: bool, do_deob: bool) -> list:
    """处理单个 .jse（单文件模式），输出统一为 <名>.js"""
    logs = []
    stem = jse_path.stem
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"{stem}.js"

    try:
        raw = jse_path.read_bytes()
        plain = decrypt_bytes(raw)
    except EmptyScript as e:
        return [("SKIP", f"{jse_path.name}: 跳过（{e}）")]
    except Exception as e:
        return [("ERR", f"{jse_path.name}: 解密失败（可能不是有效的 .jse） {e}")]

    if not do_deob:
        target.write_bytes(plain)
        logs.append(("OK", f"解密 → {target.name} ({len(plain)} B)"))
        return logs

    if not deob.available:
        target.write_bytes(plain)
        logs.append(("ERR", "去混淆不可用（缺少内置 Node 引擎），已仅输出解密结果"))
        return logs

    tmp_in = out_dir / f".{stem}.raw.tmp"
    tmp_in.write_bytes(plain)
    try:
        ok, out = deob.run(str(tmp_in), str(target))
        if ok:
            logs.append(("OK", f"去混淆 → {target.name} ({target.stat().st_size} B)"))
        else:
            target.write_bytes(plain)
            logs.append(("ERR", f"{jse_path.name}: 去混淆失败，已退回输出解密结果 {out.strip()[:160]}"))
    finally:
        try:
            tmp_in.unlink()
        except Exception:
            pass
    return logs


class App:
    def __init__(self, root):
        self.root = root
        self.deob = Deobfuscator()
        self.q = queue.Queue()
        self.busy = False

        root.title("MXD186 脚本解密 / 去混淆工具")
        root.geometry("900x690")
        root.minsize(780, 580)
        root.configure(bg=BG)

        self._style()
        self._build()
        self._setup_dnd()
        self.root.after(120, self._drain)
        self._log("OK", f"Node 引擎: {self.deob.node or '未找到'}")
        self._log("OK", f"反混淆器: {'已就绪' if os.path.exists(self.deob.bundle) else '缺失'}")
        self._log("INFO", "拖拽支持: " + ("已启用" if HAS_DND else "不可用")
                  + f" | 逻辑核数 {CPU}，批量默认并发 {DEFAULT_WORKERS}")
        if not self.deob.available:
            self._log("ERR", "警告：去混淆功能不可用（缺少 node.exe 或 deob_bundle.js）")

    # ---------- 样式 ----------
    def _style(self):
        st = ttk.Style()
        try:
            st.theme_use("clam")
        except Exception:
            pass
        st.configure(".", background=BG, foreground=TXT, fieldbackground=PANEL2,
                     bordercolor=LINE, lightcolor=LINE, darkcolor=LINE)
        st.configure("TNotebook", background=BG, borderwidth=0)
        st.configure("TNotebook.Tab", background=PANEL, foreground=SUB,
                     padding=(18, 8), borderwidth=0)
        st.map("TNotebook.Tab", background=[("selected", PANEL2)],
               foreground=[("selected", ACCENT)])
        st.configure("TFrame", background=PANEL)
        st.configure("TLabel", background=PANEL, foreground=TXT)
        st.configure("Sub.TLabel", background=PANEL, foreground=SUB)
        st.configure("TCheckbutton", background=PANEL, foreground=TXT)
        st.map("TCheckbutton", background=[("active", PANEL)])
        st.configure("TEntry", fieldbackground=PANEL2, foreground=TXT,
                     insertcolor=TXT, bordercolor=LINE)
        st.configure("TSpinbox", fieldbackground=PANEL2, foreground=TXT,
                     insertcolor=TXT, bordercolor=LINE, arrowcolor=TXT)
        st.configure("TButton", background=PANEL2, foreground=TXT, borderwidth=0, padding=(12, 6))
        st.map("TButton", background=[("active", "#2c3946")])
        st.configure("Accent.TButton", background=ACCENT, foreground="#04121f")
        st.map("Accent.TButton", background=[("active", "#6cb3ff")])
        st.configure("Horizontal.TProgressbar", background=ACCENT, troughcolor=PANEL2,
                     bordercolor=PANEL2, lightcolor=ACCENT, darkcolor=ACCENT)

    # ---------- 布局 ----------
    def _build(self):
        head = tk.Frame(self.root, bg=BG)
        head.pack(fill="x", padx=16, pady=(14, 4))
        tk.Label(head, text="MXD186 脚本解密 / 去混淆工具", bg=BG, fg=TXT,
                 font=("Microsoft YaHei", 14, "bold")).pack(anchor="w")
        tk.Label(head, text="AES 解密（.jse → .js） + 反混淆（混淆代码 → 可读源码），输出统一为 <名>.js",
                 bg=BG, fg=SUB, font=("Microsoft YaHei", 9)).pack(anchor="w")

        self.hint = tk.Label(self.root, text="", bg=BG, fg=ACCENT,
                             font=("Microsoft YaHei", 9, "bold"))
        self.hint.pack(fill="x", padx=16)
        if HAS_DND:
            self.hint.configure(text="↓ 支持把 .jse 文件或文件夹直接拖入窗口 ↓")

        self.nb = ttk.Notebook(self.root)
        self.nb.pack(fill="both", expand=True, padx=16, pady=6)

        self.tab_single = ttk.Frame(self.nb, padding=16)
        self.tab_batch = ttk.Frame(self.nb, padding=16)
        self.nb.add(self.tab_single, text="  单个文件  ")
        self.nb.add(self.tab_batch, text="  批量文件夹  ")

        self._build_single()
        self._build_batch()

        logf = tk.Frame(self.root, bg=BG)
        logf.pack(fill="both", expand=True, padx=16, pady=(4, 14))
        tk.Label(logf, text="运行日志", bg=BG, fg=SUB,
                 font=("Microsoft YaHei", 9)).pack(anchor="w")
        box = tk.Frame(logf, bg=PANEL)
        box.pack(fill="both", expand=True, pady=4)
        self.log = tk.Text(box, bg="#0b0f14", fg=TXT, insertbackground=TXT,
                           font=("Consolas", 9), relief="flat", wrap="none",
                           height=10, padx=10, pady=8)
        sb = ttk.Scrollbar(box, orient="vertical", command=self.log.yview)
        self.log.configure(yscrollcommand=sb.set)
        self.log.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.log.tag_config("OK", foreground=OK)
        self.log.tag_config("ERR", foreground=ERR)
        self.log.tag_config("INFO", foreground=SUB)

    def _row(self, parent, label):
        f = ttk.Frame(parent)
        f.pack(fill="x", pady=5)
        ttk.Label(f, text=label, width=12, style="Sub.TLabel").pack(side="left")
        return f

    def _build_single(self):
        p = self.tab_single

        f = self._row(p, "jse 文件")
        self.s_file = tk.StringVar()
        self.e_file = ttk.Entry(f, textvariable=self.s_file)
        self.e_file.pack(side="left", fill="x", expand=True, padx=6)
        ttk.Button(f, text="选择文件…", command=self._pick_file).pack(side="left")

        f = self._row(p, "输出目录")
        self.s_out = tk.StringVar()
        self.e_sout = ttk.Entry(f, textvariable=self.s_out)
        self.e_sout.pack(side="left", fill="x", expand=True, padx=6)
        ttk.Button(f, text="选择目录…", command=lambda: self._pick_dir(self.s_out)).pack(side="left")

        f = self._row(p, "选项")
        self.s_dec = tk.BooleanVar(value=True)
        self.s_deob = tk.BooleanVar(value=True)
        ttk.Checkbutton(f, text="解密", variable=self.s_dec).pack(side="left")
        ttk.Checkbutton(f, text="去混淆", variable=self.s_deob).pack(side="left", padx=(14, 0))
        ttk.Label(f, text="（输出均为 <名>.js；两者同时勾选时输出可读版）",
                  style="Sub.TLabel").pack(side="left", padx=(12, 0))

        f = ttk.Frame(p)
        f.pack(fill="x", pady=16)
        ttk.Button(f, text="开始处理", style="Accent.TButton",
                   command=self._run_single).pack(side="left")
        ttk.Label(f, text="（不填输出目录则输出到 jse 同目录）", style="Sub.TLabel").pack(side="left", padx=10)

    def _build_batch(self):
        p = self.tab_batch

        f = self._row(p, "输入文件夹")
        self.b_dir = tk.StringVar()
        self.e_bdir = ttk.Entry(f, textvariable=self.b_dir)
        self.e_bdir.pack(side="left", fill="x", expand=True, padx=6)
        ttk.Button(f, text="选择目录…", command=self._pick_dir_in).pack(side="left")

        f = self._row(p, "输出文件夹")
        self.b_out = tk.StringVar()
        self.e_bout = ttk.Entry(f, textvariable=self.b_out)
        self.e_bout.pack(side="left", fill="x", expand=True, padx=6)
        ttk.Button(f, text="选择目录…", command=lambda: self._pick_dir(self.b_out)).pack(side="left")

        f = self._row(p, "选项")
        self.b_rec = tk.BooleanVar(value=True)
        self.b_dec = tk.BooleanVar(value=True)
        self.b_deob = tk.BooleanVar(value=True)
        self.b_workers = tk.IntVar(value=DEFAULT_WORKERS)
        ttk.Checkbutton(f, text="包含子文件夹", variable=self.b_rec).pack(side="left")
        ttk.Checkbutton(f, text="解密", variable=self.b_dec).pack(side="left", padx=(14, 0))
        ttk.Checkbutton(f, text="去混淆", variable=self.b_deob).pack(side="left", padx=(14, 0))
        ttk.Label(f, text="并发", style="Sub.TLabel").pack(side="left", padx=(14, 2))
        ttk.Spinbox(f, from_=1, to=max(16, CPU), width=4,
                    textvariable=self.b_workers).pack(side="left")

        f = ttk.Frame(p)
        f.pack(fill="x", pady=16)
        ttk.Button(f, text="开始批量处理", style="Accent.TButton",
                   command=self._run_batch).pack(side="left")
        self.pb = ttk.Progressbar(p, mode="determinate")
        self.pb.pack(fill="x", pady=(4, 4))
        self.status = ttk.Label(p, text="就绪", style="Sub.TLabel")
        self.status.pack(anchor="w")

    # ---------- 拖拽 ----------
    def _setup_dnd(self):
        if not HAS_DND:
            return
        self._register(self.root, None)
        self._register(self.tab_single, None)
        self._register(self.tab_batch, None)
        self._register(self.e_file, "single")
        self._register(self.e_sout, "out")
        self._register(self.e_bdir, "batch")
        self._register(self.e_bout, "out")
        for w in (self.root, self.tab_single, self.tab_batch, self.e_file, self.e_bdir):
            try:
                w.dnd_bind("<<DropEnter>>", lambda e: self.hint.configure(fg="#7cf0c0"))
                w.dnd_bind("<<DropLeave>>", lambda e: self.hint.configure(fg=ACCENT))
            except Exception:
                pass

    def _register(self, widget, target):
        try:
            widget.drop_target_register(DND_FILES)
            widget.dnd_bind("<<Drop>>", lambda e, t=target: self._on_drop(e, t))
        except Exception:
            pass

    def _parse_drop(self, data) -> list:
        try:
            paths = list(self.root.tk.splitlist(data))
        except Exception:
            paths = [data]
        return [p for p in (str(x).strip().strip("{}") for x in paths) if os.path.exists(p)]

    def _on_drop(self, event, target):
        paths = self._parse_drop(event.data)
        if not paths:
            return
        dirs = [p for p in paths if os.path.isdir(p)]
        files = [p for p in paths if os.path.isfile(p)]

        def set_single(p):
            self.s_file.set(p)
            if not self.s_out.get():
                self.s_out.set(os.path.dirname(p))
            self.nb.select(self.tab_single)

        def set_batch(d):
            self.b_dir.set(d)
            if not self.b_out.get():
                self.b_out.set(d.rstrip("/\\") + "_解密去混淆")
            self.nb.select(self.tab_batch)

        if target == "single":
            set_single(files[0] if files else paths[0]); return
        if target == "batch":
            set_batch(dirs[0] if dirs else os.path.dirname(files[0])); return
        if target == "out":
            return
        if dirs:
            set_batch(dirs[0])
        elif len(files) == 1:
            set_single(files[0])
        elif files:
            set_batch(os.path.dirname(files[0]))

    # ---------- 交互 ----------
    def _pick_file(self):
        p = filedialog.askopenfilename(title="选择 .jse 文件",
                                       filetypes=[("加密脚本", "*.jse"), ("所有文件", "*.*")])
        if p:
            self.s_file.set(p)
            if not self.s_out.get():
                self.s_out.set(os.path.dirname(p))

    def _pick_dir(self, var):
        p = filedialog.askdirectory(title="选择输出目录")
        if p:
            var.set(p)

    def _pick_dir_in(self):
        p = filedialog.askdirectory(title="选择输入文件夹")
        if p:
            self.b_dir.set(p)
            if not self.b_out.get():
                self.b_out.set(p.rstrip("/\\") + "_解密去混淆")

    # ---------- 日志 ----------
    def _log(self, tag, msg):
        self.q.put((tag, msg))

    def _drain(self):
        try:
            while True:
                tag, msg = self.q.get_nowait()
                self.log.insert("end", msg + "\n", tag)
                self.log.see("end")
        except queue.Empty:
            pass
        self.root.after(120, self._drain)

    # ---------- 单文件 ----------
    def _run_single(self):
        if self.busy:
            return
        src = self.s_file.get().strip()
        if not src or not os.path.isfile(src):
            messagebox.showwarning("提示", "请先选择一个 .jse 文件")
            return
        if not self.s_dec.get() and not self.s_deob.get():
            messagebox.showwarning("提示", "请至少勾选「解密」或「去混淆」")
            return
        out = self.s_out.get().strip() or os.path.dirname(src)

        def work():
            self.busy = True
            self._log("INFO", f"—— 单文件处理: {os.path.basename(src)} ——")
            try:
                for tag, m in process_one(self.deob, Path(src), Path(out),
                                          self.s_dec.get(), self.s_deob.get()):
                    self._log(tag, m)
                self._log("INFO", "完成。")
            except Exception:
                self._log("ERR", traceback.format_exc(limit=2))
            self.busy = False

        threading.Thread(target=work, daemon=True).start()

    # ---------- 批量 ----------
    def _run_batch(self):
        if self.busy:
            return
        d = self.b_dir.get().strip()
        if not d or not os.path.isdir(d):
            messagebox.showwarning("提示", "请先选择输入文件夹")
            return
        if not self.b_dec.get() and not self.b_deob.get():
            messagebox.showwarning("提示", "请至少勾选「解密」或「去混淆」")
            return
        out = self.b_out.get().strip() or (d.rstrip("/\\") + "_解密去混淆")
        workers = max(1, int(self.b_workers.get() or DEFAULT_WORKERS))
        do_deob = self.b_deob.get()

        def work():
            self.busy = True
            self.pb["value"] = 0
            base = Path(d)
            files = list(base.rglob("*.jse") if self.b_rec.get() else base.glob("*.jse"))
            total = len(files)
            if total == 0:
                self._log("ERR", f"未在 {d} 找到 .jse 文件")
                self.busy = False
                return
            self._log("INFO", f"—— 批量处理: 共 {total} 个 .jse（并发 {workers}）——")
            self.pb["maximum"] = total
            self.status.configure(text=f"0 / {total}")

            tmpdir = tempfile.mkdtemp(prefix="mxd_in_")
            pairs, errs, skips = [], [], []
            try:
                # 阶段1：解密
                for f in files:
                    rel = f.relative_to(base).parent
                    tdir = Path(out) / rel
                    tdir.mkdir(parents=True, exist_ok=True)
                    target = tdir / f"{f.stem}.js"
                    try:
                        plain = decrypt_bytes(f.read_bytes())
                    except EmptyScript as e:
                        skips.append((str(rel / f.name), str(e)))
                        continue
                    except Exception as e:
                        errs.append((str(rel / f.name), f"解密失败 {e}"))
                        continue
                    if not do_deob:
                        target.write_bytes(plain)
                        continue
                    tin = Path(tmpdir) / (str(len(pairs)) + ".tmpin")
                    tin.write_bytes(plain)
                    pairs.append((str(tin), str(target)))

                self._log("INFO", f"解密完成：可去混淆 {len(pairs)} 个，跳过 {len(skips)} 个，失败 {len(errs)} 个")
                for n, m in skips[:20]:
                    self._log("INFO", f"跳过 {n}（{m}）")

                # 阶段2：并行去混淆
                if do_deob and pairs:
                    def on_prog(done, tot):
                        self.pb["value"] = done
                        self.status.configure(text=f"去混淆 {done} / {tot}")
                    okc, failed = self.deob.run_batch(pairs, workers, on_prog)
                    # 失败的回退为解密结果
                    for a, b in failed:
                        try:
                            shutil.copyfile(a, b)
                        except Exception:
                            pass
                    self._log("OK" if not failed else "ERR",
                              f"去混淆完成：成功 {okc}，失败 {len(failed)}（已回退为解密结果）")
                    for a, b in failed[:50]:
                        errs.append((os.path.basename(b), "去混淆失败"))

                self.pb["value"] = total
                ok_final = total - len(errs) - len(skips)
                self.status.configure(text=f"完成：成功 {ok_final} / 跳过 {len(skips)} / 失败 {len(errs)}")
                self._log("OK" if not errs else "ERR",
                          f"批量完成：成功 {ok_final}，跳过 {len(skips)}，失败 {len(errs)}，输出目录 {out}")
                for name, msg in errs[:100]:
                    self._log("ERR", f"{name} : {msg}")
                if errs:
                    try:
                        (Path(out) / "_errors.txt").write_text(
                            "\n".join(f"{n}\t{m}" for n, m in errs), encoding="utf-8")
                        self._log("INFO", f"错误清单已写入 {Path(out) / '_errors.txt'}")
                    except Exception:
                        pass
            except Exception:
                self._log("ERR", traceback.format_exc(limit=3))
            finally:
                shutil.rmtree(tmpdir, ignore_errors=True)
                self.busy = False

        threading.Thread(target=work, daemon=True).start()


def run_batch_cli(deob, src, out, rec, do_deob, workers, log_path=None):
    p = Path(src)
    if p.is_dir():
        files = list(p.rglob("*.jse") if rec else p.glob("*.jse"))
        base = p
    else:
        files = [p]
        base = p.parent
    lines = [f"ENV | dragdrop={HAS_DND} | node={bool(deob.node)} | bundle={os.path.exists(deob.bundle)} "
             f"| frozen={getattr(sys,'frozen',False)} | cpu={CPU} | workers={workers}"]
    tmpdir = tempfile.mkdtemp(prefix="mxd_in_")
    pairs, errs, skips = [], [], []
    try:
        for f in files:
            rel = f.relative_to(base).parent if f.parent != base else Path(".")
            tdir = Path(out) / rel
            tdir.mkdir(parents=True, exist_ok=True)
            target = tdir / f"{f.stem}.js"
            try:
                plain = decrypt_bytes(f.read_bytes())
            except EmptyScript as e:
                skips.append((str(rel / f.name), str(e)))
                continue
            except Exception as e:
                errs.append((str(rel / f.name), f"解密失败 {e}"))
                continue
            if not do_deob:
                target.write_bytes(plain)
                continue
            tin = Path(tmpdir) / (str(len(pairs)) + ".tmpin")
            tin.write_bytes(plain)
            pairs.append((str(tin), str(target)))
        lines.append(f"DECRYPT ok={len(pairs)} skip={len(skips)} err={len(errs)}")
        if do_deob and pairs:
            okc, failed = deob.run_batch(pairs, workers)
            for a, b in failed:
                try:
                    shutil.copyfile(a, b)
                except Exception:
                    pass
                errs.append((os.path.basename(b), "去混淆失败"))
            lines.append(f"DEOB ok={okc} err={len(failed)}")
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
    lines.append(f"TOTAL ok={len(files)-len(errs)-len(skips)} skip={len(skips)} err={len(errs)} files={len(files)}")
    for n, m in skips:
        lines.append(f"SKIP | {n} | {m}")
    for n, m in errs:
        lines.append(f"ERR | {n} | {m}")
    text = "\n".join(lines)
    if log_path:
        Path(log_path).write_text(text, encoding="utf-8")
    else:
        try:
            (Path(out) / "_cli_log.txt").write_text(text, encoding="utf-8")
        except Exception:
            pass
    return len(errs)


def cli_mode(argv) -> int:
    """命令行模式：
    MXD186脚本工具.exe --cli <输入.jse或文件夹> <输出目录> [--rec] [--no-deob] [--workers N] [--log 文件]
    """
    args = argv[1:]
    if not args or args[0] != "--cli":
        return -1
    rest = args[1:]
    rec = "--rec" in rest
    do_deob = "--no-deob" not in rest
    workers = DEFAULT_WORKERS
    log_path = None
    if "--workers" in rest:
        i = rest.index("--workers")
        if i + 1 < len(rest):
            try:
                workers = max(1, int(rest[i + 1]))
            except Exception:
                pass
    if "--log" in rest:
        i = rest.index("--log")
        if i + 1 < len(rest):
            log_path = rest[i + 1]
    flags_with_value = {"--workers", "--log"}
    pos, skip = [], False
    for a in rest:
        if skip:
            skip = False
            continue
        if a in flags_with_value:
            skip = True
            continue
        if a.startswith("--"):
            continue
        pos.append(a)
    if len(pos) < 2:
        return 2
    deob = Deobfuscator()
    return 0 if run_batch_cli(deob, pos[0], pos[1], rec, do_deob, workers, log_path) >= 0 else 1


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--cli":
        sys.exit(cli_mode(sys.argv))
    if AES is None:
        print("缺少 pycryptodome 依赖")
    root = TkinterDnD.Tk() if HAS_DND else tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
