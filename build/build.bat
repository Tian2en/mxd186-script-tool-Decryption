@echo off
chcp 65001 >nul
setlocal

rem ============================================================
rem  MXD186 脚本工具 - 一键打包脚本
rem  产物: dist\MXD186脚本工具.exe
rem ============================================================

cd /d "%~dp0.."
echo [1/5] 工作目录: %CD%

where python >nul 2>nul
if errorlevel 1 (
    echo [错误] 未找到 python，请先安装 Python 3.8+ 并加入 PATH
    pause & exit /b 1
)

echo [2/5] 安装 Python 依赖...
python -m pip install -q -r requirements.txt || (echo [错误] 依赖安装失败 & pause & exit /b 1)

echo [3/5] 准备 Node 运行时...
if not exist "node.exe" (
    python build\fetch_node.py || (echo [错误] Node 下载失败 & pause & exit /b 1)
) else (
    echo   node.exe 已存在，跳过
)

echo [4/5] 检查反混淆器 bundle...
if not exist "assets\deob_bundle.js" (
    echo   未找到 assets\deob_bundle.js，尝试用 rollup 生成...
    pushd build
    call npm install || (echo [错误] npm install 失败 & popd & pause & exit /b 1)
    call npm run bundle || (echo [错误] rollup 打包失败 & popd & pause & exit /b 1)
    popd
)

echo [5/5] PyInstaller 打包...
rem 注意：--specpath 会改变相对路径的解析基准，因此 --add-data 必须用绝对路径
python -m PyInstaller --noconfirm --onefile --windowed ^
    --name "MXD186脚本工具" ^
    --add-data "%CD%\node.exe;." ^
    --add-data "%CD%\assets\deob_bundle.js;." ^
    --collect-all tkinterdnd2 ^
    --distpath "%CD%\dist" --workpath "%CD%\build\pyinstaller" --specpath "%CD%\build" ^
    "%CD%\src\app.py" || (echo [错误] 打包失败 & pause & exit /b 1)

echo.
echo ============================================================
echo  打包完成: %CD%\dist\MXD186脚本工具.exe
echo ============================================================
pause
