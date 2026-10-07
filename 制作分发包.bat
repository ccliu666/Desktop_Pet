@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo ============================================
echo   制作小云宝分发包（发给他人的免安装版本）
echo ============================================
echo.

if not exist "dist\小云宝\小云宝.exe" (
    echo [错误] 没找到 dist\小云宝\小云宝.exe，请先打包：
    echo   pyinstaller --noconfirm --noconsole --onedir --name 小云宝 --icon "character\assets\小云宝.ico" --add-data "character\img;img" --add-data "character\fx;fx" --exclude-module PyQt5 --exclude-module PyQt6 --exclude-module tkinter src\main.py
    pause
    exit /b 1
)

set OUT=分发\小云宝课堂版
if exist "%OUT%" rmdir /s /q "%OUT%"
mkdir "%OUT%"

echo [1/5] 复制程序文件...
xcopy /e /i /q "dist\小云宝" "%OUT%" >nul
del /q "%OUT%\pet_pos.json" 2>nul
del /q "%OUT%\smoke*.png" 2>nul

echo [2/5] 写入空白配置（不含明文 Key）...
copy /y "character\config.example.json" "%OUT%\config.json" >nul

echo [3/5] 生成加密 Key 文件 keys.dat...
python scripts\make_keys.py "%OUT%"
if errorlevel 1 (
    echo [警告] keys.dat 生成失败，请检查 character\config.json 里的 Key
)

echo [4/5] 复制使用指南与开机自启工具...
copy /y "docs\使用指南.md" "%OUT%\使用指南.md" >nul
copy /y "设置开机自启.bat" "%OUT%\" >nul
copy /y "取消开机自启.bat" "%OUT%\" >nul

echo.
echo 完成！分发包位于： %OUT%
echo 把这个文件夹压缩成 zip 发给对方即可，对方解压后双击 小云宝.exe 使用。
echo.
echo [提示] 点位授权：本包默认不含 license.dat——对方首次打开会弹窗显示机器码，
echo        按 使用指南.md 第四节的流程办理（或打包前用 生成授权.bat 预先生成）。
echo.
pause
