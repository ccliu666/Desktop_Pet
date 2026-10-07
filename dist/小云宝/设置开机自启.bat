@echo off
chcp 65001 >nul
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -Command "$exe=(Get-ChildItem -Filter *.exe | Select-Object -First 1).FullName; $s=(New-Object -ComObject WScript.Shell).CreateShortcut([Environment]::GetFolderPath('Startup')+'\XiaoYunBao.lnk'); $s.TargetPath=$exe; $s.WorkingDirectory=(Get-Location).Path; $s.Description='XiaoYunBao AI'; $s.Save()"
if errorlevel 1 (
  echo 设置失败，请检查文件夹权限后重试。
) else (
  echo 已设置开机自启动：下次开机小云宝会自动出现。
  echo 取消方法：双击「取消开机自启.bat」。
)
pause
