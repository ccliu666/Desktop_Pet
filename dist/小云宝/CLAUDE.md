# 桌面小云宝 —— 项目交接文档（给下一台电脑上的 Claude）

> 本文件会被 Claude Code 自动加载。接手开发前通读一遍，关键决策和踩坑都在这里。

## 项目是什么

**幼儿园课堂 AI 语音助教**，部署在**希沃互动白板**（大屏）上。吉祥物「小云宝」是一朵矢量绘制的小白云，住在桌面上：散步、眨眼、睡觉、被戳、喂食；孩子按麦克风按钮或喊"小云宝"跟它对话，它用 Edge-TTS 语音回答。海云幼儿园使用。

- 技术栈：Python 3.12 + PySide6（Qt6，锁定 6.8.2）+ Edge-TTS（免费语音）+ DeepSeek（聊天）+ 讯飞（语音识别，已实测可用）
- 入口：`python src/main.py`（开发）/ `dist/小云宝/小云宝.exe`（部署，双击无黑框）
- 版本：v1.5（2026-10-07，点位授权 + 开机自启 + 节能唤醒 + 唤醒灵敏度可调）

## 当前状态（2026-09-30）

- ✅ 聊天：DeepSeek 流式回复 + 分句 + 气泡打字机 + 说完关气泡、输入框自动重开
- ✅ 人设：专业助教定位（2026-10-01 按用户要求改）：亲切专业的幼儿园老师风格、**自称"小云宝"不称老师**、称呼"大家/小朋友们"**不用单独"你"**、每句≤50 字、每次 3~5 句、音色换晓晓（zh-CN-XiaoxiaoNeural）；**自我介绍**（2026-10-02）必须说出全称"余杭区未来科技城海云幼儿园的AI助教小云宝"（提示词第 10 条）；调试样本用 `scripts/chat_probe.py`
- ✅ 行为修正（2026-10-01/02）：**取消自动入睡**（睡觉仅右键手动，之前 120 秒自动睡会在上课时冒 Zzz）；说话期间不眨眼/不打哈欠/不散步（`MonsterWidget.speaking` + Brain 待机计时联动）；睡觉时有人提问自动醒来；**自由移动默认关**（右键可开、状态记忆 pet_pos.json move 字段，拖拽与喂食不受影响）
- ✅ 界面开关（2026-10-01）：对话气泡**默认不显示**（config `classroom.show_bubble:false`，纯语音交互），右键「显示对话气泡」开关、状态记忆在 pet_pos.json 的 bubble 字段；双击宠物 = 打字输入框开↔关；右键「跟我聊天（打字）」改为可勾选开关
- ✅ 点位授权（2026-10-02）：`src/license.py` 机器码绑定——机器码 = 本机最低网卡 MAC 格式化（getmac 读取，**输出是 OEM/GBK 编码要用 mbcs 解码**）；未授权 exe 弹窗显示机器码并退出；老师用 `生成授权.bat`（→scripts/make_license.py）输入机器码生成加密 license.dat（多台可同文件）；**重复运行自动合并去重**（旧机器码保留，支持分次添加）；校验 = 本机任一 MAC 与授权任一机器码匹配（换网卡后交集还在就不失效）。仅打包 exe 生效（frozen），--smoke/--selftest 跳过。防君子不防小人，如实写在文档里
- ✅ 语音：Edge-TTS 合成，**Windows 走 winsound(waveOut) 播放**（见踩坑#1）；一句超前预取流水线，句间 0.0s 停顿
- ✅ 音效：点击/发送/唤醒（fx/*.wav，scripts/gen_fx.py 生成）
- ✅ 形象：**固定 img 图片人物（AI 生成，小云宝=图片形象）**——用户原话"人物形象用 img 里的图片，这个不要改"。矢量云朵只作图片缺失时的兜底。**三帧说话动画**：不说话时微笑↔眨眼互换（随机眨眼/睡觉闭眼）；说话时（mouth_open≥0.45）微笑↔说话互换模拟嘴巴开闭。三帧由 scripts/prepare_avatar.py 处理成 768² 透明 PNG 并**统一角色缩放对齐**（否则帧间跳变）。当前素材（2026-09-30 用户二次上传，2048² PNG、文件名与内容一致）：img/微笑.png（白底睁眼微笑）、img/眨眼.png（白底闭眼）、img/说话.png（绿底满幅张嘴）；三张右下角都有"豆包AI生成"水印（分数区 x≥0.80、y≥0.92，脚本已涂背景色）。脚本流程：缩 1024 → 水印涂背景色 → 背景色自动检测（四边中位数）+ 连通域清除 → alpha 收缩 → 角色包围盒归一化。曾踩坑：旧版 exe 没打包 img/，启动退化成矢量云朵——**--add-data 必须同时带 fx 和 img**；`小云宝.exe --smoke` 可验证打包内图片（输出 smoke_avatar.png）。
- ✅ 大小：滚轮/右键菜单缩放，0.5x ~ **填满所在屏幕**（动态上限），退出记住（pet_pos.json）
- ✅ 打包：PyInstaller onedir 模式，图标 assets/小云宝.ico（**用 img/avatar_idle.png 微笑图片**，scripts/make_icon.py 生成，缺图回退矢量云朵）
- ✅ 语音输入：讯飞流式听写（按钮 + 唤醒词）实测可用（2026-10-01）。唤醒词走**实时中间结果匹配**（不等 3 秒静音收尾，响应快）+ **同音容错表** `wake_aliases`（小元宝/小圆宝/小玉宝/小雨宝/小宇宝/小鱼宝，config.json 可增删）+ 唤醒后**语音说"我在听"**（tts.py `PromptPlayer` 启动预合成缓存，零延迟播放，播完才开麦防自录）+ 对话结束**自动恢复监听**（等 state=idle，防听到自己声音自我触发）。踩坑：旧电脑打包的 exe 唤醒词无效（疑为旧打包环境问题），本机重打包后正常
- ✅ 唤醒监听节能版（2026-10-07 改）：原方案静音也持续开讯飞会话，500 次/天额度**约 1.5 小时就烧光**，服务端报 `licc failed`（额度/免费包到期）。现改为 **本地麦克风常开 + 能量检测**（`WakeListener._gate_loop`），静音完全不走云端；触发时带 1.2 秒预录音频开会话；失败退避 30 秒并清空积压音频。**阈值可调**：config `classroom.wake_gate_rms`（默认 100，实测安静底噪 9~21；初始 260 会漏掉轻声说话——2/3 多数判定抗音量波动；踩坑：阈值太高=喊不醒，太低=环境噪误触发烧额度）。语音出错提示用 `bubble.show_alert` 强制显示（气泡关闭也可见）
- ⏳ 未实测：教室白板整机测试（部署见下）

## 换电脑操作清单（2026-10-07 更新，适用于下一台开发机）

1. 装 Python 3.12+（勾选 Add to PATH）→ 双击 `install.bat`（已配清华镜像）
2. `python src/selfcheck.py` 应 10/10 通过（Edge-TTS 项需联网）
3. **声音验证**：`python scripts/sound_probe.py` 分层听音——历史两台电脑都只有 winsound 响、Qt 通道无声，winsound 方案不要改（见踩坑#1）
4. `python src/main.py` 开发运行（开发模式不校验 license、配置从 character/config.json 读取，明文 Key 在里面）
5. 打包后 exe 只认 license.dat 绑定的机器：新开发机要用 exe 测试，先双击看弹窗机器码 → `生成授权.bat` 输入该码生成 license.dat 放进 exe 旁
6. 历史开发机环境：旧电脑 E:\Desktop\Claude\code\Desktop_Pet（Python 3.13）；上一台 D:\Administrator\Desktop\claude\folder_code\Desktop_Pet（Python 3.12.10，机器码 30C5-9985-25C4）
7. 完整会话记录在 `.claude/会话恢复/`（两个 jsonl + 恢复说明），需要历史细节可翻或 /resume

## 用户偏好（重要）

1. **先提问再动手**：一次只问一个问题，根据回答继续追问。用户习惯用"第1点/第2点"列需求。
2. 需求变化快、会改主意（例：宠物上限从"半屏"改到"全屏"）——确认后立即改，别假设。
3. 用户是老师，非程序员；方案要按"课堂使用场景"想（大屏、后排可见、孩子操作）。
4. 图片类素材用户用 AI（豆包）生成，可能带水印/白底/文件名与内容不符，先验证再信。

## 架构与文件（2026-10-02 目录重构后）

**核心原则：`src/` 与角色无关；角色专属内容全部在 `character/`。开发新宠物 = 复制项目改 character/（见 docs/开发新宠物.md）。**

| 位置 | 职责 |
|---|---|
| src/main.py | 入口：窗口/缩放/菜单/托盘/状态记忆；`--smoke` 离屏渲染；`--selftest` 全链路自测；`--scale` 启动缩放 |
| src/pet.py | 图片形象精灵图（微笑/眨眼/说话三帧）+ 矢量云朵兜底绘制；eye_open/mouth_open/squash/bob/facing/speaking 参数；MonsterWidget 类名是历史遗留，别改（多处引用） |
| src/behaviors.py | 行为状态机：待机/散步/睡觉（仅手动）/进食/跟随鼠标 + 苹果食物 + 自由移动开关 |
| src/chat.py | ChatBot（DeepSeek 流式+护栏+分句+提示词规则）+ ChatSession（对话编排、45s 收尾兜底定时器） |
| src/tts.py | Speaker：合成线程→QAudioDecoder 解码→winsound 异步播→QTimer 收尾；一句超前预取流水线；PromptPlayer 固定提示语缓存播放 |
| src/fx.py | 音效播放器（Windows 走 winsound；目录查找：_MEIPASS → 脚本目录 → character/） |
| src/voice.py / asr.py / mic.py | 语音链路：麦克风按钮/唤醒词/连续对话（讯飞）；mic 大按钮 |
| src/bubble.py | 对话气泡（打字机，可关）+ 打字输入框 |
| src/stage.py | 全屏舞台模式（大云宝+字幕） |
| src/config.py + character/config.json | 配置加载（CWD/config.json → character/config.json 兜底 DEFAULTS）；**keys.dat 加密 Key 优先覆盖**，删 keys.dat 则用 config.json 明文（换 Key 路径） |
| character/img/ | 三帧素材+处理产物 avatar_*.png；喂AI素材/ 豆包再生素材包 |
| character/fx/ + assets/ | 音效 wav / exe 图标 ico |
| scripts/ | prepare_avatar.py 三帧处理、gen_fx.py 音效、make_icon.py 图标、make_keys.py 加密 Key、sound_probe/wake_probe/chat_probe 诊断 |
| docs/ | README.md（项目说明）、使用指南.md（分发包内文档）、开发新宠物.md（迁移指南） |
| 制作分发包.bat | 一键生成免安装分发包（空白 config + 加密 keys.dat + 使用指南） |
| dist/小云宝/ | PyInstaller 产物（exe + _internal + config.json 副本） |
| pet_pos.json | 运行时生成：位置/麦克风按钮位置/缩放/气泡与移动开关记忆 |

## 踩坑记录（务必先读，别重蹈覆辙）

1. **两台电脑实测 Qt 音频后端都无声**：QMediaPlayer/QSoundEffect 事件流正常（EndOfMedia 照发）但扬声器不响；winsound 蜂鸣正常（2026-09-30 旧机与 2026-10-01 新机 sound_probe 结果一致）。因此 Windows 上 TTS 与音效**全走 winsound(waveOut)**，不要"顺手修好"这个设计。以后换电脑仍先用 `scripts/sound_probe.py` 分层听音验证，若 Qt 通道正常可考虑切回（tts.py 里非 win32 分支已保留 QMediaPlayer 路径）。
2. **Qt 信号发射顺序**：状态复位（`_playing=False`）必须在 `finished.emit()` **之前**，否则收尾方查 busy 恒为 True，聊天框永远不消失。tts.py 三个收尾点都已修，别改回去。
3. **PySide6 API 与 Qt 官方文档不一致**（本机版本实测）：`QAudioDecoder` 的信号是 `bufferReady()`（**无参**，取数据用 `dec.read()`）和 `error`，不是文档写的 audioBufferReady/errorOccurred。`QMediaPlayer.errorOccurred` 存在。Pillow 12 已移除 `ImageDraw.floodfill`/`Image.floodfill`。
4. **预取流水线三个坑**：`Speaker.busy` 必须把 `_prefetching` 算进去（否则回合过早结束、音频孤儿）；空闲态也要防重复开工预取；`_play_ready()` 末尾必须再 `_pump()`（否则句间又有停顿）。
5. **打包**：环境里 PyQt5/PyQt6/tkinter 与 PySide6 共存会中断 PyInstaller，必须 `--exclude-module PyQt5 --exclude-module PyQt6 --exclude-module tkinter`。用 **onedir**（启动快；onefile 在白板上解包慢）。资源查找优先级（main.py `_asset_path`）：**CWD → _MEIPASS → 脚本目录**——把 img/ 放在 exe 旁边即可覆盖内嵌图片，换形象无需重打包；fx.py 用 _MEIPASS。config.json/pet_pos.json 从 CWD 读取（双击 exe 时 CWD=exe 目录，config.json 已复制在 exe 旁）。
6. **三帧色差**：AI 分次生成的三帧有区域性着色偏差（下巴带 blink 偏暗、talk 偏绿，空间不均匀）。prepare_avatar.py 已做：直方图匹配 + 稳定格子回归 + 分区局部增益校色 + 统一提鲜 1.22，整体均值差收敛到 ~1、大部分区域 ≤7，但下巴带仍有 ~10-17 残留。**根治需用户用 img/喂AI素材/ 里的基准图+提示词重新生成**（两次生成都以同一基准图为底、只改表情、白底），替换 img/微笑.png、眨眼.png、说话.png 后重跑 prepare_avatar.py。
6. **无视觉模型时的图片分析**：用"两图差分 + 整图/局部 ASCII 灰度渲染"定位过豆包水印（在右下角 x1070-1280/y1190-1280，浅灰 190-230 恰好躲过抠图阈值 230）。相关代码在 scripts/prepare_avatar.py。
7. Windows 控制台中文输出 GBK 乱码是显示问题不是数据问题；`tasklist` 匹配中文进程名要用 Python decode("gbk")，别用 bash grep。

## 常用命令

```bash
python src/main.py               # 开发运行
python src/main.py --smoke       # 离屏渲染形象到 smoke.png
python src/main.py --selftest    # 全链路自测（真实提问+语音+气泡流程，打印事件时间戳）
python src/selfcheck.py          # 离线 10 项自检（不需要 Key）
python scripts/make_icon.py      # 重新生成 exe 图标（改形象后要跑）
python scripts/gen_fx.py         # 重新生成音效
python scripts/make_keys.py      # 生成加密 Key 文件 keys.dat
# 装依赖（国内 pypi.org 卡死时加清华镜像）：
python -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
# 重新打包（img 和 fx 都必须带上，漏掉 img 会退化成矢量云朵；
# --noconfirm 必须加：dist 非空时 PyInstaller 会拒绝覆盖导致打包静默失败！）：
pyinstaller --noconfirm --noconsole --onedir --name 小云宝 \
  --icon "character/assets/小云宝.ico" \
  --add-data "character/img;img" --add-data "character/fx;fx" \
  --exclude-module PyQt5 --exclude-module PyQt6 --exclude-module tkinter src/main.py
# 打包后把 config.json、config.example.json、README.md 复制进 dist/小云宝/
# 一键生成发给别人的分发包（空白配置+加密keys.dat+使用指南）：双击 制作分发包.bat
```

## 部署到希沃白板

1. 把整个 `dist/小云宝/` 文件夹拷到白板（约 153MB）
2. 在 exe 旁的 config.json 填好 Key（DeepSeek 已填；讯飞按需）
3. 白板需联网（聊天+语音都走云端）
4. 双击 `小云宝.exe`：无黑框直接出现云朵；位置/大小会记住（pet_pos.json 生成在 exe 旁）
5. 若要开机自启：双击 exe 旁的 `设置开机自启.bat`（PowerShell 在启动文件夹建快捷方式；**PS 命令行里不要出现中文路径**——用 `Get-ChildItem -Filter *.exe` 动态找 exe、`(Get-Location).Path` 取工作目录，否则 cp65001 下中文变乱码）；`取消开机自启.bat` 撤销。程序侧已加固：config/keys/license 查找包含 exe 所在目录，任何启动方式（含注册表 Run 键、无工作目录快捷方式）都能找到配置

**发给别的老师/别的班**：双击 `制作分发包.bat` 生成 `分发/小云宝课堂版/`（空白 config + 加密 keys.dat + 使用指南），压缩发过去解压即用；对方换自己的 Key = 删 keys.dat 改 config.json（见 docs/使用指南.md）。Key 加密是 XOR+Base64 防君子不防小人，明说在文档里了。

## 后续规划（用户提过的方向）

- 知识库 RAG：教案/绘本文件夹 → 基于教案备课（chat.py 预留 kb 注入点）
- 全屏模式时气泡字幕等比放大（目前气泡固定 28px，宠物全屏时字偏小）
- 语音打断：孩子说话时自动停嘴
- 打包 exe 后如嫌启动慢，考虑 onefile 或精简 PySide6 子模块
- 讯飞额度观察：节能唤醒上线后确认教室实际日消耗，不够再考虑充值或本地离线唤醒方案
