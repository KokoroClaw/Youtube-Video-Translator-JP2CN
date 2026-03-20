# YouTube JP→CN Subtitle Generator
# YouTube日本語音声 → 中国語字幕生成ツール

---

## プロジェクト概要

YouTube動画の日本語音声から中国語字幕（バイリンガル + 中文のみ）を自動生成します。

**処理フロー：**
```
YouTube URL
    ↓
[1] 動画メタデータを取得（タイトル、再生時間、概要）
    ↓
[2] 動画ストリーム + 音声ストリームを分離ダウンロード（bestaudio）
    ↓
[3] Whisper (large) で日本語音声 → テキスト化
    ↓
[4] AI一括翻訳：日本語 → 中国語（20件/バッチ）
    ↓
[5] ASS字幕生成（バイリンガル + 中文のみ）
    ↓
[6] 動画 + 音声を結合 → 最終MP4（一時ファイルを自動削除）
```

---

## 環境構築

### 1. conda環境の作成

```bash
conda create -n subtitle python=3.10
conda activate subtitle
```

### 2. 依存関係のインストール

```bash
# ffprobe/ffmpeg（conda）
conda install -c conda-forge ffmpeg

# Python依存
pip install -r requirements.txt
```

### 3. .env の設定

```bash
cp .env.example .env
```

`.env` を編集し、利用可能なAPI Keyを記入（複数可。自動優先順位で選択）：

```env
# 翻訳バックエンド（優先順位で自動選択）
DEEPSEEK_API_KEY=      # deepseek-chat、高コスパ
OPENAI_API_KEY=        # GPT-4o mini
MINIMAX_API_KEY=       # MiniMax-Text-01
GOOGLE_API_KEY=        # Gemini 2.0 Flash
GROQ_API_KEY=         # Llama 3.1 8B（ 무료、高速）
ANTHROPIC_API_KEY=     # Claudeシリーズ
ZHIPU_API_KEY=         # 智譜GLM-4-Flash（中国本土向け）
# Google Translate（ 免费替代案、Key不要）

# ローカルモデル
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=llama3

# ツールパス
FFMPEG_PATH=C:\Users\elaak\miniconda3\envs\subtitle\Library\bin
YTDLP_PATH=C:\Users\elaak\miniconda3\envs\subtitle\Scripts

# 出力ディレクトリ（省略時：{script_dir}/downloads/）
OUTPUT_DIR=C:\Users\elaak\Desktop\testing_folder\downloads
```

**自動選択ルール：** DeepSeek → OpenAI → MiniMax → Gemini → Groq → Ollama → Anthropic → 智譜 → Google Translate の順でチェックし、最初の有効なKeyを使用。全て未設定の場合は Google Translate（無料）。

---

## 使い方

### 基本構文

```bash
# 環境有効化後
python main.py "https://youtu.be/HtpzR17uq0w"
```

Whisper `large` モデル使用、出力は `downloads/{動画タイトル}/` 。

### コマンドライン引数

| 引数 | 説明 | デフォルト |
|------|------|-----------|
| `url` | YouTube動画URL（必須） | — |
| `--model` | Whisperモデル（tiny/base/small/medium/large） | `large` |
| `--output` | 出力ディレクトリ（CLI > .env > デフォルト） | `{script_dir}/downloads/` |
| `--no-video` | 動画ダウンロードをスキップ（音声のみ） | False |
| `--no-thumb` | サムネイルダウンロードをスキップ | False |

### 使用例

```bash
# モデルと出力ディレクトリを指定
python main.py "https://youtu.be/HtpzR17uq0w" --model medium --output ./output

# 音声のみ（字幕作成目的のみ、DL高速化）
python main.py "https://youtu.be/HtpzR17uq0w" --no-video
```

---

## 出力ファイル

 `{出力ディレクトリ}/{動画タイトル}/` に以下を生成：

```
{動画タイトル}/
├── {タイトル}_video.mp4      # 動画+音声結合済み最終ファイル
├── {タイトル}_thumb.jpg      # サムネイル画像
├── {タイトル}_dual.ass       # バイリンガル字幕（日文在下灰色、中文在上白色）
├── {タイトル}_zh.ass         # 中国語のみ字幕（白色）
├── {タイトル}_info.txt       # メタデータ（タイトル、URL、概要350字）
└── {タイトル}_audio.m4a      # ⚠️ 結合後に自動削除される一時ファイル
```

> 注意：一時ファイル（DLした元動画 + 元音声）は結合完了後に**自動削除**され、`_video.mp4` のみが残ります。

---

## 字幕スタイルのカスタマイズ

スタイル定義は `presets/styles/dual.ass` と `presets/styles/zh.ass` で管理。

### 方法一：Aegisubでビジュアル編集（推奨）

1. Aegisubで `presets/styles/dual.ass` を開く
2. `Shift+F3` でスタイルマネージャーを開く
3. フォント、サイズ、色、縁取りなどを編集
4. 保存すればOK（次回実行時に自動読み込み）

### 方法二：.assファイルを直接編集

ASS色の書式は **BGR**（RGBではない！）：

| 色 | ASS値 |
|------|--------|
| 白 | `&H00FFFFFF` |
| 薄灰 | `&H00D0D0D0` |
| 黄 | `&H00FFFF00` |
| 赤 | `&H000000FF` |

配置（テンキー対応）：

```
7  8  9   ← 上部
4  5  6   ← 中部
1  2  3   ← 下部（2 = 下部中央、デフォルト）
```

### バイリンガル字幕のレイアウト

`dual.ass` は2行重ね：
- **上段（Dual_ZH）：** 中国語、白、Microsoft JhengHei、80pt、{\fsp4} 行間
- **下段（Dual_JP）：** 日本語、薄灰色、Arial、24pt

---

## 対応翻訳バックエンド

| バックエンド | 環境変数 | デフォルトモデル |
|------|---------|---------|
| DeepSeek | `DEEPSEEK_API_KEY` | deepseek-chat |
| OpenAI | `OPENAI_API_KEY` | gpt-4o-mini |
| MiniMax | `MINIMAX_API_KEY` | MiniMax-Text-01 |
| Google Gemini | `GOOGLE_API_KEY` | gemini-2.0-flash |
| Groq | `GROQ_API_KEY` | llama-3.1-8b-instant |
| Ollama（ローカル） | `OLLAMA_BASE_URL` + `OLLAMA_MODEL` | カスタム |
| Anthropic | `ANTHROPIC_API_KEY` | claude-sonnet-4 |
| 智譜 AI | `ZHIPU_API_KEY` | glm-4-flash |
| Google Translate | Key不要 | —（免费代替案） |

---

## プロジェクト構造

```
youtube_translator(JP2CN)/
├── main.py                     # エントリーポイント、6ステップパイプライン
├── .env / .env.example         # 設定（API Key、パスなど）
├── requirements.txt
├── README_zh.md / README_ja.md
│
├── src/
│   ├── downloader.py           # yt-dlp 動画+音声的分離ダウンロード
│   ├── transcriber.py          # Whisper 音声 → テキスト
│   ├── translator.py           # 翻訳ファクトリー（自動バックエンド選択+一括翻訳）
│   ├── subtitle_builder.py     # preset .assからスタイルを読込み、字幕生成
│   ├── utils.py                # ユーティリティ（タイムスタンプ形式、ffmpeg結合など）
│   │
│   └── backends/               # 翻訳バックエンド実装
│       ├── base.py             # 抽象基底クラス（TranslationBackend）
│       ├── deepseek.py
│       ├── openai.py
│       ├── minimax.py
│       ├── gemini.py
│       ├── groq.py
│       ├── ollama.py
│       ├── anthropic.py
│       ├── zhipu.py
│       └── google.py           # Google Translate（代替案）
│
└── presets/
    └── styles/
        ├── dual.ass            # バイリンガルスタイルテンプレート（Aegisub編集対応）
        └── zh.ass              # 中国語のみスタイルテンプレート
```

---

## トラブルシューティング

### Q: "ffmpeg not found" エラー
A: `FFMPEG_PATH` が `.env` に正しく設定されているか確認。パスは `Library/bin`（`Scripts` ではない）を指している必要があります。

### Q: 翻訳エラー "API key not found"
A: `.env` が作成されているか、Keyが正しく入力されているか、前後にスペースが入っていないかを確認。

### Q: Whisperの文字起こし精度が悪い / 内容が抜ける
A:
- `--model large`（デフォルト）を使用しているか確認
- 前30秒がBGM/無音パートの場合は正常動作（Whisperは音声のみ認識）
- 音声品質の問題が疑われる場合 `--no-video` で bestaudio を強制使用

### Q: 字幕のフォントを変更したい
A: `presets/styles/dual.ass` と `zh.ass` の `Fontname` フィールドを直接編集。PCにインストール済みのChineseフォントを指定（`Microsoft JhengHei`、`SimHei`、`PingFang SC` など）。

### Q: 動画ダウンロードが失敗する
A: YouTubeの地域制限またはネットワーク問題の可能性。VPNを確認。

---

## License

MIT License
