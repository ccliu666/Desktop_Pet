@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo 正在安装依赖（国内网络已配置清华镜像源，首次约 2~5 分钟）...
python -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
echo.
echo 安装完成！下一步：
echo   1. 在 character\config.json 中填写 DeepSeek 与讯飞的 Key
echo   2. 双击 start.bat 启动小云宝
echo.
pause
