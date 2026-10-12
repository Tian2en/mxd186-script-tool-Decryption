# MXD186 脚本解密 / 去混淆工具

一个用于 **冒险岛（MapleStory）v186 私服服务端脚本** 的批量解密与反混淆工具。

- **解密**：把加密的 `.jse` 脚本还原为可加载的 `.js`
- **去混淆**：把 `javascript-obfuscator` 混淆过的代码还原成人类可读的源码
- **批量**：支持整个目录递归处理，多进程并行，实测 **约 0.13 秒/文件**
- **界面**：图形界面（tkinter），支持拖拽文件/文件夹；同时提供命令行模式

> ⚠️ **免责声明**
> 本项目仅供**学习研究**与**服务端运维**使用。请勿用于任何侵犯他人权益的用途。
> 使用者需自行承担因使用本工具产生的一切后果。

---

## 效果对比

```js
// 去混淆前（混淆态）
var a0v=['DgvZDa','5AsC5ywj5lI256wE6zQq',...];var a0V=function(u,j,w,l){...};
function get(){var N=function(u,j,w,l){return a0O(l-0x12a,u);};return arr[Math[N(0x237,...)](...)];}
var arr=[a0V(-0x2a8,-0x2ac,-0x29f,-0x2a1),'\xce\xb6\xb6\xf9\xb1\xe8\xd7\xd3\xc3\xc3\xc3\xc3',...];

// 去混淆后
function get() {
  return arr[Math["floor"](Math['random']() * arr['length'])];
}
var arr = ["溪姐的大跟班", "睡觉的衣羊", "味儿辫子妹妹", ...];
```

| 文件 | 原始 `.jse` | 解密后 | 去混淆后 |
|---|---:|---:|---:|
| 反应堆/100000 | 5.9 KB | 4.4 KB | **39 B** |
| 道具/2430005 | 6.6 KB | 4.9 KB | **287 B** |
| 特殊/AI信息菜单 | 25.8 KB | 19.3 KB | **7.4 KB** |
| 事件/Boss_比睿山_浓姬 | 33.0 KB | 24.7 KB | **11.1 KB** |

---

## 技术原理

### 1. 解密（AES + Base64）

服务端脚本以 **AES-128 / ECB / PKCS5Padding** 加密后再做 **标准 Base64** 编码。

密钥并非直接硬编码，而是由服务端的「脚本密钥」经 Java 的 `KeyGenerator` 派生：

```java
KeyGenerator kg = KeyGenerator.getInstance("AES");
kg.init(128, new SecureRandom("RyZuxRfceVKJBGuwn0MTDIdz0NASMBRC".getBytes(UTF_8)));
SecretKeySpec key = new SecretKeySpec(kg.generateKey().getEncoded(), "AES");
```

本工具已将该派生结果固定为 16 字节密钥写死在源码里（`src/app.py` 的 `AES_KEY_HEX`），
因此**不需要 JRE** 即可解密。

> 想换密钥？直接改 `src/app.py` 里的 `AES_KEY_HEX`。

### 2. 去混淆（沙箱求值 + AST 常量折叠）

解密出来的 JS 仍是 `javascript-obfuscator` 混淆产物，结构为：

```
字符串数组 a0v[]  +  自定义 Base64 解码器 a0O()  +  数组轮转 IIFE  +  自防御代码
```

`src/deobfuscator.js` 的处理流程：

1. **沙箱求值**：用 `vm` 执行原代码，拿到全部字符串解码器函数
   （必须传入独立的 `console`，否则混淆代码的自防御会劫持宿主 console）
2. **收集局部包装函数**：`get()` 内部还存在 `var N = function(u,j,w,l){ return a0O(l-0x12a,u) }`
   这类转发函数，需在「全局 + 全部局部包装」的共享上下文中编译才能求值
3. **常量折叠**：把 `a0V(-0x2a8, ...)` 这类调用替换成解码后的字符串字面量；
   同时折叠字符串拼接、算术、`!![]` 等
4. **死代码清除**：删除数组轮转 IIFE、自防御调用、以及已失效的解码器与包装函数
5. **输出**：`@babel/generator` 生成格式化代码，数值统一转十进制

---

## 安装与构建

### 获取源码

```bash
git clone https://github.com/Tian2en/mxd186-script-tool-Decryption.git
cd mxd186-script-tool-Decryption
```

### 环境要求

- **Python 3.8+**（Windows 需带 tkinter）
- **Node.js 18+**（运行反混淆器）

### 直接运行源码

```bash
pip install -r requirements.txt
python src/app.py
```

> 运行前需要把 `node.exe` 放到项目根目录（或加入 PATH），因为反混淆器依赖 Node 运行时。

### 打包成单文件 exe

```bash
build\build.bat
```

脚本会自动：下载 Node 运行时 → 生成反混淆器 bundle → 用 PyInstaller 打包，
产物在 `dist\MXD186脚本工具.exe`。

---

## 使用方法

### 图形界面

双击 exe 打开，两个标签页：

- **单个文件**：选（或拖入）`.jse` → 选输出目录 → 勾选「解密 / 去混淆」→ 开始处理
- **批量文件夹**：选（或拖入）输入目录 → 输出目录 → 勾选选项与并发数 → 开始批量处理

支持把 `.jse` 文件或文件夹**直接拖进窗口**，会自动切到对应标签页。

### 命令行

```bash
MXD186脚本工具.exe --cli <输入.jse或文件夹> <输出目录> [选项]

选项：
  --rec          递归处理子文件夹
  --no-deob      只解密，不去混淆
  --workers N    并发进程数（默认 8）
  --log 文件     日志输出路径
```

示例：

```bash
# 批量递归处理整个脚本目录，10 并发
MXD186脚本工具.exe --cli "D:\Server\脚本" "D:\out" --rec --workers 10
```

### 输出命名

统一输出为 `<名称>.js`，批量模式保持原目录结构：

| 勾选 | 输出内容 |
|---|---|
| 只「解密」 | 解密结果（仍是混淆代码，服务端可直接加载） |
| 只「去混淆」 | 可读源码 |
| 两个都勾 | 可读源码（解密仅作中间步骤） |

### 异常处理

- **空文件（0 字节）** → 记为「跳过」，不算失败
- **非法 Base64 / 密文长度异常** → 记为「失败」，写入 `_errors.txt`
- **单个文件去混淆失败** → 自动回退输出解密结果，保证有产出

---

## 性能

| 版本 | 方式 | 速度 |
|---|---|---|
| v1.0 | 每个文件启动一次 Node | ~2.5 秒/文件 |
| **v1.2+** | 单进程批量队列 + 多进程并行 | **~0.13 秒/文件** |

实测：19347 个 `.jse`，10 并发，耗时 **24 分 46 秒**。

---

## 项目结构

```
.
├── src/
│   ├── app.py               # GUI + 解密 + 并行调度（Python / tkinter）
│   └── deobfuscator.js      # 反混淆器（Node / Babel）
├── assets/
│   └── deob_bundle.js       # 由 deobfuscator.js 经 rollup 打包生成
├── build/
│   ├── build.bat            # 一键打包
│   ├── fetch_node.py        # 下载 Node 运行时
│   ├── package.json         # rollup 依赖
│   └── rollup.config.mjs
├── docs/
│   └── 使用说明.md
├── .github/workflows/
│   └── release.yml          # 打 tag 自动构建并发布 Release
└── requirements.txt
```

### 重新生成反混淆器 bundle

改动 `src/deobfuscator.js` 后：

```bash
cd build
npm install
npm run bundle
```

---

## 已验证

- 常量数据表 **21** 个文件：解密 + 去混淆，数据与原服务端逐条一致
- 服务端脚本 **19347** 个文件：
  - 成功 **19346**，跳过 **1**（一个 0 字节的空占位文件），失败 **0**
  - 全部产出经 Node 引擎逐个编译检查：**0 空文件、0 语法错误**
- 抽样比对：去混淆结果与原混淆版本**行为逐条一致**（mock `cm`/`em` 记录调用序列）

---

## 第三方组件

见 [THIRD_PARTY_LICENSES.md](THIRD_PARTY_LICENSES.md)。

---

## License

[MIT](LICENSE)
