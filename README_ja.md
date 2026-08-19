# YouTube JP→CN Subtitle Generator
# YouTube日本語音声 → 中国語字幕生成ツール

[プロジェクトトップ](README.md) · [中文文档](README_zh.md)

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
[3] OpenAI whisper-1 で日本語音声 → タイムスタンプ付きテキスト化
    ↓
[4] OpenAI一括翻訳：日本語 → 中国語（TRANSLATION_BATCH_SIZEで指定）
    ↓
[5] ASS字幕生成（バイリンガル + 中文のみ）
    ↓
[6] 動画 + 音声を結合 → 最終MP4（一時ファイルを自動削除）
    ↓
[7] 任意：zh.ass / dual.ass を焼き込み → 確認後にBilibiliへ投稿
```

---

## 環境構築

### 1. conda環境の作成

```powershell
conda create -n subtitle python=3.11
conda activate subtitle
```

本プロジェクトは Python 3.10 以降の構文を使用し、現在の公開前テストは Python 3.11 で実施しています。

### 2. 依存関係のインストール

現在の yt-dlp で YouTube を取得するには、プレイヤーチャレンジ処理用の Node.js 22 以上が必要です（[yt-dlp EJSドキュメント](https://github.com/yt-dlp/yt-dlp/wiki/EJS)）。先に確認してください：

```powershell
node --version
```

```powershell
# ffprobe/ffmpeg（conda）
conda install -c conda-forge ffmpeg

# Python依存
pip install -r requirements.txt
```

### 3. .env の設定

```powershell
Copy-Item .env.example .env
```

`.env` を編集し、OpenAI API Keyと使用バックエンドを指定します：

```env
OPENAI_API_KEY=OpenAIのAPIキー
TRANSCRIPTION_BACKEND=openai
OPENAI_TRANSCRIPTION_MODEL=whisper-1
TRANSLATION_BACKEND=openai
OPENAI_TRANSLATION_MODEL=gpt-4o-mini
TRANSLATION_BATCH_SIZE=50

# その他の翻訳バックエンド（TRANSLATION_BACKEND変更時のみ使用）
DEEPSEEK_API_KEY=
MINIMAX_API_KEY=       # MiniMax-Text-01
GOOGLE_API_KEY=        # Gemini 2.0 Flash
GROQ_API_KEY=         # Llama 3.1 8B（無料、高速）
ANTHROPIC_API_KEY=     # Claudeシリーズ
ZHIPU_API_KEY=         # 智譜GLM-4-Flash（中国本土向け）
# Google Translate（無料の代替手段、Key不要）

# ローカルモデル
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=llama3

# ツールパス
FFMPEG_PATH=C:\path\to\miniconda3\envs\subtitle\Library\bin
YTDLP_PATH=C:\path\to\miniconda3\envs\subtitle\Scripts\yt-dlp.exe
YTDLP_JS_RUNTIME=node
YTDLP_FORCE_IPV4=true
YTDLP_PLAYER_CLIENT=web_embedded
BILIUP_PATH=C:\path\to\miniconda3\envs\subtitle\Scripts\biliup.exe

# 出力ディレクトリ（省略時：{script_dir}/downloads/）
OUTPUT_DIR=C:\path\to\output
```

デフォルトは OpenAI 固定です。`TRANSLATION_BACKEND=auto` に変更した場合のみ、設定済みのバックエンドを自動選択します。

`YTDLP_PATH` は `Scripts` ディレクトリではなく `yt-dlp.exe` 自体を指定してください。`FFMPEG_PATH` は `ffmpeg.exe`、またはそれを含むディレクトリを指定できます。秘密鍵を含む `.env` は `.gitignore` の対象です。GitHubへ強制追加しないでください。

中国語訳では、読点を空白へ置換し、句点を削除する本プロジェクトの字幕用表記ルールを適用します。日本語原文は変更しません。

---

## 使い方

### Web UI（推奨）

```powershell
conda activate subtitle
pip install -r requirements.txt
python web.py
```

または PowerShell で `.\start_web.ps1` を実行し、ブラウザで `http://127.0.0.1:8787` を開きます。Windowsでは `start_web.bat` をダブルクリックしても起動できます。BATは `%USERPROFILE%\miniconda3\envs\subtitle\python.exe` を使用するため、別の場所に環境を作成した場合は `PYTHON_EXE` を変更してください。API Key は `.env` からのみ読み込まれ、ブラウザには送信されません。用語集は `data/glossary.json` に保存されます。

高度な設定の「長すぎる字幕を自動分割」はデフォルトで有効です。翻訳後の中国語が動画幅・フォント・余白・最大行数から算出した容量を超えると、中国語と日本語を対応させたまま複数の字幕イベントへ分割し、時間軸も分けます。Whisperのword timestampを優先し、取得できない場合は安全な比例分割へフォールバックします。各イベントは原則0.7秒以上です。密度は「短文 / 標準 / コンパクト」、最大行数は1〜3から選択できます。

Whisperへの音声送信は1回のままで、word timestampを取得しても2回目の文字起こしは発生しません。OpenAI翻訳バックエンドでは、分割が必要な長文字幕ごとに現在のテキストモデルを追加で1回呼び出して自然な対応位置を選びます。通常の字幕とローカルフォールバック分割には、この追加呼び出しはありません。

タスク完了後は「字幕編集」タブで動画と字幕を同期再生し、中国語・日本語・開始/終了時刻を編集できます。字幕の追加、削除、分割、結合、時刻微調整に加え、フォント、サイズ、色、縁取り、影、位置も変更できます。保存時は元ASSを `.kotoba/backups/` に退避し、`*_zh.ass` と `*_dual.ass` を同時に更新します。「現在フレームを正確にプレビュー」ではFFmpegによる最終ASS描画を確認できます。動画未取得のタスクも文字編集は可能ですが、動画プレビューは利用できません。

タスク完了後、校正済みの `*_zh.ass` または `*_dual.ass` を選択して字幕を焼き込めます。出力は `*_hardsub_zh.mp4` / `*_hardsub_dual.mp4`（H.264、CRF 18、yuv420p、faststart）で、元動画とASSは上書きしません。

Bilibili投稿は第三者製CLI `biliup` を利用します。「Bilibili QRログイン」で本人がログインした後、動画・タイトル・カテゴリ・タグなどを入力してください。概要欄はデフォルトで空です。転載元URLには元のYouTube URLが自動入力されます。「今すぐ公開投稿する」確認を毎回チェックしない限り投稿されません。認証情報は `%LOCALAPPDATA%\KotobaStudio\bilibili\cookies.json` に保存され、プロジェクトやブラウザには渡しません。

カテゴリは [biliupのカテゴリ一覧](https://biliup.github.io/tid-ref.html) を使った「大カテゴリ → 動画カテゴリ」の2段階選択です。中国語名を選ぶと数値IDが自動設定され、デフォルトは「時尚 → 穿搭（158）」です。サムネイルを使う場合、拡張子が `.jpg` でも実体がWebPのYouTube画像を標準RGB JPEGへ変換してから送信します。チェックを外せばBilibili側の自動フレームを利用できます。

### 基本構文

```powershell
# 環境有効化後
conda activate subtitle
$env:PYTHONUTF8="1"
python main.py "https://youtu.be/HtpzR17uq0w"
```

デフォルトは OpenAI `whisper-1` で文字起こしし、`gpt-4o-mini` で翻訳します。

### コマンドライン引数

| 引数 | 説明 | デフォルト |
|------|------|-----------|
| `url` | YouTube動画URL（必須） | — |
| `--transcription-backend` | 文字起こしバックエンド（openai/local） | `openai` |
| `--model` | ローカルWhisperモデル（OpenAIモードでは無視） | `large` |
| `--output` | 出力ディレクトリ（CLI > .env > デフォルト） | `{script_dir}/downloads/` |
| `--no-video` | 動画ダウンロードをスキップ（音声のみ） | False |
| `--no-thumb` | サムネイルダウンロードをスキップ | False |
| `--separator` | 文字起こし前のボーカル抽出を有効化 | デフォルト無効 |
| `--no-separator` | ボーカル抽出を明示的に無効化（互換用） | — |
| `--no-auto-split` | 長すぎる字幕の自動時間軸分割を無効化 | デフォルト有効 |
| `--subtitle-density` | 自動分割密度：short / standard / compact | `standard` |
| `--subtitle-lines` | 1イベントの最大表示行数：1 / 2 / 3 | `2` |
| `--prompt` | Whisperへ渡す日本語認識ヒント | 組み込みの日本語会話ヒント |

### 使用例

```powershell
# ローカルWhisper mediumを使用
python main.py "https://youtu.be/HtpzR17uq0w" --transcription-backend local --model medium

# 音声のみ（字幕作成目的のみ、DL高速化）
python main.py "https://youtu.be/HtpzR17uq0w" --no-video

# 必要な場合のみボーカル抽出を有効化
python main.py "https://youtu.be/HtpzR17uq0w" --separator
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
├── {タイトル}_hardsub_zh.mp4 # 任意：中国語字幕焼き込み版
├── {タイトル}_hardsub_dual.mp4 # 任意：バイリンガル焼き込み版
├── {タイトル}_info.txt       # メタデータ（タイトル、URL、概要350字）
├── {タイトル}_audio.m4a      # --no-video の場合のみ保持
└── .kotoba/                  # Web編集用データとバックアップ
```

> 通常の動画ダウンロードでは、`_video_raw.mp4` と `_audio.m4a` は結合成功後に自動削除され、`_video.mp4` のみが残ります。`--no-video` では `_video.mp4` を生成せず、音声ファイルを保持します。

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

`dual.ass` は上下分割：
- **上部（Dual_ZH）：** 中国語、白、Microsoft JhengHei
- **下部（Dual_JP）：** 日本語、薄灰色、Arial
- 字幕生成時に画面サイズへ合わせてフォント、縁取り、余白を自動調整し、CJK長文も安全に改行

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
| Google Translate | Key不要 | —（無料の代替手段） |

---

## プロジェクト構造

```
youtube_translator(JP2CN)/
├── README.md                   # GitHubプロジェクト入口
├── main.py                     # CLIエントリーポイント
├── web.py                      # ローカルFastAPI Web UI
├── start_web.bat / .ps1       # Windows起動スクリプト
├── .env / .env.example         # 設定（API Key、パスなど）
├── .gitignore / LICENSE        # 公開除外設定とライセンス
├── requirements.txt
├── README_zh.md / README_ja.md
│
├── src/
│   ├── downloader.py           # yt-dlp 動画+音声的分離ダウンロード
│   ├── transcriber.py          # Whisper 音声 → テキスト
│   ├── translator.py           # 翻訳ファクトリー（自動バックエンド選択+一括翻訳）
│   ├── subtitle_builder.py     # preset .assからスタイルを読込み、字幕生成
│   ├── subtitle_editor.py      # Web校正、ASS同期保存、バックアップ、プレビュー
│   ├── subtitle_splitter.py    # 表示容量判定、意味対応分割、時間軸分割
│   ├── burner.py               # FFmpeg字幕焼き込みと進捗
│   ├── bilibili_uploader.py    # biliupログイン状態・投稿アダプター
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
├── web/static/                 # Web UIのHTML、CSS、JavaScript
├── tests/                      # unittest自動テスト
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
- OpenAIモードは `.env` の `OPENAI_TRANSCRIPTION_MODEL=whisper-1` を使用し、`--model` は無視されます
- ローカルモードでは `--transcription-backend local --model large` を指定できます
- 前30秒がBGM/無音パートの場合は正常動作（Whisperは音声のみ認識）
- `--no-video` は映像のダウンロードだけを省略します。音声は常に `bestaudio` を使用します
- BGMやノイズの影響が大きい場合は `--separator` を試せますが、処理時間とモデル資源が増えます

### Q: 字幕のフォントを変更したい
A: `presets/styles/dual.ass` と `zh.ass` の `Fontname` フィールドを直接編集。PCにインストール済みのChineseフォントを指定（`Microsoft JhengHei`、`SimHei`、`PingFang SC` など）。

### Q: 動画ダウンロードが失敗する
A: YouTubeの地域制限またはネットワーク問題の可能性。VPNを確認。

### Q: OpenAIで音声が25 MBを超えていると表示される
A: 現在のOpenAI文字起こしは音声全体を1回で送信し、25 MBを超える場合は送信前に停止します。音声を圧縮または分割してください。自動分割アップロードはまだ実装されていません。

### Q: Bilibili投稿で `-400` リクエストエラーが返る
A: カテゴリ、タイトル、タグ、投稿タイプ、転載元URLが有効か、ログイン情報が期限切れでないか確認してください。Web UIはbiliup/Bilibiliの検証を回避せず、返されたエラーを表示します。

### Q: 92%の動画結合で `[WinError 5]` が表示される
A: Windowsが `.env` の `ffmpeg.exe` 実行を拒否しています。旧サービスを終了し、通常のPowerShellから `.\start_web.ps1` を実行してください。同じ動画を再送信すると既存ASSを再利用し、OpenAI文字起こしと翻訳をスキップします。

---

## テストとGitHub公開前チェック

テストはPython標準の `unittest` で実行できます。pytestは必須ではありません。

```powershell
conda activate subtitle
python -m unittest discover -s tests -v
```

公開前に `git status --short` を確認し、`.env`、`data/`、`downloads/`、ローカルモデル、音声・動画、字幕編集バックアップがステージされていないことを確認してください。`data/glossary.json` はローカル用語集のためデフォルトでは公開されません。必要な場合は別途、安全な場所へバックアップしてください。

---

## License

[MIT License](LICENSE)
