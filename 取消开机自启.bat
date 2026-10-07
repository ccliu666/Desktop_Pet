@echo off
chcp 65001 >nul
del "%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\XiaoYunBao.lnk" 2>nul
if exist "%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\XiaoYunBao.lnk" (
  echo 取消失败，请手动删除启动文件夹里的 XiaoYunBao 快捷方式。
) else (
  echo 已取消开机自启动。
)
pause
