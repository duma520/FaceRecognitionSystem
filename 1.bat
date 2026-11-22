@echo off
chcp 65001 >nul
rem ============================================================
rem 【日常运行 / 调试入口】 1.bat   （位于项目根目录，v2.1.2）
rem ------------------------------------------------------------
rem 默认【不使用虚拟环境】，直接用系统 Python 运行主程序。
rem 本机实测：系统 Python 3.10.11 与 venv 的依赖完全一致，均可直接运行
rem          （insightface / onnxruntime / opencv / PyQt5 / pywin32 / pysocks 等均无缺失）
rem
rem 想改回虚拟环境：把下面的 USE_VENV 改成 1 即可，其它不用动。
rem 想固定用某个解释器：取消 PYEXE 那行的注释并填上路径。
rem 本脚本始终以"自己所在目录"（项目根目录）为工作目录，从任何位置调用都正确。
rem ============================================================
cd /d "%~dp0"

set "USE_VENV=0"
set "PYEXE="
rem set "PYEXE=D:\Program Files\Python310\python.exe"

rem ---------- 1) 可选：启用虚拟环境 ----------
if "%USE_VENV%"=="1" (
    if exist "venv\Scripts\activate.bat" (
        echo [1.bat] 使用虚拟环境 venv ...
        call "venv\Scripts\activate.bat"
    ) else (
        echo [1.bat] 警告: 未找到 venv，改用系统 python ...
        echo          如需新建虚拟环境: python -m venv venv
    )
)

rem ---------- 2) 选定解释器 ----------
if not defined PYEXE set "PYEXE=python"

rem ---------- 3) 轻量校验：解释器可用即可 ----------
rem 说明：这里刻意不做 insightface/cv2 这类重量级 import（那会拖慢每次启动好几秒），
rem       只确认 python 能跑起来（同时可挡住 Windows 商店的 python 占位程序）。
"%PYEXE%" -c "import sys;raise SystemExit(0 if sys.version_info[0]==3 else 1)" >nul 2>&1
if errorlevel 1 (
    echo.
    echo [1.bat] 错误: 找不到可用的 Python 解释器（当前为 %PYEXE%）。
    echo.
    echo   解决办法任选其一:
    echo     1. 安装 Python 3.10（勾选 Add to PATH）后重试;
    echo     2. 在本脚本里指定解释器路径，例如:
    echo            set "PYEXE=D:\Program Files\Python310\python.exe"
    echo     3. 若本机已建好虚拟环境: 把 USE_VENV 改成 1。
    echo.
    pause
    exit /b 1
)

rem ---------- 4) 启动主程序 ----------
echo [1.bat] 启动主程序 FaceRecognitionSystem.py （解释器: %PYEXE%）...
"%PYEXE%" FaceRecognitionSystem.py

rem 调试时不要让窗口一闪而过：只有异常退出才停留
if errorlevel 1 (
    echo.
    echo [1.bat] 程序异常退出，错误码 %errorlevel%
    echo         若提示缺少模块，请执行:
    echo             %PYEXE% -m pip install -r build\requirements.txt
    echo         若仍希望隔离环境，可执行 python -m venv venv 并把本脚本 USE_VENV 改成 1。
    pause
)
