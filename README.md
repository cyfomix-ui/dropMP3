# DropMP3

[日本語](#日本語) | [English](#english)

## 日本語

DropMP3 は、音楽ファイルをドラッグ＆ドロップしてすぐ再生できる Windows 向けの小型音楽プレイヤーです。  
個人用途の「すぐ確認したい」「大きなプレイヤーは要らない」「歌詞やジャケットも見たい」という使い方を前提に、Python + PySide6 で構築しています。

### 主な機能

- 音楽ファイルやフォルダのドラッグ＆ドロップ再生
- プレイリストの追加、並び替え、複数選択、削除
- 埋め込みジャケット画像の表示
- ミニプレイヤー表示
- タスクトレイ格納
- ワンショット再生
- SRT / SRT2 字幕表示
- 日本語 / 英語 UI 切り替え
- M3U / M3U8 / WPL / PLS / TXT ベースのリスト読み込み
- M3U8 / WPL 形式でのプレイリスト保存
- `ffprobe` によるメディア情報確認
- Whisper を使った字幕生成依頼

### 動作環境

- Windows
- Python 3 系
- PySide6
- mutagen

任意機能:

- `ffprobe` : メディア情報の詳細表示
- `openai-whisper` または `whisper.exe` : 字幕生成
- Ollama : 字幕の翻訳補助

### セットアップ

```powershell
python -m pip install --upgrade pip
python -m pip install --upgrade PySide6 mutagen
```

字幕生成も使う場合:

```powershell
python -m pip install --upgrade openai-whisper
```

`ffprobe` を使う場合は FFmpeg をインストールし、`ffprobe.exe` を `PATH` に追加してください。

### 起動方法

```powershell
python .\dropMP3.py
```

UI 言語を固定したい場合:

```powershell
$env:DROPMP3_UI_LANG="ja"
python .\dropMP3.py

$env:DROPMP3_UI_LANG="en"
python .\dropMP3.py
```

### 使い方

1. 音楽ファイル、フォルダ、またはプレイリストファイルをウィンドウへドロップします。
2. ドロップした曲がそのまま再生され、プレイリストに追加されます。
3. 左ドロワーから並び替え、複数選択、削除、保存を行えます。
4. ジャケット画像のダブルクリックでミニプレイヤー表示へ切り替えできます。
5. 字幕ファイルが見つかれば再生時間に合わせて表示されます。

### 字幕まわり

DropMP3 は `.srt` と `.srt2` を扱えます。字幕は主に以下の場所から検索します。

- 音楽ファイルと同じフォルダ
- 音楽ファイル側の `srt` / `SRT` フォルダ
- アプリ側の `_conf\srt`

Whisper による字幕生成では、出力先として `_conf\srt` を使います。  
日本語 / 英語の両方を出力する設定では、`.srt` と `.srt2` を使い分けます。

### ビルド

PyInstaller による EXE 化用スクリプトを同梱しています。

```powershell
powershell -ExecutionPolicy Bypass -File .\build.ps1
```

別バージョンのビルドスクリプトとして `build_dropmp3.ps1` もあります。

### ディレクトリ構成

```text
dropMP3.py              メインアプリ
build.ps1               EXE ビルドスクリプト
build_dropmp3.ps1       代替ビルドスクリプト
_conf/                  設定、Help、保存済みリスト、字幕
Doc/                    利用ガイド、機能メモ、記事草稿
pyinstaller_assets/     Splash 画像などのビルド用素材
```

`_conf` 配下の主な内容:

- `_conf\DropMp3.ini` : 設定ファイル
- `_conf\html` : Help HTML
- `_conf\lst` : 保存済みプレイリスト
- `_conf\srt` : 生成済み字幕

### 公開時の補足

- 現状は Windows デスクトップ利用を前提にしています。
- リポジトリ公開時は、必要に応じて `LICENSE` を追加してください。
- `dist/` や `_conf/` の個人データは `.gitignore` 対象です。公開前に内容を確認してください。

## English

DropMP3 is a compact Windows music player designed for immediate drag-and-drop playback.  
It is built with Python and PySide6 for a personal workflow where you want to preview audio quickly, keep the UI small, and still have access to jacket art and subtitles.

### Features

- Drag-and-drop playback for audio files and folders
- Playlist add, reorder, multi-select, and delete
- Embedded album art display
- Mini player mode
- Minimize to system tray
- One-shot playback mode
- SRT / SRT2 subtitle display
- Japanese / English UI switching
- Playlist import from M3U / M3U8 / WPL / PLS / TXT-based lists
- Playlist export in M3U8 / WPL format
- Media property inspection with `ffprobe`
- Subtitle generation requests via Whisper

### Requirements

- Windows
- Python 3
- PySide6
- mutagen

Optional integrations:

- `ffprobe` : detailed media metadata view
- `openai-whisper` or `whisper.exe` : subtitle generation
- Ollama : subtitle translation support

### Setup

```powershell
python -m pip install --upgrade pip
python -m pip install --upgrade PySide6 mutagen
```

If you also want subtitle generation:

```powershell
python -m pip install --upgrade openai-whisper
```

If you want to use `ffprobe`, install FFmpeg and add `ffprobe.exe` to your `PATH`.

### Run

```powershell
python .\dropMP3.py
```

To force the UI language:

```powershell
$env:DROPMP3_UI_LANG="ja"
python .\dropMP3.py

$env:DROPMP3_UI_LANG="en"
python .\dropMP3.py
```

### Basic Usage

1. Drop audio files, folders, or playlist files onto the window.
2. The dropped track starts playing immediately and is added to the playlist.
3. Use the left drawer to reorder, multi-select, delete, and save playlist items.
4. Double-click the jacket image to switch to mini player mode.
5. If subtitle files are found, they are displayed in sync with playback.

### Subtitle Handling

DropMP3 supports both `.srt` and `.srt2` subtitle files. It mainly searches in:

- the same folder as the audio file
- `srt` / `SRT` folders near the audio file
- the app-side `_conf\srt` folder

When generating subtitles through Whisper, output files are written to `_conf\srt`.  
If both Japanese and English output are enabled, the app uses `.srt` and `.srt2` separately.

### Build

The repository includes a PyInstaller build script for creating a Windows executable.

```powershell
powershell -ExecutionPolicy Bypass -File .\build.ps1
```

An alternative build script is also available as `build_dropmp3.ps1`.

### Directory Layout

```text
dropMP3.py              main application
build.ps1               EXE build script
build_dropmp3.ps1       alternative build script
_conf/                  settings, help files, saved playlists, subtitles
Doc/                    guides, feature notes, article drafts
pyinstaller_assets/     splash images and build assets
```

Main `_conf` contents:

- `_conf\DropMp3.ini` : settings file
- `_conf\html` : help HTML files
- `_conf\lst` : saved playlists
- `_conf\srt` : generated subtitles

### Notes for Public Release

- The current project targets Windows desktop use.
- Add a `LICENSE` file before publishing if needed.
- `dist/` and personal data under `_conf/` are ignored by `.gitignore`; review them before release.
