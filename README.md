# YouTube JP→CN Subtitle Generator
# YouTube日语字幕 → 中文翻译字幕生成器

日本語Readme.mdあり

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
[3] Whisper (large) 日语音频 → 文字
    ↓
[4] AI 批量翻译：日语 → 中文（20条/批）
    ↓
[5] 生成 ASS 字幕（双语 + 仅中文）
    ↓
[6] 合并视频 + 音频 → 最终 MP4（清理临时文件）
```

---

## 环境配置

### 1. 创建 conda 环境

```bash
conda create -n subtitle python=3.10
conda activate subtitle
```

### 2. 安装依赖

```bash
# ffprobe/ffmpeg（conda）
conda install -c conda-forge ffmpeg

# Python 依赖
pip install -r requirements.txt
```

### 3. 配置 .env

```bash
cp .env.example .env
```

然后编辑 `.env`，根据你有的 API Key 填写（可填多个，会自动优先使用第一个有效的）：

```env
# 翻译后端（按优先级自动选用）
DEEPSEEK_API_KEY=      # deepseek-chat，性价比高
OPENAI_API_KEY=        # GPT-4o mini
MINIMOX_API_KEY=       # MiniMax-Text-01
GOOGLE_API_KEY=        # Gemini 2.0 Flash
GROQ_API_KEY=         # Llama 3.1 8B（免费，速度快）
ANTHROPIC_API_KEY=     # Claude 系列
ZHIPU_API_KEY=         # 智谱 GLM-4-Flash（国内可用）
# Google Translate（免费备选，无需 Key）

# 本地模型
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=llama3

# 工具路径
FFMPEG_PATH=C:\Users\elaak\miniconda3\envs\subtitle\Library\bin
YTDLP_PATH=C:\Users\elaak\miniconda3\envs\subtitle\Scripts

# 输出目录（可选，默认 {script_dir}/downloads/）
OUTPUT_DIR=C:\Users\elaak\Desktop\testing_folder\downloads
```

**自动选择规则：** 系统从 DeepSeek → OpenAI → MiniMax → Gemini → Groq → Ollama → Anthropic → 智谱 → Google Translate 依次检查，返回第一个配置了有效 Key 的后端。均未配置时使用 Google Translate（免费，无需 Key）。

---

## 使用方法

### 基本用法

```bash
# 激活环境后
python main.py "https://youtu.be/HtpzR17uq0w"
```

默认用 Whisper `large` 模型，输出到 `downloads/{视频标题}/`。

### 命令行参数

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `url` | YouTube 视频 URL（必需） | — |
| `--model` | Whisper 模型（tiny/base/small/medium/large） | `large` |
| `--output` | 输出目录（优先级：CLI > .env > 默认） | `{script_dir}/downloads/` |
| `--no-video` | 跳过视频下载（仅下载音频，节省时间） | False |
| `--no-thumb` | 跳过缩略图下载 | False |

### 示例

```bash
# 指定模型和输出目录
python main.py "https://youtu.be/HtpzR17uq0w" --model medium --output ./output

# 仅音频模式（不看视频只做字幕时用，下载更快）
python main.py "https://youtu.be/HtpzR17uq0w" --no-video
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
├── {标题}_info.txt       # 元数据（标题、URL、简介前350字）
└── {标题}_audio.m4a      # ⚠️ 此文件已无用（合并后自动清理）
```

> 注意：临时文件（下载的原始视频 + 原始音频）在合并完成后**自动删除**，只保留 `_video.mp4`。

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

`dual.ass` 两条叠加：
- **上层（Dual_ZH）：** 中文，白色，Microsoft JhengHei，80pt，{\fsp4} 行间距
- **下层（Dual_JP）：** 日文，浅灰色，Arial，24pt

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
├── main.py                     # 入口，6步流水线
├── .env / .env.example         # 配置（API Key、路径等）
├── requirements.txt
├── README_zh.md / README_ja.md
│
├── src/
│   ├── downloader.py           # yt-dlp 分离下载视频 + 音频
│   ├── transcriber.py          # Whisper 音频 → 文字
│   ├── translator.py           # 翻译工厂（自动选后端 + 批量翻译）
│   ├── subtitle_builder.py    # 从 preset .ass 加载样式，生成字幕
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
- 确认用的是 `--model large`（默认）
- 前30秒如果是纯音乐/静音段属正常（Whisper 只转写语音）
- 音频质量问题可试 `--no-video` 强制用 bestaudio 流

### Q: 想修改字幕字体
A: 直接编辑 `presets/styles/dual.ass` 和 `zh.ass` 中的 `Fontname` 字段，改为系统已安装的中文字体，如 `Microsoft YaHei`、`SimHei`、`PingFang SC`。

### Q: 视频下载失败
A: 可能是 YouTube 地区限制或网络问题，检查 VPN。

---

## License

MIT License
