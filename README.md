# Kotoba Studio — YouTube 日语字幕翻译工具

本地运行的 YouTube 日语语音转中文字幕工作流，支持 OpenAI `whisper-1` 转写、GPT 翻译、术语保护、过长字幕自动拆分、网页校对、ASS 样式调整、硬字幕压制以及经用户确认后的 B 站投稿。

[中文完整文档](README_zh.md) · [日本語ドキュメント](README_ja.md)

## 主要功能

- 生成纯中文和中日双语 ASS 字幕
- 按画面宽度自动拆分过长字幕，并同步拆分中日文和时间轴
- 在 Web UI 中编辑文本、时间轴和常用 ASS 样式
- 使用术语库固定人名、节目名和专业词汇的译法
- 选择 `zh.ass` 或 `dual.ass` 压制 H.264 硬字幕视频
- 通过本机 `biliup` 登录并投稿 B 站；每次公开投稿都要求手动确认

## 快速开始（Windows）

```powershell
conda create -n subtitle python=3.11
conda activate subtitle
conda install -c conda-forge ffmpeg
pip install -r requirements.txt
Copy-Item .env.example .env
```

编辑 `.env`，至少填写 `OPENAI_API_KEY`，并把 `FFMPEG_PATH`、`YTDLP_PATH` 配置为本机的实际绝对路径。使用项目默认 Node 运行时还需要 Node.js 22 或更高版本。

双击 `start_web.bat`，或在 PowerShell 中运行：

```powershell
.\start_web.ps1
```

然后访问 <http://127.0.0.1:8787>。完整安装、CLI 参数、输出文件和安全说明请阅读[中文文档](README_zh.md)。

## 发布与隐私

- `.env`、下载视频、字幕任务历史、术语库和本地模型已由 `.gitignore` 排除。
- 不要把本项目的 Web 服务暴露到公网。
- B 站登录凭据保存在项目目录之外；公开投稿前请确认素材版权及平台规则。
- 自动测试命令：`python -m unittest discover -s tests -v`。

## License

[MIT](LICENSE)
