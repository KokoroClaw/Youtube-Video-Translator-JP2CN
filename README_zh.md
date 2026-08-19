# YouTube JP→CN Subtitle Generator
# YouTube日语字幕 → 中文翻译字幕生成器

[项目首页](README.md) · [日本語](README_ja.md)

---

## 项目介绍

从 YouTube 视频自动生成日语原声的中文字幕（双语 + 仅中文两种格式）。

**处理流程：**
```
YouTube URL
    ↓
[1] 获取视频元数据（标题、时长、简介）
    ↓
[2] 分离下载视频流 + 音频流（bestaudio）
    ↓
[3] OpenAI whisper-1 日语音频 → 带时间轴文字
    ↓
[4] OpenAI 批量翻译：日语 → 中文（由 TRANSLATION_BATCH_SIZE 控制）
    ↓
[5] 生成 ASS 字幕（双语 + 仅中文）
    ↓
[6] 合并视频 + 音频 → 最终 MP4（清理临时文件）
    ↓
[7] 可选：选择 zh.ass / dual.ass 压制硬字幕 → 确认后投稿 B 站
```

---

## 环境配置

### 1. 创建 conda 环境

```powershell
conda create -n subtitle python=3.11
conda activate subtitle
```

项目使用 Python 3.10 以上语法；当前发布前测试环境为 Python 3.11。

### 2. 安装依赖

当前 yt-dlp 的 YouTube 提取需要 Node.js 22 或更高版本来处理播放器挑战（参见 [yt-dlp EJS 文档](https://github.com/yt-dlp/yt-dlp/wiki/EJS)）。先确认：

```powershell
node --version
```

```powershell
# ffprobe/ffmpeg（conda）
conda install -c conda-forge ffmpeg

# Python 依赖
pip install -r requirements.txt
```

### 3. 配置 .env

```powershell
Copy-Item .env.example .env
```

然后编辑 `.env`，填写 OpenAI API Key，并明确指定转写和翻译后端：

```env
OPENAI_API_KEY=你的OpenAI密钥
TRANSCRIPTION_BACKEND=openai
OPENAI_TRANSCRIPTION_MODEL=whisper-1
TRANSLATION_BACKEND=openai
OPENAI_TRANSLATION_MODEL=gpt-4o-mini
TRANSLATION_BATCH_SIZE=50

# 其他可选翻译后端（仅在修改 TRANSLATION_BACKEND 后使用）
DEEPSEEK_API_KEY=
MINIMAX_API_KEY=       # MiniMax-Text-01
GOOGLE_API_KEY=        # Gemini 2.0 Flash
GROQ_API_KEY=         # Llama 3.1 8B（免费，速度快）
ANTHROPIC_API_KEY=     # Claude 系列
ZHIPU_API_KEY=         # 智谱 GLM-4-Flash（国内可用）
# Google Translate（免费备选，无需 Key）

# 本地模型
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=llama3

# 工具路径
FFMPEG_PATH=C:\path\to\miniconda3\envs\subtitle\Library\bin
YTDLP_PATH=C:\path\to\miniconda3\envs\subtitle\Scripts\yt-dlp.exe
YTDLP_JS_RUNTIME=node
YTDLP_FORCE_IPV4=true
YTDLP_PLAYER_CLIENT=web_embedded
BILIUP_PATH=C:\path\to\miniconda3\envs\subtitle\Scripts\biliup.exe

# 输出目录（可选，默认 {script_dir}/downloads/）
OUTPUT_DIR=C:\path\to\output
```

默认固定使用 OpenAI。只有将 `TRANSLATION_BACKEND` 改成 `auto` 时，才会按已配置的后端自动选择。

`YTDLP_PATH` 必须指向 `yt-dlp.exe` 本身，不能只填写 `Scripts` 目录。`FFMPEG_PATH` 可以指向 `ffmpeg.exe`，也可以指向包含它的目录。`.env` 包含密钥且已被 `.gitignore` 排除，发布代码时不要强制添加它。

中文翻译结果会统一移除句号，并将逗号替换为空格；日文原文不受影响。

---

## 使用方法

### Web UI（推荐）

首次使用先安装更新后的依赖，然后启动本地界面：

```powershell
conda activate subtitle
pip install -r requirements.txt
python web.py
```

也可以在 PowerShell 中直接运行：

```powershell
.\start_web.ps1
```

Windows 用户还可以直接双击 `start_web.bat`。这个脚本默认使用 `%USERPROFILE%\miniconda3\envs\subtitle\python.exe`，如果你的 Miniconda 或环境安装在其他位置，请修改脚本中的 `PYTHON_EXE`。

浏览器打开 `http://127.0.0.1:8787`。界面只监听本机地址，OpenAI API Key 继续从 `.env` 读取，不会发送到网页前端。

Web UI 包含任务进度、处理日志、结果文件下载、字幕压制、B 站投稿和术语库管理。术语库保存在 `data/glossary.json`；当日文原文命中已启用术语时，系统会用受保护标记确保指定中文译法不被模型改写。如果模型意外丢失标记，任务会明确报错，而不是静默输出错误术语。

#### 自动拆分过长字幕

高级设置中的“自动拆分过长字幕”默认开启。系统会在 Whisper 识别和 GPT 翻译完成后，按照视频画布、字幕字号、边距、密度和最多行数检查每个中文字幕片段。超过容量时会生成两个或更多独立时间轴片段，而不是只在同一个片段里插入 `\N`：

- OpenAI `whisper-1` 同时请求 `segment` 和 `word` 时间戳，优先在真实语音词边界上切时间
- 只有过长字幕才让当前 OpenAI 翻译模型选择中日文对应的自然语义切点
- 语义切分失败或使用其他翻译后端时，会自动使用本地平衡切分，不会让整个任务失败
- 每个片段默认至少保留约 `0.7` 秒，避免一闪而过
- “短句 / 标准 / 紧凑”控制每行信息量；默认“标准、最多 2 行”
- 中文仍会执行项目标点规则：逗号变空格，句号删除

单词时间戳比只有片段时间戳稍慢。如果关闭自动拆分，管线会保留 Whisper 原始片段，只使用原有安全换行。

Whisper 仍然只转写一次，获取 word timestamp 不会触发第二次音频转写。使用 OpenAI 翻译后端时，每个需要语义切分的过长片段会额外调用一次当前文本模型；普通片段和本地回退切分不会产生这笔额外文本模型调用。

为了避免重复产生 OpenAI 费用，输出目录中已经存在 `*_zh.ass` 和 `*_dual.ass` 时仍会复用缓存，不会重新执行自动拆段。自动拆段会应用于之后新识别、翻译的任务；已有字幕可以继续在“字幕编辑”中手工拆分。

#### 可视化字幕编辑器

任务完成后打开“字幕编辑”标签，可以直接在网页中完成日常校对：

- 播放原视频并自动高亮当前字幕；点击字幕行可跳转到对应时间
- 修改中日文、开始/结束时间，或使用 `±0.1s`、`±0.5s` 微调
- 新增、删除、拆分、合并字幕，并提示时间重叠
- 分别调整纯中文、双语中文、双语日文的字体、字号、颜色、描边、阴影、位置和边距
- `Ctrl+S` 保存、`Ctrl+Z` 撤销、`Ctrl+Y` 重做
- “精确预览当前帧”会用 FFmpeg 和保存后的 ASS 显示最终渲染效果

编辑器以 `.kotoba/subtitles.json` 作为当前任务的统一字幕数据。每次保存都会在 `.kotoba/backups/` 备份原 ASS，再原子更新 `*_zh.ass` 和 `*_dual.ass`。如果 Aegisub 或其他程序在外部修改了 ASS，旧网页版本会被拒绝覆盖，需要点击“重新载入”。字幕保存后，旧硬字幕视频会从网页投稿选项中移除，必须重新压制，避免误传旧版本。使用 `--no-video` 生成的任务仍可编辑字幕，但没有视频和精确帧预览。

#### 压制校对后的字幕

任务完成后会出现“字幕压制”区域。先在输出目录中校对并保存 `*_zh.ass` 或 `*_dual.ass`，回到网页选择对应版本，再点击“开始压制”。系统使用 FFmpeg 输出 H.264/AAC 兼容 MP4：

- `zh.ass` → `*_hardsub_zh.mp4`
- `dual.ass` → `*_hardsub_dual.mp4`
- 视频编码：`libx264`、CRF 18、`yuv420p`、`faststart`
- 音频直接复制，不重复编码；源视频和 ASS 都不会被覆盖

双语模板会按视频画布自动缩放字号和边距，并为无空格的中日文长句加入安全换行。手工编辑已有 ASS 时，也要检查长句是否需要 `\N` 换行。

#### 投稿到 B 站

项目通过第三方 `biliup` CLI 完成登录和投稿，依赖已包含在 `requirements.txt`。如果网页显示“未安装”，先在已激活的环境中执行 `pip install -r requirements.txt`，并在 `.env` 配置 `BILIUP_PATH`。

1. 点击“扫码登录 B 站”，在新打开的终端按提示扫码。登录凭据只保存在 `%LOCALAPPDATA%\KotobaStudio\bilibili\cookies.json`，不会写进项目或网页前端。
2. 选择原视频、`hardsub_zh.mp4` 或 `hardsub_dual.mp4`，填写标题、分区和标签；简介默认留空，可按需填写。
   分区选择器按 [biliup 分区参考表](https://biliup.github.io/tid-ref.html) 整理为“大区 → 视频分区”，点击中文名称后会自动提交对应数字 ID；默认选择“时尚 → 穿搭（158）”。YouTube 缩略图可能是扩展名为 `.jpg` 的 WebP，启用封面后系统会先转换成真正的 RGB JPEG 再投稿，也可以取消勾选让 B 站自动取帧。
3. 默认稿件类型是“转载”；转载来源会自动带入当前任务的原 YouTube URL。只有确实拥有自制版权时才选“自制”。
4. 勾选“我确认现在公开投稿到 B 站”后按钮才可提交。每次投稿都必须重新确认，不会在字幕生成结束后自动公开发布。

扫码登录和公开投稿需要用户本人完成；请遵守 B 站规则并确认所用视频、音乐、字幕和封面拥有相应权利。当前实现为本机单用户工具，不要把 Web 服务暴露到公网。

### 基本用法

```powershell
# 激活环境后
conda activate subtitle
$env:PYTHONUTF8="1"
python main.py "https://youtu.be/HtpzR17uq0w"
```

默认用 OpenAI `whisper-1` 转写和 `gpt-4o-mini` 翻译，输出到 `downloads/{视频标题}/`。

### 命令行参数

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `url` | YouTube 视频 URL（必需） | — |
| `--transcription-backend` | 转写后端（openai/local） | `openai` |
| `--model` | 本地 Whisper 模型；OpenAI 模式忽略 | `large` |
| `--output` | 输出目录（优先级：CLI > .env > 默认） | `{script_dir}/downloads/` |
| `--no-video` | 跳过视频下载（仅下载音频，节省时间） | False |
| `--no-thumb` | 跳过缩略图下载 | False |
| `--separator` | 转写前启用人声提取 | 默认关闭 |
| `--no-separator` | 明确关闭人声提取（兼容选项） | — |
| `--no-auto-split` | 关闭过长字幕自动拆段 | 默认开启 |
| `--subtitle-density` | 自动拆段密度：short / standard / compact | `standard` |
| `--subtitle-lines` | 每个时间轴片段最多视觉行数：1 / 2 / 3 | `2` |
| `--prompt` | 传给 Whisper 的日语识别提示 | 内置日语会话提示 |

### 示例

```powershell
# 使用本地 Whisper medium 模型
python main.py "https://youtu.be/HtpzR17uq0w" --transcription-backend local --model medium

# 仅音频模式（不看视频只做字幕时用，下载更快）
python main.py "https://youtu.be/HtpzR17uq0w" --no-video

# 需要时手动启用人声提取
python main.py "https://youtu.be/HtpzR17uq0w" --separator
```

---

## 输出文件

每次运行在 `{输出目录}/{视频标题}/` 下生成：

```
{视频标题}/
├── {标题}_video.mp4      # 最终合并好的视频（视频流 + 音频流）
├── {标题}_thumb.jpg      # 缩略图
├── {标题}_dual.ass       # 双语字幕（日文在下灰字，中文在上白字）
├── {标题}_zh.ass         # 仅中文字幕（白字）
├── {标题}_hardsub_zh.mp4 # 可选：压制仅中文字幕
├── {标题}_hardsub_dual.mp4 # 可选：压制双语字幕
├── {标题}_info.txt       # 元数据（标题、URL、简介前350字）
├── {标题}_audio.m4a      # 仅 --no-video 模式保留，供转写或后续处理
└── .kotoba/              # 使用网页编辑器后生成的字幕数据与备份
```

> 正常下载视频时，`_video_raw.mp4` 与 `_audio.m4a` 会在合并成功后自动删除，只保留 `_video.mp4`。使用 `--no-video` 时不会生成 `_video.mp4`，音频文件会保留。

---

## 字幕样式自定义

样式由 `presets/styles/dual.ass` 和 `presets/styles/zh.ass` 定义。

### 方法一：用 Aegisub 可视化编辑（推荐）

1. 用 Aegisub 打开 `presets/styles/dual.ass`
2. 按 `Shift+F3` 打开样式管理器
3. 修改字体、大小、颜色、描边等参数
4. 保存，程序下次运行自动加载新样式

### 方法二：直接编辑 .ass 文件

ASS 颜色格式为 BGR（不是 RGB！）：

| 颜色 | ASS 值 |
|------|--------|
| 白色 | `&H00FFFFFF` |
| 浅灰 | `&H00D0D0D0` |
| 黄色 | `&H00FFFF00` |
| 红色 | `&H000000FF` |

对齐方式（数字键盘对应位置）：

```
7  8  9   ← 顶部
4  5  6   ← 中部
1  2  3   ← 底部（2 = 底部居中，默认）
```

### 双语字幕布局说明

`dual.ass` 使用上下分区：
- **上方（Dual_ZH）：** 中文，白色，Microsoft JhengHei
- **下方（Dual_JP）：** 日文，浅灰色，Arial
- 模板以 1080 行画布为基准，生成时会按实际 `PlayResY` 自动缩放字号、描边和边距

---

## 支持的翻译后端

| 后端 | 环境变量 | 默认模型 |
|------|---------|---------|
| DeepSeek | `DEEPSEEK_API_KEY` | deepseek-chat |
| OpenAI | `OPENAI_API_KEY` | gpt-4o-mini |
| MiniMax | `MINIMAX_API_KEY` | MiniMax-Text-01 |
| Google Gemini | `GOOGLE_API_KEY` | gemini-2.0-flash |
| Groq | `GROQ_API_KEY` | llama-3.1-8b-instant |
| Ollama（本地） | `OLLAMA_BASE_URL` + `OLLAMA_MODEL` | 自定义 |
| Anthropic | `ANTHROPIC_API_KEY` | claude-sonnet-4 |
| 智谱 AI | `ZHIPU_API_KEY` | glm-4-flash |
| Google Translate | 无需 Key | —（免费备选） |

---

## 项目结构

```
youtube_translator(JP2CN)/
├── README.md                   # GitHub 项目入口
├── main.py                     # CLI 入口与参数解析
├── web.py                      # 本地 FastAPI Web UI
├── start_web.bat / .ps1       # Windows 一键启动脚本
├── .env / .env.example         # 配置（API Key、路径等）
├── .gitignore / LICENSE        # 发布保护与许可证
├── requirements.txt
├── README_zh.md / README_ja.md
│
├── src/
│   ├── downloader.py           # yt-dlp 分离下载视频 + 音频
│   ├── transcriber.py          # Whisper 音频 → 文字
│   ├── translator.py           # 翻译工厂（自动选后端 + 批量翻译）
│   ├── subtitle_builder.py    # 从 preset .ass 加载样式，生成字幕
│   ├── subtitle_editor.py     # Web 校对、双 ASS 同步、备份与精确预览
│   ├── subtitle_splitter.py   # 视觉容量、双语语义切分与时间轴拆分
│   ├── burner.py              # FFmpeg 硬字幕压制与进度解析
│   ├── bilibili_uploader.py   # biliup 登录状态与投稿适配器
│   ├── utils.py                # 工具函数（时间戳格式、ffmpeg合并等）
│   │
│   └── backends/               # 翻译后端实现
│       ├── base.py             # 抽象基类（TranslationBackend）
│       ├── deepseek.py
│       ├── openai.py
│       ├── minimax.py
│       ├── gemini.py
│       ├── groq.py
│       ├── ollama.py
│       ├── anthropic.py
│       ├── zhipu.py
│       └── google.py           # Google Translate（免费备选）
│
├── web/static/                 # Web UI 的 HTML、CSS、JavaScript
├── tests/                      # unittest 自动测试
└── presets/
    └── styles/
        ├── dual.ass            # 双语样式模板（Aegisub 可视化编辑）
        └── zh.ass              # 中文仅字幕样式模板
```

---

## 常见问题

### Q: 报错 "ffmpeg not found"
A: 确认 `FFMPEG_PATH` 已正确写入 `.env`，路径指向 `Library/bin` 目录（不是 `Scripts`）。

### Q: 翻译报错 "API key not found"
A: 检查 `.env` 是否已创建、Key 是否正确、前后无空格。

### Q: Whisper 转写质量差 / 漏掉内容
A:
- OpenAI 模式固定使用 `.env` 中的 `OPENAI_TRANSCRIPTION_MODEL=whisper-1`；`--model` 在该模式下无效
- 本地模式可以使用 `--transcription-backend local --model large`
- 前30秒如果是纯音乐/静音段属正常（Whisper 只转写语音）
- `--no-video` 只跳过视频画面下载，音频本来就始终使用 `bestaudio`
- 背景音乐或噪声影响明显时，可以尝试 `--separator`，但处理会更慢并需要额外模型资源

### Q: 想修改字幕字体
A: 直接编辑 `presets/styles/dual.ass` 和 `zh.ass` 中的 `Fontname` 字段，改为系统已安装的中文字体，如 `Microsoft YaHei`、`SimHei`、`PingFang SC`。

### Q: 视频下载失败
A: 可能是 YouTube 地区限制或网络问题，检查 VPN。

### Q: OpenAI 提示音频超过 25 MB
A: 当前 OpenAI 转写实现一次上传完整音频，超过 25 MB 会在发送前停止并提示错误。请先压缩或切分音频；项目目前还没有自动分片上传功能。

### Q: B 站投稿返回 `-400 请求错误`
A: 检查分区、标题、标签、稿件类型和转载来源是否有效，并确认登录凭据没有过期。Web UI 只会显示 biliup/B 站返回的错误，不会绕过平台校验。

### Q: 在 92% 封装视频时报 `[WinError 5] 拒绝访问`
A: Windows 拒绝当前进程执行 `.env` 中配置的 `ffmpeg.exe`。请关闭旧服务后，在普通 PowerShell 中运行 `.\start_web.ps1`。再次提交同一视频时，程序会复用已经生成的 ASS 字幕，跳过 OpenAI 转写和翻译，不会重复产生这部分 API 费用。

---

## 测试与发布前检查

项目测试基于标准库 `unittest`，不要求安装 pytest：

```powershell
conda activate subtitle
python -m unittest discover -s tests -v
```

提交到 GitHub 前先运行 `git status --short`，确认没有 `.env`、`data/`、`downloads/`、本地模型、音视频或编辑器备份进入暂存区。`data/glossary.json` 是本机术语库，默认不会上传；需要迁移时请单独做私密备份。

---

## License

[MIT License](LICENSE)
