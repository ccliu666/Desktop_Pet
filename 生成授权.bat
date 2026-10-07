@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ============================================
echo   生成 / 追加点位授权文件 license.dat
echo ============================================
echo 对方在未授权电脑上打开小云宝.exe 时，弹窗里会显示机器码。
echo 对方把机器码发给你后，在下面输入（形如 A4BB-6D31-9F02）。
echo 一次添加多台：机器码用空格分隔。
echo 分次添加：已有 license.dat 会自动合并，原来的机器码会保留。
echo.
set /p CODES=请输入机器码：
if "%CODES%"=="" (
  echo 未输入任何机器码，已取消。
  pause
  exit /b 1
)
python scripts\make_license.py . %CODES%
pause
