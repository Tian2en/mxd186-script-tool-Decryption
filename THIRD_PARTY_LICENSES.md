# 第三方组件与许可

本项目在源码与打包产物中使用了以下第三方组件，特此致谢。

## 运行时依赖

| 组件 | 用途 | 许可 |
|---|---|---|
| [Python](https://www.python.org/) | 运行环境 | PSF License |
| [Tcl/Tk (tkinter)](https://www.tcl.tk/) | 图形界面 | Tcl/Tk License (BSD 风格) |
| [pycryptodome](https://www.pycryptodome.org/) | AES 解密 | BSD 2-Clause / Public Domain |
| [tkinterdnd2](https://github.com/pmgagne/tkinterdnd2) | 拖拽支持（含 TkDND） | MIT |
| [Node.js](https://nodejs.org/) | 反混淆器运行环境 | MIT |
| [@babel/parser](https://babeljs.io/) | JS 语法解析 | MIT |
| [@babel/traverse](https://babeljs.io/) | AST 遍历 | MIT |
| [@babel/generator](https://babeljs.io/) | 代码生成 | MIT |
| [@babel/types](https://babeljs.io/) | AST 类型工具 | MIT |

## 构建工具

| 组件 | 用途 | 许可 |
|---|---|---|
| [PyInstaller](https://pyinstaller.org/) | 打包为单文件 exe | GPL-2.0-or-later（含允许打包专有程序的例外条款） |
| [Rollup](https://rollupjs.org/) | 打包反混淆器 | MIT |

## 说明

- `assets/deob_bundle.js` 是由 `src/deobfuscator.js` 经 Rollup 打包生成的产物，
  其中内联了上表中 `@babel/*` 各包（均为 MIT 许可）。
- 发布打包产物（exe）时，请一并保留本文件与各组件原始许可声明。
- 本项目自身代码以 [MIT](LICENSE) 许可发布。
