@echo off
chcp 65001 >nul
rem ============================================================
rem 【PyInstaller 一键打包 - 主程序】 0.bat   （位于项目根目录，v2.1.1）
rem ------------------------------------------------------------
rem 用户要求：编译主程序的脚本放在程序目录，方便直接双击编译。
rem 需求4：主程序 FaceRecognitionSystem.py 就是最终发布版，唯一编译入口。
rem 产物：     dist\FaceRecognitionSystem\FaceRecognitionSystem.exe
rem 中间目录： build\_work （绝不能用 build 本身，那是脚手架目录）
rem 脚手架：   build\FaceRecognitionSystem.spec（统一维护，不再临时生成 spec）
rem ============================================================
cd /d "%~dp0"

if not exist "build\FaceRecognitionSystem.spec" (
    echo [0.bat] 错误: 找不到 build\FaceRecognitionSystem.spec，无法打包。
    pause
    exit /b 1
)

echo [1/5] 清理旧的打包产物...
rmdir /s /q "build\_work" 2>nul
rmdir /s /q dist 2>nul

echo [2/5] 创建运行时数据目录...
if not exist models mkdir models
if not exist faces mkdir faces
if not exist unknown_faces mkdir unknown_faces
if not exist datasets mkdir datasets
if not exist logs mkdir logs

echo [3/5] 检查字体文件...
if not exist simhei.ttf (
    echo    警告: simhei.ttf 不存在，尝试从系统字体目录复制...
    copy /y C:\Windows\Fonts\simhei.ttf . 2>nul
)

echo [4/5] 检查 .env（API Key / 数据库密码等敏感配置，需求8）...
if not exist .env (
    echo    提示: 未找到 .env，正在从 .env.example 生成...
    if exist .env.example copy /y .env.example .env 2>nul
)

echo [5/5] 开始打包（PyInstaller + build\FaceRecognitionSystem.spec）...
python -m PyInstaller --noconfirm --clean ^
    --workpath "build\_work" ^
    --distpath dist ^
    "build\FaceRecognitionSystem.spec"

if %errorlevel% neq 0 (
    echo.
    echo 打包失败！错误码：%errorlevel%
    pause
    exit /b %errorlevel%
)

echo.
echo ========================================
echo  打包完成（主程序）
echo  程序位置: dist\FaceRecognitionSystem\
echo  启动脚本: build\run.bat
echo ========================================
pause
