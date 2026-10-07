@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ============================================
echo   生成点位授权文件 license.dat
echo ============================================
echo 对方在未授权电脑上打开小云宝.exe 时，弹窗里会显示机器码。
echo 对方把机器码发给你后，在下面输入（形如 A4BB-6D31-9F02）。
echo 多台机器的机器码用空格分隔。生成后把 license.dat 放进对方程序文件夹即可。
echo.
set /p CODES=请输入机器码：
if "%CODES%"=="" (
  echo 未输入任何机器码，已取消。
  pause
  exit /b 1
)
python scripts\make_license.py . %CODES%
pause
