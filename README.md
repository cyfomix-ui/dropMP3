# DropMP3

DropMP3 は、音楽ファイルをドラッグ＆ドロップしてすぐ再生できる Windows 向けの小型音楽プレイヤーです。  
個人用途の「すぐ確認したい」「大きなプレイヤーは要らない」「歌詞やジャケットも見たい」という使い方を前提に、Python + PySide6 で構築しています。

## 主な機能

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

## 動作環境

- Windows
- Python 3 系
- PySide6
- mutagen

任意機能:

- `ffprobe` : メディア情報の詳細表示
- `openai-whisper` または `whisper.exe` : 字幕生成
- Ollama : 字幕の翻訳補助

## セットアップ

```powershell
python -m pip install --upgrade pip
python -m pip install --upgrade PySide6 mutagen
```

字幕生成も使う場合:

```powershell
python -m pip install --upgrade openai-whisper
```

`ffprobe` を使う場合は FFmpeg をインストールし、`ffprobe.exe` を `PATH` に追加してください。

## 起動方法

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

## 使い方

1. 音楽ファイル、フォルダ、またはプレイリストファイルをウィンドウへドロップします。
2. ドロップした曲がそのまま再生され、プレイリストに追加されます。
3. 左ドロワーから並び替え、複数選択、削除、保存を行えます。
4. ジャケット画像のダブルクリックでミニプレイヤー表示へ切り替えできます。
5. 字幕ファイルが見つかれば再生時間に合わせて表示されます。

## 字幕まわり

DropMP3 は `.srt` と `.srt2` を扱えます。字幕は主に以下の場所から検索します。

- 音楽ファイルと同じフォルダ
- 音楽ファイル側の `srt` / `SRT` フォルダ
- アプリ側の `_conf\srt`

Whisper による字幕生成では、出力先として `_conf\srt` を使います。  
日本語 / 英語の両方を出力する設定では、`.srt` と `.srt2` を使い分けます。

## ビルド

PyInstaller による EXE 化用スクリプトを同梱しています。

```powershell
powershell -ExecutionPolicy Bypass -File .\build.ps1
```

別バージョンのビルドスクリプトとして `build_dropmp3.ps1` もあります。

## ディレクトリ構成

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

## 公開時の補足

- 現状は Windows デスクトップ利用を前提にしています。
- リポジトリ公開時は、必要に応じて `LICENSE` を追加してください。
- `dist/` や `_conf/` の個人データは `.gitignore` 対象です。公開前に内容を確認してください。
