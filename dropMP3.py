import sys
import os
import json
import time
import random
import math
import re
import socket
import threading
import http.server
import socketserver
import mimetypes
import shutil
import subprocess
import tempfile
import hashlib
import xml.etree.ElementTree as ET
import urllib.error
import urllib.request
import urllib.parse
from datetime import datetime
from pathlib import Path
from html import escape
from typing import Optional

from PySide6.QtCore import (
    Qt,
    QUrl,
    QTimer,
    QSettings,
    qInstallMessageHandler,
    QtMsgType,
    QObject,
    Signal,
    QPoint,
    QPointF,
    QSize,
    QRect,
    QEvent,
    QMimeData,
    QProcess,
    QProcessEnvironment,
)
from PySide6.QtGui import (
    QAction,
    QPixmap,
    QPainter,
    QFontMetrics,
    QColor,
    QFont,
    QIcon,
    QKeySequence,
    QPen,
    QDrag,
    QDesktopServices,
    QShortcut,
    QTextCursor,
    QCursor,
)
from PySide6.QtWidgets import (
    QApplication,
    QWidget,
    QLabel,
    QPushButton,
    QComboBox,
    QSlider,
    QVBoxLayout,
    QHBoxLayout,
    QGridLayout,
    QMenu,
    QSizePolicy,
    QTextEdit,
    QTextBrowser,
    QFileDialog,
    QMessageBox,
    QListWidget,
    QListWidgetItem,
    QWidgetAction,
    QToolTip,
    QFrame,
    QAbstractItemView,
    QSplitter,
    QSystemTrayIcon,
    QStyle,
    QCheckBox,
    QDialog,
    QPlainTextEdit,
    QDialogButtonBox,
    QTreeWidget,
    QTreeWidgetItem,
    QHeaderView,
    QProgressBar,
    QProgressDialog,
    QFontComboBox,
    QSpinBox,
    QColorDialog,
    QInputDialog,
)
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput, QMediaDevices

from mutagen import File as MutagenFile


AUDIO_EXTS = {
    ".mp3", ".wav", ".flac", ".ogg", ".m4a", ".aac", ".wma", ".aiff", ".aif"
}

PLAYLIST_EXTS = {".m3u", ".m3u8", ".wpl", ".pls"}
TEXT_PLAYLIST_EXTS = {".txt", ".list", ".playlist"}
LIST_FILE_EXTS = PLAYLIST_EXTS | TEXT_PLAYLIST_EXTS

APP_START_MONO = time.perf_counter()
APP_NAME = "DropMP3"
APP_GITHUB_REPO = "cyfomix-ui/dropMP3"
APP_VERSION_FALLBACK = "1.00"
APP_VERSION_FILE = "_conf/app_version.xml"
APP_VERSION_LEGACY_FILE = "_conf/app_version.json"
APP_UPDATE_API_URL = f"https://api.github.com/repos/{APP_GITHUB_REPO}/releases/latest"
APP_UPDATE_TIMEOUT_SEC = 15


def read_app_version(base_dir: Path | None = None) -> str:
    if base_dir is not None:
        version_path = Path(base_dir) / APP_VERSION_FILE
        try:
            if version_path.exists():
                root = ET.fromstring(version_path.read_text(encoding="utf-8"))
                value = str(root.findtext("version", "") or "").strip()
                if value:
                    return value
        except Exception as exc:
            app_log(f"[UPDATE] version file read failed: {exc}")
        legacy_path = Path(base_dir) / APP_VERSION_LEGACY_FILE
        try:
            if legacy_path.exists():
                payload = json.loads(legacy_path.read_text(encoding="utf-8"))
                value = str(payload.get("version", "") or "").strip()
                if value:
                    return normalize_version_text(value)
        except Exception as exc:
            app_log(f"[UPDATE] legacy version file read failed: {exc}")
    return APP_VERSION_FALLBACK


def format_version_label(version: str) -> str:
    value = normalize_version_text(version) or APP_VERSION_FALLBACK
    return f"v{value}"


def normalize_version_text(text: str) -> str:
    value = str(text or "").strip()
    if value.lower().startswith("ver "):
        value = value[4:].strip()
    if value.lower().startswith("v"):
        value = value[1:].strip()
    return value


def version_sort_key(text: str) -> tuple:
    normalized = normalize_version_text(text)
    parts: list[int | str] = []
    for chunk in re.split(r"[.\-_+]", normalized):
        if not chunk:
            continue
        if chunk.isdigit():
            parts.append(int(chunk))
        else:
            parts.append(chunk.lower())
    return tuple(parts)


def fetch_latest_release_metadata() -> dict:
    req = urllib.request.Request(
        APP_UPDATE_API_URL,
        headers={
            "User-Agent": f"{APP_NAME}-updater",
            "Accept": "application/vnd.github+json",
        },
    )
    with urllib.request.urlopen(req, timeout=APP_UPDATE_TIMEOUT_SEC) as resp:
        return json.loads(resp.read().decode("utf-8"))


def select_release_asset(release: dict) -> dict | None:
    assets = release.get("assets") or []
    if not isinstance(assets, list):
        return None
    candidates = []
    for asset in assets:
        if not isinstance(asset, dict):
            continue
        name = str(asset.get("name", "") or "")
        lowered = name.lower()
        score = 0
        if lowered.endswith(".zip"):
            score += 100
        if lowered.endswith(".exe"):
            score += 60
        if "dropmp3" in lowered:
            score += 20
        if "portable" in lowered:
            score += 5
        if score > 0:
            candidates.append((score, asset))
    if not candidates:
        return None
    candidates.sort(key=lambda item: (-item[0], str(item[1].get("name", ""))))
    return candidates[0][1]


def collect_startup_audio_files(argv: list[str]) -> list[Path]:
    files: list[Path] = []
    seen: set[str] = set()
    for raw in argv:
        text = str(raw or "").strip().strip('"')
        if not text:
            continue
        path = Path(text)
        try:
            if not path.exists() or not path.is_file():
                continue
        except Exception:
            continue
        if path.suffix.lower() not in AUDIO_EXTS:
            continue
        try:
            resolved = path.resolve()
        except Exception:
            resolved = path
        key = str(resolved).lower()
        if key in seen:
            continue
        seen.add(key)
        files.append(resolved)
    return files


def try_forward_one_shot_to_existing_instance(paths: list[Path], port: int = 8765) -> bool:
    if not paths:
        return False
    target = Path(paths[0])
    payload = urllib.parse.urlencode({"path": str(target)}).encode("utf-8")
    req = urllib.request.Request(
        f"http://127.0.0.1:{int(port)}/api/oneshot",
        data=payload,
        headers={"Content-Type": "application/x-www-form-urlencoded; charset=utf-8"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=1.2) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return bool(data.get("ok"))
    except Exception:
        return False


class UpdateWorkerBridge(QObject):
    checkFinished = Signal(dict)
    progressChanged = Signal(int, str)
    downloadFinished = Signal(dict)
    updateError = Signal(dict)



# -----------------------------------------------------------------------------
# UI language support
# -----------------------------------------------------------------------------
def _detect_japanese_ui_language() -> bool:
    """Return True when the current OS/UI locale appears to be Japanese."""
    try:
        from PySide6.QtCore import QLocale
        if QLocale.system().language() == QLocale.Language.Japanese:
            return True
    except Exception:
        pass
    try:
        if sys.platform.startswith("win"):
            import ctypes
            lang_id = ctypes.windll.kernel32.GetUserDefaultUILanguage()
            # Primary language 0x11 = Japanese.
            if (int(lang_id) & 0x3FF) == 0x11:
                return True
    except Exception:
        pass
    try:
        import locale
        loc = locale.getlocale()[0] or locale.getdefaultlocale()[0] or ""
        return str(loc).lower().startswith("ja")
    except Exception:
        return False


_FORCED_UI_LANGUAGE = str(os.environ.get("DROPMP3_UI_LANG", "")).strip().lower()
if _FORCED_UI_LANGUAGE in ("ja", "jp", "japanese"):
    APP_UI_LANGUAGE = "ja"
elif _FORCED_UI_LANGUAGE in ("en", "english"):
    APP_UI_LANGUAGE = "en"
else:
    APP_UI_LANGUAGE = "ja" if _detect_japanese_ui_language() else "en"

_UI_TRANSLATIONS_EN = {
    '\n\n失敗:\n': '\n\nFailed:\n',
    '\nSRT文字コード正規化に失敗: ': '\nFailed to normalize SRT text encoding: ',
    '\n[警告] 幻聴字幕の可能性あり。検出例:': '\n[Warning] Possible hallucinated subtitles. Examples:',
    '\nモデル: medium': '\nModel: medium',
    '\n中止要求を送信しました...': '\nCancel request sent...',
    '\n出力: ': '\nOutput: ',
    '\n字幕: あり': '\nSubtitles: available',
    '\n完了しました。': '\nCompleted.',
    '\nWhisper起動エラー: ': '\nWhisper startup error: ',
    'ffprobe の実行に失敗しました。\n\n': 'Failed to run ffprobe.\n\n',
    'ffprobe のJSON解析に失敗しました。\n\n': 'Failed to parse ffprobe JSON.\n\n',
    'ストリーム #': 'Stream #',
    '\n怪しい字幕行を除去して保存しました: ': '\nRemoved suspicious subtitle lines and saved: ',
    '\n終了しました: exit_code=': '\nFinished: exit_code=',
    '\n言語: ': '\nLanguage: ',
    '  ... 他 ': '  ... and ',
    ' 行': ' lines',
    ' 行削除': ' lines removed',
    ' 行検出しました。必要なら『怪しい字幕行を除去して保存』を押してください。': " suspicious lines. Use 'Remove suspicious subtitle lines and save' if needed.",
    '1曲': 'One',
    'M3U8を作成': 'Create M3U8',
    'M3U8リストファイルの保存に失敗しました。\n\n': 'Failed to save the M3U8 playlist file.\n\n',
    'M3U8リストファイルを作成': 'Create M3U8 playlist file',
    'PATH上の whisper.exe / whisper.cmd、または python -m whisper を確認してください。': 'Check whisper.exe / whisper.cmd on PATH, or python -m whisper.',
    'SRTをメモ帳で開く': 'Open SRT in Notepad',
    'SRTファイルが見つかりません。Whisperのログを確認してください。': 'SRT file was not found. Check the Whisper log.',
    'SRTファイルはまだ作成されていません。\n\n': 'SRT file has not been created yet.\n\n',
    'SRTフォルダ作成失敗': 'Failed to create SRT folder',
    'SRT出力フォルダを作成できませんでした。\n\n': 'Could not create the SRT output folder.\n\n',
    'SRT未作成': 'SRT not created',
    'SRT除去保存失敗': 'Failed to clean/save SRT',
    'WPLを作成': 'Create WPL',
    'WPLリストファイルの保存に失敗しました。\n\n': 'Failed to save the WPL playlist file.\n\n',
    'WPLリストファイルを作成': 'Create WPL playlist file',
    'Whisper がInstallされていません。\n\n例:\n  pip install -U openai-whisper\n\nまたは whisper.exe をPATHに追加してください。': 'Whisper is not installed.\n\nExample:\n  pip install -U openai-whisper\n\nOr add whisper.exe to PATH.',
    'Whisperで字幕を作成中:\n': 'Creating subtitles with Whisper:\n',
    'Whisperプロセスを起動しました。': 'Whisper process started.',
    'Whisper実行中... mediumモデルで変換中': 'Whisper running... converting with medium model',
    'Whisper未検出': 'Whisper not found',
    'ffprobe がInstallされていません。\n\nFFmpegをInstallして、ffprobe.exe をPATHに追加してください。': 'ffprobe is not installed.\n\nInstall FFmpeg and add ffprobe.exe to PATH.',
    'ffprobe がエラーを返しました。': 'ffprobe returned an error.',
    'ffprobe のJSON解析に失敗しました。\n\n': 'Failed to parse ffprobe JSON.\n\n',
    'ffprobe の実行に失敗しました。\n\n': 'Failed to run ffprobe.\n\n',
    'ffprobeエラー': 'ffprobe error',
    'ffprobe実行失敗': 'ffprobe failed',
    'ffprobe未検出': 'ffprobe not found',
    'ffprobe解析失敗': 'ffprobe parse failed',
    '※ 古いSRTは依頼開始時に削除済みです。': '* Old SRT files were deleted when the request started.',
    'ここに音声ファイルをDrop': 'Drop audio files here',
    'なし': 'None',
    'クリック: 再生 / 一時停止\nダブルクリック: ミニプレイヤーモード切替\nホイール: 音量調整': 'Click: Play / Pause\nDouble-click: Toggle mini player mode\nWheel: Adjust volume',
    'コンテナ': 'Container',
    'コンテナ詳細': 'Container details',
    'コーデック': 'Codec',
    'コーデック詳細': 'Codec details',
    'サイズ': 'Size',
    'サンプルレート': 'Sample rate',
    'ストリーム #': 'Stream #',
    'ストリーム数': 'Streams',
    'タグ': 'Tags',
    'タグ(フォーマット)': 'Tags (format)',
    'タスクトレイに格納しました。アイコンをダブルクリックすると通常Playerに戻ります。': 'Minimized to the system tray. Double-click the icon to return to the normal player.',
    'チェックON: 曲の最初は元画像を表示し、約20秒後からプレイリスト内の画像をランダム表示します\nチェックOFF: 現在の曲に埋め込まれた元画像へ戻します': "ON: Shows the original artwork at the start, then random playlist artwork after about 20 seconds\nOFF: Restores the current track's embedded artwork",
    'チャンネルレイアウト': 'Channel layout',
    'チャンネル数': 'Channels',
    'ドラッグして再生位置を移動します': 'Drag to seek playback position',
    'バックアップ: ': 'Backup: ',
    'パス': 'Path',
    'ビットレート': 'Bitrate',
    'ファイルが見つかりません。\n\n': 'File not found.\n\n',
    'ファイルなし': 'No file',
    'ファイル名': 'File name',
    'ファイル名に日本語が含まれるため日本語固定': 'Japanese forced because the file name contains Japanese characters',
    'ファイル名順に並べ替え': 'Sort by file name',
    'フォント': 'Font',
    'フォーマット': 'Format',
    'フレームレート': 'Frame rate',
    'プレイリストをシャッフルします': 'Shuffle playlist',
    'プレイリストをファイル名順に並べ替えます': 'Sort playlist by file name',
    'プロパティ': 'Properties',
    'プロファイル': 'Profile',
    'マウスを載せてホイールで音量調節': 'Hover and use mouse wheel to adjust volume',
    'マウスホイールで音量調節': 'Use mouse wheel to adjust volume',
    'メモ帳でSRTを開けませんでした。\n\n': 'Could not open the SRT in Notepad.\n\n',
    'メモ帳起動失敗': 'Failed to open Notepad',
    'ランダムでイメージ表示中....': 'Showing random artwork...',
    'リストから削除': 'Remove from list',
    'リストをクリア': 'Clear list',
    'リストをシャッフル': 'Shuffle list',
    'リストを閉じる': 'Close list',
    'リストファイルを作成...': 'Create playlist file...',
    'テキストリストをDropしました': 'Text playlist dropped',
    'フルパス一覧テキストをどのように読み込みますか？': 'How do you want to import this full-path text list?',
    'リピート': 'Repeat',
    'リピート: 1曲\nクリックで全曲リピートに切替': 'Repeat: One\nClick to switch to repeat all',
    'リピート: Off\nクリックで1曲リピートに切替': 'Repeat: Off\nClick to repeat one',
    'リピート: 全曲\nクリックでOffに切替': 'Repeat: All\nClick to turn off',
    'リピート切替: Off → 1曲 → 全曲': 'Repeat: Off → One → All',
    'ログウィンドウを表示 / 非表示  F12': 'Show / hide log window  F12',
    'ワンショット再生モード ON/OFF\nONの間は、ドロップした曲をリストに追加せず一時再生します': 'One-shot playback mode ON/OFF\nWhen ON, dropped tracks play temporarily without being added to the list',
    '一部の字幕ファイルを削除できませんでした。\n\n削除済み:\n': 'Some subtitle files could not be deleted.\n\nDeleted:\n',
    '不明': 'Unknown',
    '中止': 'Cancel',
    '保存失敗': 'Save failed',
    '値': 'Value',
    '全曲': 'All',
    '再生 / 一時停止': 'Play / Pause',
    '再生 / 一時停止を切り替えます': 'Toggle play / pause',
    '再生リストを閉じる': 'Close playlist',
    '再生リストを開く': 'Open playlist',
    '再生リストを開く / 閉じる': 'Open / close playlist',
    '前の曲へ戻ります': 'Go to previous track',
    '古いSRTを削除できませんでした。\n\n': 'Could not delete old SRT files.\n\n',
    '古いSRT削除失敗': 'Failed to delete old SRT',
    '基本': 'Basic',
    '変換ログはここに逐次表示します。何も出ない時間があっても medium モデルのロード中/解析中の可能性があります。\n': 'Conversion logs are shown here. If nothing appears for a while, the medium model may still be loading or analyzing.\n',
    '失敗 / 中断': 'Failed / canceled',
    '字幕を表示': 'Show subtitles',
    '字幕を閉じる': 'Hide subtitles',
    '字幕ファイルを削除しました。': 'Subtitle files were deleted.',
    '字幕ファイルは見つかりませんでした。\n\n': 'Subtitle file was not found.\n\n',
    '字幕フォント / サイズ / 色を変更': 'Change subtitle font / size / color',
    'ここに曲をドロップすると、一時的にワンショット再生します': 'Drop a track here to play it temporarily as one-shot',
    '字幕フォント設定': 'Subtitle Font Settings',
    '字幕プレビュー / Subtitle Preview\nBroken glass mirrors, where two shadows meet': 'Subtitle Preview\nBroken glass mirrors, where two shadows meet',
    '字幕作成を開始します。': 'Starting subtitle creation.',
    '字幕依頼': 'Create subtitles',
    '字幕確認': 'Check subtitles',
    '字幕依頼 - ': 'Create subtitles - ',
    '字幕削除': 'Delete subtitles',
    'DropMp3 起動中': 'Starting DropMp3',
    '起動完了': 'Startup complete',
    'メイン画面を表示中...': 'Showing main window...',
    '前回の曲を復元中...': 'Restoring previous track...',
    'プレイリストを表示中...': 'Displaying playlist...',
    '保存済みプレイリストを確認中...': 'Checking saved playlist...',
    '字幕設定を読み込み中...': 'Loading subtitle settings...',
    '設定とプレイリストを復元中...': 'Restoring settings and playlist...',
    'タスクトレイを準備中...': 'Preparing system tray...',
    '操作を接続中...': 'Connecting controls...',
    'UIを構築中...': 'Building UI...',
    'メインウィンドウを準備中...': 'Preparing main window...',
    'アイコンを読み込み中...': 'Loading icons...',
    '字幕色を選択': 'Choose Subtitle Color',
    '完了': 'Done',
    '対象: ': 'Target: ',
    '幅': 'Width',
    '平均フレームレート': 'Average frame rate',
    '幻聴字幕の可能性あり: 怪しい字幕行を ': 'Possible hallucinated subtitles: detected ',
    '怪しい字幕行の除去に失敗しました。\n\n': 'Failed to remove suspicious subtitle lines.\n\n',
    '怪しい字幕行を除去して保存': 'Remove suspicious subtitle lines and save',
    '怪しい字幕行を除去して保存しました（': 'Removed suspicious subtitle lines and saved (',
    '怪しい定型字幕は検出されませんでした。': 'No suspicious boilerplate subtitle lines were detected.',
    '映像': 'Video',
    '映像コーデック': 'Video codec',
    '映像ビットレート': 'Video bitrate',
    '時間ベース': 'Time base',
    '曲がありません': 'No tracks',
    '更新日時': 'Modified',
    '次の字幕ファイルを削除しますか？\n\n': 'Delete the following subtitle files?\n\n',
    '次の曲': 'Next Track',
    '次の曲へ進みます': 'Go to next track',
    '画角': 'Frame size',
    '終了': 'Exit',
    '色を選択': 'Choose Color',
    '色形式': 'Pixel format',
    '色空間': 'Color space',
    '英語固定（日本語が混じる場合も英語優先）': 'English forced (English preferred even if Japanese is mixed)',
    '行削除）。バックアップも保存済みです。': ' lines removed). Backup was also saved.',
    '表示': 'Show',
    '設定メニューを開きます\nリスト作成、リストクリア、ログ表示などを操作できます': 'Open settings menu\nCreate lists, clear list, show logs, and more',
    '詳細情報: ': 'Details: ',
    '起動失敗': 'Startup failed',
    '起動準備中...': 'Preparing to start...',
    '長さ': 'Duration',
    '長さ (ms)': 'Duration (ms)',
    '長さ (秒)': 'Duration (sec)',
    '閉じる': 'Close',
    '音声': 'Audio',
    '音声コーデック': 'Audio codec',
    '音声ビットレート': 'Audio bitrate',
    '音量 ': 'Volume ',
    '項目': 'Item',
    '高さ': 'Height',
    'このアイコンに音楽ファイルをDropするとワンショットで再生されます': 'Drop an audio file on this icon to play it as a one-shot.',
    'ワンショット再生モード ON/OFF\nONの間は、ドロップした曲をリストに追加せず一時再生します\nこのアイコンに音楽ファイルをDropするとワンショットで再生されます': 'One-shot playback mode ON/OFF\nWhile ON, dropped tracks play temporarily without being added to the list.\nDrop an audio file on this icon to play it as a one-shot.',
    'このアイコンに音楽ファイルをDropするとワンショットで再生されます\nワンショット再生後、約0.3秒後に通常再生へ戻ります': 'Drop an audio file on this icon to play it as a one-shot.\nAfter one-shot playback, normal playback resumes after about 0.3 seconds.',
    'GitHub Release の更新確認': 'Check GitHub Release updates',
    'この実行形態では自動更新できません。Release ページを開きますか？': 'Auto-update is not available in this run mode. Open the Release page instead?',
    'ダウンロード中...': 'Downloading...',
    'ダウンロード完了': 'Download completed',
    'ダウンロード失敗': 'Download failed',
    '更新': 'Update',
    '更新を開始できませんでした。\n\n': 'Could not start the update.\n\n',
    '更新エラー': 'Update error',
    '更新確認': 'Update check',
    '更新確認を実行中です。': 'Update check is already running.',
    '更新確認に失敗しました。\n\n': 'Failed to check for updates.\n\n',
    '最新版です。': 'This is the latest version.',
    '最新版を確認できませんでした。': 'Could not determine the latest version.',
    '最新版があります。\n\n現在: ': 'A newer version is available.\n\nCurrent: ',
    '\n最新版: ': '\nLatest: ',
    '\n\n今すぐダウンロードして更新しますか？': '\n\nDownload and update now?',
    '更新用ファイルのダウンロードが完了しました。\n\n今すぐアプリを終了して更新を適用しますか？': 'The update package has been downloaded.\n\nQuit now and apply the update?',
    '配布アセットが見つかりませんでした。': 'No release asset was found.',
    '起動中の EXE を置き換えるため、アプリを一度終了してから更新します。設定とプレイリストは保持します。': 'The app will close once so the running EXE can be replaced. Settings and playlists will be preserved.',
}


def T(text: str) -> str:
    """Translate user-facing UI text. Japanese Windows keeps original Japanese."""
    if APP_UI_LANGUAGE == "ja":
        return text
    return _UI_TRANSLATIONS_EN.get(text, text)


class StartupSplash(QWidget):
    """Small startup window that shows visible boot progress until the main UI appears."""

    def __init__(self, app_version: str = ""):
        super().__init__(None, Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setFixedSize(520, 230)
        self.app_version = normalize_version_text(app_version) or APP_VERSION_FALLBACK

        outer = QFrame(self)
        outer.setObjectName("splashOuter")
        outer.setGeometry(0, 0, self.width(), self.height())
        outer.setStyleSheet("""
            QFrame#splashOuter {
                background: #101217;
                border: 1px solid #303644;
                border-radius: 18px;
            }
            QLabel#splashTitle {
                color: #ffffff;
                font-size: 24px;
                font-weight: 700;
            }
            QLabel#splashStatus {
                color: #c8d0dc;
                font-size: 13px;
            }
            QLabel#splashLog {
                color: #8f98a8;
                font-family: Consolas, 'Yu Gothic UI', monospace;
                font-size: 11px;
            }
            QProgressBar {
                border: 1px solid #343b4c;
                border-radius: 5px;
                background: #242833;
                height: 9px;
                text-align: center;
                color: transparent;
            }
            QProgressBar::chunk {
                background: #5d91f0;
                border-radius: 4px;
            }
        """)

        layout = QVBoxLayout(outer)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(10)

        self.title_label = QLabel(f"DropMp3 {format_version_label(self.app_version)}")
        self.title_label.setObjectName("splashTitle")
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.title_label)

        self.status_label = QLabel(T("起動準備中..."))
        self.status_label.setObjectName("splashStatus")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.status_label)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(3)
        layout.addWidget(self.progress)

        self.log_label = QLabel(f"DropMp3 {format_version_label(self.app_version)}")
        self.log_label.setObjectName("splashLog")
        self.log_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self.log_label.setWordWrap(True)
        layout.addWidget(self.log_label, 1)

        screen = QApplication.primaryScreen()
        if screen:
            geo = screen.availableGeometry()
            self.move(geo.center() - self.rect().center())

    def update_status(self, message: str, percent: int | None = None):
        if percent is not None:
            self.progress.setValue(max(0, min(100, int(percent))))
        translated = T(message)
        self.status_label.setText(translated)
        current = self.log_label.text().splitlines()[-5:]
        current.append(f"{datetime.now().strftime('%H:%M:%S')}  {translated}")
        self.log_label.setText("\n".join(current))
        app = QApplication.instance()
        if app:
            app.processEvents()


class LogBus(QObject):
    message = Signal(str)


LOG_BUS = LogBus()
LOG_HISTORY: list[str] = []


def make_log_line(message: str) -> str:
    now = datetime.now()
    elapsed = time.perf_counter() - APP_START_MONO
    ts = now.strftime("%Y-%m-%d %H:%M:%S")
    ms = int(now.microsecond / 1000)
    return f"{ts}.{ms:03d} | +{elapsed:8.3f}s | {message}"


def app_log(message: str):
    if message is None:
        return
    text = str(message).rstrip()
    if not text:
        return
    for line in text.splitlines():
        log_line = make_log_line(line)
        LOG_HISTORY.append(log_line)
        LOG_BUS.message.emit(log_line)


def qt_message_handler(mode, context, message):
    level = {
        QtMsgType.QtDebugMsg: "DEBUG",
        QtMsgType.QtInfoMsg: "INFO",
        QtMsgType.QtWarningMsg: "WARN",
        QtMsgType.QtCriticalMsg: "CRITICAL",
        QtMsgType.QtFatalMsg: "FATAL",
    }.get(mode, "LOG")
    app_log(f"[QT {level}] {message}")


class StreamBridge:
    def __init__(self, original, name: str):
        self.original = original
        self.name = name
        self.buffer = ""

    def write(self, text):
        try:
            if self.original:
                self.original.write(text)
                self.original.flush()
        except Exception:
            pass
        if not text:
            return
        self.buffer += text
        while "\n" in self.buffer:
            line, self.buffer = self.buffer.split("\n", 1)
            if line.strip():
                app_log(f"[{self.name}] {line.rstrip()}")

    def flush(self):
        try:
            if self.original:
                self.original.flush()
        except Exception:
            pass


def format_ms(ms: int) -> str:
    if ms is None or ms < 0:
        ms = 0
    total_sec = int(ms / 1000)
    h = total_sec // 3600
    m = (total_sec % 3600) // 60
    s = total_sec % 60
    if h > 0:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def bool_from_settings(value, default=False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).lower() in ("true", "1", "yes", "on")




class RemoteCommandBridge(QObject):
    """Run HTTP remote commands on the Qt/UI thread."""

    execute_requested = Signal(str, object, object)

    def __init__(self, owner):
        super().__init__(owner)
        self.owner = owner
        self.execute_requested.connect(self._execute)

    def invoke(self, command: str, params: dict, timeout_sec: float = 8.0) -> dict:
        done = threading.Event()
        box = {"result": None}
        self.execute_requested.emit(str(command or ""), dict(params or {}), (done, box))
        if not done.wait(timeout_sec):
            return {"ok": False, "error": "remote command timed out"}
        result = box.get("result")
        if isinstance(result, dict):
            return result
        return {"ok": False, "error": "remote command returned invalid result"}

    def _execute(self, command: str, params: object, token: object):
        done, box = token
        try:
            box["result"] = self.owner.remote_handle_command(str(command or ""), dict(params or {}))
        except Exception as exc:
            app_log(f"[REMOTE] command failed: {command}: {exc}")
            box["result"] = {"ok": False, "error": str(exc)}
        finally:
            done.set()


class _RemoteThreadingHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


class _RemoteRequestHandler(http.server.BaseHTTPRequestHandler):
    server_version = "DropMp3Remote/1.0"

    def log_message(self, fmt, *args):
        try:
            app_log("[REMOTE] " + (fmt % args))
        except Exception:
            pass

    def _send_bytes(self, data: bytes, content_type: str = "application/json; charset=utf-8", status: int = 200):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Remote-Token")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)

    def _send_json(self, payload: dict, status: int = 200):
        self._send_bytes(json.dumps(payload, ensure_ascii=False).encode("utf-8"), status=status)

    def _params_from_query(self, parsed):
        params = {}
        for key, values in urllib.parse.parse_qs(parsed.query, keep_blank_values=True).items():
            params[key] = values[-1] if values else ""
        return params

    def _read_body_params(self):
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        ctype = (self.headers.get("Content-Type") or "").lower()
        try:
            text = raw.decode("utf-8")
        except Exception:
            text = raw.decode("utf-8", errors="replace")
        if "application/json" in ctype:
            try:
                data = json.loads(text or "{}")
                return data if isinstance(data, dict) else {}
            except Exception:
                return {}
        params = {}
        for key, values in urllib.parse.parse_qs(text, keep_blank_values=True).items():
            params[key] = values[-1] if values else ""
        return params

    def _authorized(self, params: dict) -> bool:
        token = str(getattr(self.server, "remote_token", "") or "")
        if not token:
            return True
        request_token = str(params.get("token") or self.headers.get("X-Remote-Token") or "")
        return request_token == token

    def do_OPTIONS(self):
        self._send_bytes(b"", status=204)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        params = self._params_from_query(parsed)
        if not self._authorized(params):
            self._send_json({"ok": False, "error": "unauthorized"}, status=403)
            return
        if parsed.path in ("/", "/index.html"):
            html = remote_control_html(getattr(self.server, "remote_app_name", "DropMp3"))
            self._send_bytes(html.encode("utf-8"), "text/html; charset=utf-8")
            return
        if parsed.path == "/api/status":
            self._send_json(self.server.remote_bridge.invoke("status", params))
            return
        if parsed.path == "/api/playlist":
            self._send_json(self.server.remote_bridge.invoke("playlist", params))
            return
        self._send_json({"ok": False, "error": "not found"}, status=404)

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        params = self._params_from_query(parsed)
        params.update(self._read_body_params())
        if not self._authorized(params):
            self._send_json({"ok": False, "error": "unauthorized"}, status=403)
            return
        prefix = "/api/"
        if not parsed.path.startswith(prefix):
            self._send_json({"ok": False, "error": "not found"}, status=404)
            return
        command = parsed.path[len(prefix):].strip().lower()
        self._send_json(self.server.remote_bridge.invoke(command, params))


def remote_control_html(app_name: str) -> str:
    app_label = escape(str(app_name or "DropMp3"))
    return """<!doctype html>
<html lang=\"ja\">
<head>
<meta charset=\"utf-8\">
<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">
<title>__APP_NAME__ HTTPリモコン</title>
<style>
body{font-family:system-ui,-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#111;color:#eee;margin:0;padding:16px;}
h1{font-size:22px;margin:0 0 12px;} .panel{background:#1b1b1b;border:1px solid #333;border-radius:12px;padding:12px;margin:0 0 12px;}
button{font-size:16px;margin:4px;padding:8px 12px;border-radius:8px;border:1px solid #555;background:#2a2a2a;color:#eee;}
button:hover{background:#3a3a3a;} input[type=range]{width:min(420px,90vw);} .now{font-weight:700;color:#ffd27d;}
.item{display:flex;gap:8px;align-items:center;border-top:1px solid #333;padding:8px 0;} .item:first-child{border-top:0;} .idx{width:3em;color:#aaa;} .title{flex:1;overflow-wrap:anywhere;}
.small{color:#aaa;font-size:12px;overflow-wrap:anywhere;} .current{background:#222b37;border-radius:8px;padding-left:6px;}
</style>
</head>
<body>
<h1>__APP_NAME__ HTTPリモコン</h1>
<div class=\"panel\">
  <div id=\"status\">接続中...</div>
  <div style=\"margin-top:8px\">
    <button onclick=\"post('play')\">再生</button>
    <button onclick=\"post('pause')\">一時停止</button>
    <button onclick=\"post('toggle')\">再生/一時停止</button>
    <button onclick=\"post('stop')\">停止</button>
    <button onclick=\"post('prev')\">前へ</button>
    <button onclick=\"post('next')\">次へ</button>
  </div>
  <div style=\"margin-top:8px\">音量 <input id=\"vol\" type=\"range\" min=\"0\" max=\"100\" value=\"80\" oninput=\"setVolume(this.value)\"> <span id=\"volText\">80%</span></div>
  <div style=\"margin-top:8px\">位置 <input id=\"seek\" type=\"range\" min=\"0\" max=\"0\" value=\"0\" onchange=\"seekTo(this.value)\"> <span id=\"posText\">0:00 / 0:00</span></div>
</div>
<div class=\"panel\"><div class=\"small\">リスト項目の「再生」を押すと、リモート先PC上のPlayerで鳴ります。</div><div id=\"playlist\"></div></div>
<script>
const token = new URLSearchParams(location.search).get('token') || '';
let lastStatus = null;
function apiUrl(path, params={}){ const u = new URL(path, location.href); Object.entries(params).forEach(([k,v])=>u.searchParams.set(k,v)); if(token) u.searchParams.set('token', token); return u; }
async function get(path, params={}){ const r = await fetch(apiUrl(path, params)); return await r.json(); }
async function post(cmd, params={}){ const r = await fetch(apiUrl('/api/'+cmd, params), {method:'POST'}); const j = await r.json(); await refresh(); return j; }
function fmt(ms){ ms = Math.max(0, Number(ms||0)); const s = Math.floor(ms/1000); const h=Math.floor(s/3600), m=Math.floor((s%3600)/60), sec=s%60; return h>0 ? `${h}:${String(m).padStart(2,'0')}:${String(sec).padStart(2,'0')}` : `${m}:${String(sec).padStart(2,'0')}`; }
async function setVolume(v){ document.getElementById('volText').textContent = v+'%'; await post('volume', {value:v}); }
async function seekTo(v){ await post('seek', {ms:v}); }
async function playIndex(i){ await post('play', {index:i}); }
function renderStatus(s){ lastStatus=s; document.getElementById('status').innerHTML = `<div>状態: <span class=\"now\">${s.state_text||s.state}</span></div><div>現在: <span class=\"now\">${s.title||'(なし)'}</span></div><div class=\"small\">${s.path||''}</div>`; document.getElementById('vol').value=Math.round(Number(s.volume||0)*100); document.getElementById('volText').textContent=Math.round(Number(s.volume||0)*100)+'%'; const seek=document.getElementById('seek'); seek.max=Math.max(0, Number(s.duration_ms||0)); seek.value=Math.max(0, Number(s.position_ms||0)); document.getElementById('posText').textContent=fmt(s.position_ms)+' / '+fmt(s.duration_ms); }
function renderPlaylist(p){ const root=document.getElementById('playlist'); const items=p.items||[]; root.innerHTML = items.map(it => `<div class=\"item ${it.current?'current':''}\"><div class=\"idx\">#${it.index}</div><button onclick=\"playIndex(${it.index})\">再生</button><div class=\"title\">${escapeHtml(it.title||'')}<div class=\"small\">${escapeHtml(it.path||'')}</div></div></div>`).join('') || '<div class=\"small\">プレイリストは空です。</div>'; }
function escapeHtml(s){ return String(s).replace(/[&<>\"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;'}[c])); }
async function refresh(){ try{ const s=await get('/api/status'); if(s.ok) renderStatus(s); const p=await get('/api/playlist'); if(p.ok) renderPlaylist(p); }catch(e){ document.getElementById('status').textContent='接続できません: '+e; } }
refresh(); setInterval(refresh, 1500);
</script>
</body></html>""".replace("__APP_NAME__", app_label)


class RemoteControlServer:
    def __init__(self, owner, app_name: str, default_port: int):
        self.owner = owner
        self.app_name = app_name
        self.default_port = int(default_port)
        self.bridge = RemoteCommandBridge(owner)
        self.httpd = None
        self.thread = None
        self.url = ""
        self.lan_urls: list[str] = []

    def start(self):
        settings = getattr(self.owner, "settings", None)
        enabled = True
        host = "0.0.0.0"
        port = self.default_port
        token = ""
        try:
            if settings is not None:
                enabled = bool_from_settings(settings.value("remote/enabled", True), True)
                host = str(settings.value("remote/host", host) or host).strip() or host
                port = int(settings.value("remote/port", port) or port)
                token = str(settings.value("remote/token", "") or "")
        except Exception as exc:
            app_log(f"[REMOTE] settings read failed: {exc}")
        if not enabled:
            app_log("[REMOTE] HTTP remote control is disabled")
            return
        last_error = None
        for candidate in range(max(1, port), max(1, port) + 20):
            try:
                httpd = _RemoteThreadingHTTPServer((host, candidate), _RemoteRequestHandler)
                httpd.remote_bridge = self.bridge
                httpd.remote_token = token
                httpd.remote_app_name = self.app_name
                self.httpd = httpd
                display_host = "127.0.0.1" if host in ("", "0.0.0.0", "::") else host
                self.url = f"http://{display_host}:{candidate}/"
                self.lan_urls = self._collect_lan_urls(candidate) if host in ("0.0.0.0", "::", "") else []
                self.thread = threading.Thread(target=httpd.serve_forever, name=f"{self.app_name}RemoteHTTP", daemon=True)
                self.thread.start()
                app_log(f"[REMOTE] listening: {self.url}")
                for url in self.lan_urls:
                    app_log(f"[REMOTE] LAN URL: {url}")
                if token:
                    app_log("[REMOTE] token authentication is enabled")
                else:
                    app_log("[REMOTE] token authentication is disabled")
                return
            except OSError as exc:
                last_error = exc
                continue
        app_log(f"[REMOTE] failed to start HTTP remote control: {last_error}")

    def _collect_lan_urls(self, port: int) -> list[str]:
        urls = []
        seen = set()
        try:
            hostname = socket.gethostname()
            for info in socket.getaddrinfo(hostname, None, socket.AF_INET, socket.SOCK_STREAM):
                ip = info[4][0]
                if ip.startswith("127.") or ip in seen:
                    continue
                seen.add(ip)
                urls.append(f"http://{ip}:{port}/")
        except Exception:
            pass
        return urls

    def shutdown(self):
        httpd = self.httpd
        self.httpd = None
        if httpd is None:
            return
        try:
            app_log("[REMOTE] shutting down HTTP remote control")
            httpd.shutdown()
            httpd.server_close()
        except Exception as exc:
            app_log(f"[REMOTE] shutdown failed: {exc}")

def relative_or_absolute_path(media_path: Path, playlist_path: Path) -> str:
    try:
        return os.path.relpath(str(media_path), str(playlist_path.parent))
    except Exception:
        return str(media_path)



def read_text_auto(path: Path) -> str:
    last_error = None
    for enc in ("utf-8-sig", "utf-8", "cp932", "shift_jis"):
        try:
            return path.read_text(encoding=enc, errors="strict")
        except Exception as e:
            last_error = e
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        if last_error:
            raise last_error
        raise


def resolve_playlist_entry(base: Path, entry: str) -> Path | None:
    entry = (entry or "").strip().strip('"')
    if not entry:
        return None
    if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", entry):
        return None
    candidate = Path(entry)
    if not candidate.is_absolute():
        candidate = base.parent / candidate
    try:
        return candidate.expanduser().resolve()
    except Exception:
        return candidate


def is_comment_line_for_plain_list(line: str) -> bool:
    stripped = (line or "").strip()
    return not stripped or stripped.startswith("#") or stripped.startswith(";")


def add_audio_entry_from_text(result: list[Path], base: Path | None, value: str):
    value = (value or "").strip().strip('"').strip("'")
    if not value or value.startswith("#") or value.startswith(";"):
        return
    if value.lower().startswith("file://"):
        try:
            local = QUrl(value).toLocalFile()
            if local:
                value = local
        except Exception:
            pass
    resolved = resolve_playlist_entry(base or Path.cwd(), value)
    if resolved and resolved.exists() and resolved.suffix.lower() in AUDIO_EXTS:
        result.append(resolved)


def dedupe_paths(paths: list[Path]) -> list[Path]:
    deduped: list[Path] = []
    seen: set[str] = set()
    for item in paths:
        key = str(item).lower()
        if key not in seen:
            deduped.append(item)
            seen.add(key)
    return deduped


def parse_plain_path_list_text(text: str, base: Path | None = None) -> list[Path]:
    result: list[Path] = []
    for line in (text or "").splitlines():
        line = line.strip().lstrip("\ufeff")
        if is_comment_line_for_plain_list(line):
            continue
        add_audio_entry_from_text(result, base, line)
    deduped = dedupe_paths(result)
    app_log(f"Plain text path list parsed -> {len(deduped)} audio file(s)")
    return deduped


def parse_playlist_file(path: Path) -> list[Path]:
    ext = path.suffix.lower()
    result: list[Path] = []
    try:
        text = read_text_auto(path)
    except Exception as e:
        app_log(f"[PLAYLIST READ ERROR] {path}: {e}")
        return result

    def add_entry(value: str):
        add_audio_entry_from_text(result, path, value)

    if ext in TEXT_PLAYLIST_EXTS:
        return parse_plain_path_list_text(text, path)
    if ext in (".m3u", ".m3u8"):
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            add_entry(line)
    elif ext == ".pls":
        for line in text.splitlines():
            m = re.match(r"\s*File\d+\s*=\s*(.+)\s*$", line, re.IGNORECASE)
            if m:
                add_entry(m.group(1))
    elif ext == ".wpl":
        try:
            root = ET.fromstring(text)
            for elem in root.iter():
                src = elem.attrib.get("src")
                if src:
                    add_entry(src)
        except Exception:
            for m in re.finditer(r'<\s*media\b[^>]*\bsrc\s*=\s*["\']([^"\']+)["\']', text, re.IGNORECASE):
                add_entry(m.group(1))

    deduped = dedupe_paths(result)
    app_log(f"Playlist parsed: {path} -> {len(deduped)} audio file(s)")
    return deduped

def srt_time_to_ms(text: str) -> int:
    m = re.match(r"(\d{1,2}):(\d{2}):(\d{2})[,.](\d{1,3})", text.strip())
    if not m:
        return 0
    h, mi, s, ms = m.groups()
    ms = (ms + "000")[:3]
    return (int(h) * 3600 + int(mi) * 60 + int(s)) * 1000 + int(ms)


def parse_srt(path: Path) -> list[tuple[int, int, str]]:
    """SRTを読み込む。UTF-8 / UTF-8 BOM / Shift_JIS(CP932)を自動判定寄りで読む。"""
    raw = ""
    last_error = None
    for enc in ("utf-8-sig", "utf-8", "cp932", "shift_jis"):
        try:
            raw = path.read_text(encoding=enc, errors="strict")
            app_log(f"SRT loaded: {path} encoding={enc}")
            break
        except Exception as e:
            last_error = e
    else:
        try:
            raw = path.read_text(encoding="utf-8", errors="replace")
            app_log(f"SRT loaded with replacement fallback: {path}; last_error={last_error}")
        except Exception as e:
            app_log(f"SRT read failed: {path} / {e}")
            return []

    blocks = re.split(r"\n\s*\n", raw.replace("\r\n", "\n").replace("\r", "\n"))
    cues: list[tuple[int, int, str]] = []
    for block in blocks:
        lines = [ln.strip() for ln in block.split("\n") if ln.strip()]
        if not lines:
            continue
        time_line_index = -1
        for idx, line in enumerate(lines):
            if "-->" in line:
                time_line_index = idx
                break
        if time_line_index < 0:
            continue
        parts = lines[time_line_index].split("-->")
        if len(parts) < 2:
            continue
        start = srt_time_to_ms(parts[0])
        end = srt_time_to_ms(parts[1].split()[0])
        text = " ".join(lines[time_line_index + 1:]).strip()
        if start is not None and end is not None and text:
            cues.append((start, end, text))
    return cues


class ScrollingLabel(QLabel):
    fontWheelChanged = Signal(int, object)

    def __init__(self, text="", parent=None):
        super().__init__(parent)
        self.full_text = text
        self.offset = 0
        self.wait_count = 0
        self.text_color = QColor("#ffffff")
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(120)
        self.setMinimumHeight(24)
        self.setAlignment(Qt.AlignCenter)
        self.setStyleSheet("color: white; font-size: 14px;")

    def setText(self, text):
        self.full_text = text or ""
        self.offset = 0
        self.wait_count = 0
        self.update()

    def text(self):
        return self.full_text

    def setTextColor(self, color):
        try:
            self.text_color = QColor(color)
        except Exception:
            self.text_color = QColor("#ffffff")
        self.update()

    def tick(self):
        metrics = QFontMetrics(self.font())
        text_width = metrics.horizontalAdvance(self.full_text)
        if text_width <= self.width() - 16:
            return
        if self.wait_count < 10:
            self.wait_count += 1
            return
        self.offset += 2
        if self.offset > text_width + 40:
            self.offset = 0
            self.wait_count = 0
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setPen(self.text_color)
        painter.setFont(self.font())
        metrics = QFontMetrics(self.font())
        text_width = metrics.horizontalAdvance(self.full_text)
        y = int((self.height() + metrics.ascent() - metrics.descent()) / 2)
        if text_width <= self.width() - 16:
            x = int((self.width() - text_width) / 2)
            painter.drawText(x, y, self.full_text)
        else:
            x = 8 - self.offset
            painter.drawText(x, y, self.full_text)
            painter.drawText(x + text_width + 40, y, self.full_text)

    def wheelEvent(self, event):
        delta = event.angleDelta().y()
        if delta != 0 and event.modifiers() & Qt.ControlModifier:
            self.fontWheelChanged.emit(delta, event)
            event.accept()
            return
        super().wheelEvent(event)


class ArtLabel(QLabel):
    doubleClicked = Signal()
    clicked = Signal()
    wheelChanged = Signal(int, object)
    leftPressed = Signal(object)
    leftMoved = Signal(object)
    leftReleased = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._press_pos = None
        self._moved = False
        # ダブルクリック時に、2回目の release が single click として拾われるのを防ぐ。
        self._suppress_release_click_once = False
        self._click_timer = QTimer(self)
        self._click_timer.setSingleShot(True)
        self._click_timer.timeout.connect(self.clicked.emit)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:
            if self._click_timer.isActive():
                self._click_timer.stop()
            self._suppress_release_click_once = True
            self.doubleClicked.emit()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._press_pos = event.position().toPoint()
            self._moved = False
            self.leftPressed.emit(event)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.LeftButton:
            if self._press_pos is not None:
                delta = event.position().toPoint() - self._press_pos
                if abs(delta.x()) + abs(delta.y()) >= 6:
                    self._moved = True
            self.leftMoved.emit(event)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.leftReleased.emit(event)
            if self._suppress_release_click_once:
                # ダブルクリックでミニ/ワンショット表示から戻る直後に
                # single click の再生/停止が走って曲が止まるのを防止。
                self._suppress_release_click_once = False
                if self._click_timer.isActive():
                    self._click_timer.stop()
            elif not self._moved:
                self._click_timer.start(220)
            self._press_pos = None
            self._moved = False
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def wheelEvent(self, event):
        delta = event.angleDelta().y()
        if delta != 0:
            self.wheelChanged.emit(delta, event)
            event.accept()
            return
        super().wheelEvent(event)


class VolumeLabel(QLabel):
    wheelChanged = Signal(int, object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAlignment(Qt.AlignCenter)
        self.setMinimumWidth(76)
        self._display_font_size = 12
        self.setToolTip(T("マウスを載せてホイールで音量調節") + "\nCtrl+ホイール: 文字サイズ変更")
        self.apply_display_style()

    def set_display_font_size(self, size: int):
        self._display_font_size = max(8, min(28, int(size)))
        self.apply_display_style()

    def apply_display_style(self):
        self.setStyleSheet(f"""
            QLabel {{
                color:#d8d8d8;
                background:#222;
                border:1px solid #444;
                border-radius:12px;
                padding:4px 8px;
                font-size:{self._display_font_size}px;
            }}
            QLabel:hover {{
                color:#ffb36a;
                border-color:#ff9b45;
                background:#2a241f;
            }}
        """)

    def wheelEvent(self, event):
        delta = event.angleDelta().y()
        if delta != 0:
            self.wheelChanged.emit(delta, event)
            event.accept()
            return
        super().wheelEvent(event)

    def enterEvent(self, event):
        QToolTip.showText(
            self.mapToGlobal(QPoint(self.width() + 8, int(self.height() / 2))),
            T("マウスホイールで音量調節") + "\nCtrl+ホイール: 文字サイズ変更",
            self,
        )
        super().enterEvent(event)



class TimeDisplayLabel(QLabel):
    wheelChanged = Signal(int, object)

    def __init__(self, text="", parent=None):
        super().__init__(text, parent)
        self._display_font_size = 12
        self.setToolTip(T("Ctrl+ホイール: 時間表示文字サイズ変更"))
        self.apply_display_style()

    def set_display_font_size(self, size: int):
        self._display_font_size = max(8, min(28, int(size)))
        self.apply_display_style()

    def apply_display_style(self):
        font = QFont(self.font())
        font.setPixelSize(self._display_font_size)
        self.setFont(font)
        metrics = QFontMetrics(font)
        self.setMinimumWidth(max(48, metrics.horizontalAdvance("00:00:00") + 8))
        self.setStyleSheet("""
            QLabel {
                color:#d0d0d0;
                background:transparent;
            }
            QLabel:hover {
                color:#ffb36a;
            }
        """)

    def wheelEvent(self, event):
        delta = event.angleDelta().y()
        if delta != 0 and event.modifiers() & Qt.ControlModifier:
            self.wheelChanged.emit(delta, event)
            event.accept()
            return
        super().wheelEvent(event)


class SubtitleFontDialog(QDialog):
    T("""字幕フォント・サイズ・色をライブプレビューしながら変更するダイアログ。""")

    preview_changed = Signal(QFont, QColor)

    def __init__(self, parent=None, current_font: QFont | None = None, current_color: QColor | None = None):
        super().__init__(parent)
        self.setWindowTitle(T("字幕フォント設定"))
        self.setModal(False)
        self.resize(560, 300)

        self._initial_font = QFont(current_font) if current_font is not None else QFont("Yu Gothic UI", 20)
        self._initial_color = QColor(current_color) if current_color is not None else QColor("#66ff88")
        self._color = QColor(self._initial_color)

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(10)

        form = QGridLayout()
        form.setHorizontalSpacing(10)
        form.setVerticalSpacing(8)
        root.addLayout(form)

        form.addWidget(QLabel(T("フォント")), 0, 0)
        self.font_combo = QFontComboBox(self)
        self.font_combo.setCurrentFont(self._initial_font)
        form.addWidget(self.font_combo, 0, 1, 1, 2)

        form.addWidget(QLabel(T("サイズ")), 1, 0)
        self.size_spin = QSpinBox(self)
        self.size_spin.setRange(8, 72)
        self.size_spin.setSingleStep(1)
        self.size_spin.setValue(max(8, self._initial_font.pointSize() if self._initial_font.pointSize() > 0 else 24))
        form.addWidget(self.size_spin, 1, 1)

        self.color_button = QPushButton(T("色を選択"), self)
        self.color_button.setCursor(Qt.CursorShape.PointingHandCursor)
        form.addWidget(self.color_button, 1, 2)

        self.preview = QLabel(T("字幕プレビュー / Subtitle Preview\nBroken glass mirrors, where two shadows meet"), self)
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setWordWrap(True)
        self.preview.setMinimumHeight(110)
        self.preview.setStyleSheet("background: rgba(0,0,0,190); border-radius: 12px; padding: 12px;")
        root.addWidget(self.preview)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, self)
        root.addWidget(buttons)

        self.font_combo.currentFontChanged.connect(self._emit_preview)
        self.size_spin.valueChanged.connect(self._emit_preview)
        self.color_button.clicked.connect(self._choose_color)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        self._emit_preview()

    def selected_font(self) -> QFont:
        f = QFont(self.font_combo.currentFont())
        f.setPointSize(self.size_spin.value())
        f.setBold(True)
        return f

    def selected_color(self) -> QColor:
        return QColor(self._color)

    def initial_font(self) -> QFont:
        return QFont(self._initial_font)

    def initial_color(self) -> QColor:
        return QColor(self._initial_color)

    def _choose_color(self) -> None:
        color = QColorDialog.getColor(self._color, self, T("字幕色を選択"))
        if color.isValid():
            self._color = color
            self._emit_preview()

    def _emit_preview(self) -> None:
        font = self.selected_font()
        color = self.selected_color()
        self.preview.setFont(font)
        self.preview.setStyleSheet(
            "background: rgba(0,0,0,190); border-radius: 12px; padding: 12px; "
            f"color: {color.name()};"
        )
        self.color_button.setStyleSheet(
            f"background: {color.name()}; color: {'#000000' if color.lightness() > 140 else '#ffffff'};"
        )
        self.preview_changed.emit(font, color)

class SubtitleOverlay(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.cues: list[tuple[int, int, str]] = []
        self.current_index = -1
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.subtitle_font = QFont(self.font())
        self.subtitle_color = QColor(120, 255, 145, 235)
        self.setVisible(False)

    def set_subtitle_style(self, font=None, color=None):
        if font is not None:
            self.subtitle_font = QFont(font)
        if color is not None:
            self.subtitle_color = QColor(color)
        self.update()

    def set_cues(self, cues: list[tuple[int, int, str]]):
        self.cues = cues or []
        self.current_index = -1
        self.setVisible(bool(self.cues))
        self.update()

    def update_position(self, position_ms: int):
        if not self.cues:
            if self.isVisible():
                self.setVisible(False)
            return
        idx = -1
        for i, (start, end, _txt) in enumerate(self.cues):
            if start <= position_ms <= end:
                idx = i
                break
            if position_ms < start:
                break
        if idx != self.current_index:
            self.current_index = idx
            self.update()

    def wrapped_lines(self, painter: QPainter, text: str, max_width: int, max_lines: int = 2) -> list[str]:
        metrics = QFontMetrics(painter.font())
        if metrics.horizontalAdvance(text) <= max_width:
            return [text]

        lines = []
        current = ""
        # 日本語・英語混在用。空白がある場合は単語、無い場合は文字単位寄り。
        units = re.findall(r"\S+\s*", text) if " " in text else list(text)
        for unit in units:
            candidate = current + unit
            if metrics.horizontalAdvance(candidate) <= max_width or not current:
                current = candidate
            else:
                lines.append(current.strip())
                current = unit.strip()
                if len(lines) >= max_lines:
                    break
        if len(lines) < max_lines and current:
            lines.append(current.strip())
        if len(lines) > max_lines:
            lines = lines[:max_lines]
        return lines

    def paintEvent(self, event):
        if not self.cues or self.current_index < 0:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        font = QFont(getattr(self, "subtitle_font", self.font()))
        painter.setFont(font)

        indices = [i for i in (self.current_index - 1, self.current_index, self.current_index + 1) if 0 <= i < len(self.cues)]
        rows: list[tuple[bool, str]] = []
        max_width = max(80, self.width() - 28)
        for idx in indices:
            is_current = idx == self.current_index
            for line in self.wrapped_lines(painter, self.cues[idx][2], max_width, 2):
                rows.append((is_current, line))

        # 最大5行。現在字幕が2行化しても見やすいようにする。
        rows = rows[:5]
        if not rows:
            return

        metrics = QFontMetrics(font)
        line_h = metrics.height() + 5
        box_h = line_h * len(rows) + 12
        box_w = self.width() - 18
        x = 9
        y = max(10, self.height() - box_h - 12)

        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(0, 0, 0, 118))
        painter.drawRoundedRect(QRect(x, y, box_w, box_h), 8, 8)

        text_y = y + 8
        text_rect_x = x + 12
        text_rect_w = max(10, box_w - 24)
        for is_current, line in rows:
            line_rect = QRect(text_rect_x, text_y, text_rect_w, line_h)
            # 影も中央寄せ
            painter.setPen(QColor(0, 0, 0, 210))
            painter.drawText(line_rect.adjusted(1, 1, 1, 1), Qt.AlignCenter, line)
            # 現在字幕は設定色、それ以外は白。全行中央寄せ。
            current_color = QColor(getattr(self, "subtitle_color", QColor(120, 255, 145, 235)))
            if current_color.alpha() <= 0:
                current_color.setAlpha(235)
            painter.setPen(current_color if is_current else QColor(255, 255, 255, 225))
            painter.drawText(line_rect, Qt.AlignCenter, line)
            text_y += line_h


class LogWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("DropMp3 Log")
        self.resize(860, 420)
        self.text = QTextEdit()
        self.text.setReadOnly(True)
        self.text.setStyleSheet("""
            QTextEdit {
                background-color: #101010;
                color: #d8d8d8;
                font-family: Consolas, Meiryo, monospace;
                font-size: 12px;
            }
        """)
        layout = QVBoxLayout()
        layout.setContentsMargins(6, 6, 6, 6)
        layout.addWidget(self.text)
        self.setLayout(layout)
        self.loaded_history = False

    def load_history_once(self):
        if self.loaded_history:
            return
        self.text.clear()
        for line in LOG_HISTORY:
            self.text.append(line)
        self.loaded_history = True
        self.scroll_to_bottom()

    def append(self, line: str):
        if not self.loaded_history:
            return
        self.text.append(line)
        self.scroll_to_bottom()

    def showEvent(self, event):
        self.load_history_once()
        self.scroll_to_bottom()
        super().showEvent(event)

    def scroll_to_bottom(self):
        bar = self.text.verticalScrollBar()
        bar.setValue(bar.maximum())


class PlaylistMenuList(QListWidget):
    itemActivatedByIndex = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setSelectionMode(QListWidget.SingleSelection)
        self.setStyleSheet("""
            QListWidget {
                background-color: #141414;
                border: 1px solid #333;
                outline: none;
                font-size: 13px;
            }
            QListWidget::item { padding: 5px 8px; border-bottom: 1px solid #242424; }
            QListWidget::item:selected { background-color: #3a3a3a; color: #ffb36a; }
            QListWidget::item:hover { background-color: #2c2c2c; }
        """)

    def mouseDoubleClickEvent(self, event):
        item = self.itemAt(event.position().toPoint())
        if item:
            self.itemActivatedByIndex.emit(int(item.data(Qt.UserRole)))
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def mousePressEvent(self, event):
        item = self.itemAt(event.position().toPoint())
        if item:
            self.setCurrentItem(item)
        super().mousePressEvent(event)


class EditablePlaylistWidget(QListWidget):
    deletePressed = Signal()
    orderChanged = Signal()
    activatedIndex = Signal(int)
    filesDroppedAt = Signal(int, list)
    itemContextRequested = Signal(int, QPoint)
    fontWheelChanged = Signal(int, object)

    def __init__(self, parent=None):
        super().__init__(parent)
        # Ctrl/Shift による複数選択を有効化。
        # 選択した複数曲は、そのまま内部移動や外部Drag&Dropに使えます。
        self.setSelectionMode(QListWidget.ExtendedSelection)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDragDropMode(QAbstractItemView.DragDrop)
        self.setDefaultDropAction(Qt.MoveAction)
        self.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.itemDoubleClicked.connect(self._on_double_clicked)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._on_context_menu_requested)

    def _on_double_clicked(self, item):
        idx = item.data(Qt.UserRole)
        if idx is not None:
            self.activatedIndex.emit(int(idx))

    def _on_context_menu_requested(self, pos):
        item = self.itemAt(pos)
        if not item:
            return
        idx = item.data(Qt.UserRole)
        if idx is None:
            return
        # 複数選択済みの曲を右クリックした場合は、選択状態を壊さない。
        # 未選択の曲を右クリックした場合だけ、その曲を現在項目にする。
        if not item.isSelected():
            self.clearSelection()
            item.setSelected(True)
        self.setCurrentItem(item)
        self.itemContextRequested.emit(int(idx), self.viewport().mapToGlobal(pos))

    def mimeData(self, items):
        mime = super().mimeData(items)
        urls = []
        paths = []
        for item in items:
            path = item.data(Qt.UserRole + 1)
            if path:
                p = Path(str(path))
                urls.append(QUrl.fromLocalFile(str(p)))
                paths.append(str(p))
        if urls:
            mime.setUrls(urls)
            mime.setText("\n".join(paths))
        return mime

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Delete:
            self.deletePressed.emit()
            event.accept()
            return
        super().keyPressEvent(event)

    def wheelEvent(self, event):
        delta = event.angleDelta().y()
        if delta != 0 and event.modifiers() & Qt.ControlModifier:
            self.fontWheelChanged.emit(delta, event)
            event.accept()
            return
        super().wheelEvent(event)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls() or event.mimeData().hasText():
            event.acceptProposedAction()
            return
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls() or event.mimeData().hasText():
            event.acceptProposedAction()
            return
        super().dragMoveEvent(event)

    def dropEvent(self, event):
        if event.source() is self:
            super().dropEvent(event)
            self.orderChanged.emit()
            return
        if event.mimeData().hasUrls():
            row = self.indexAt(event.position().toPoint()).row()
            if row < 0:
                row = self.count()
            if self.dropIndicatorPosition() == QAbstractItemView.DropIndicatorPosition.BelowItem:
                row += 1
            files = []
            for url in event.mimeData().urls():
                local = url.toLocalFile()
                if local:
                    files.append(Path(local))
            self.filesDroppedAt.emit(row, files)
            event.acceptProposedAction()
            return
        if event.mimeData().hasText():
            row = self.indexAt(event.position().toPoint()).row()
            if row < 0:
                row = self.count()
            if self.dropIndicatorPosition() == QAbstractItemView.DropIndicatorPosition.BelowItem:
                row += 1
            files = parse_plain_path_list_text(event.mimeData().text())
            if files:
                self.filesDroppedAt.emit(row, files)
                event.acceptProposedAction()
                return
        super().dropEvent(event)
        self.orderChanged.emit()


class DropOneShotButton(QPushButton):
    filesDropped = Signal(list)

    def __init__(self, text: str = "🎯", parent=None):
        super().__init__(text, parent)
        self.setAcceptDrops(True)
        self.setCursor(Qt.PointingHandCursor)
        self._normal_text = text
        self._expanded_text = "DROP\n🎯"
        self._normal_size = QSize(42, 42)
        self._expanded_size = QSize(92, 58)
        self._drop_hot = False
        self.setFixedSize(self._normal_size)

    def configure_drop_expand(self, normal_size: QSize, expanded_size: QSize, normal_text: str | None = None, expanded_text: str | None = None):
        self._normal_size = normal_size
        self._expanded_size = expanded_size
        if normal_text is not None:
            self._normal_text = normal_text
        if expanded_text is not None:
            self._expanded_text = expanded_text
        self.setText(self._normal_text)
        self.setFixedSize(self._normal_size)

    def _set_drop_hot(self, hot: bool):
        if self._drop_hot == hot:
            return
        self._drop_hot = hot
        self.setProperty("dropHot", bool(hot))
        self.setText(self._expanded_text if hot else self._normal_text)
        self.setFixedSize(self._expanded_size if hot else self._normal_size)
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()
        if hot:
            self.raise_()

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls() or event.mimeData().hasText():
            self._set_drop_hot(True)
            event.acceptProposedAction()
            return
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls() or event.mimeData().hasText():
            self._set_drop_hot(True)
            event.acceptProposedAction()
            return
        super().dragMoveEvent(event)

    def dragLeaveEvent(self, event):
        self._set_drop_hot(False)
        super().dragLeaveEvent(event)

    def dropEvent(self, event):
        self._set_drop_hot(False)
        if event.mimeData().hasUrls():
            dropped = []
            for url in event.mimeData().urls():
                local = url.toLocalFile()
                if local:
                    dropped.append(Path(local))
            self.filesDropped.emit(dropped)
            event.acceptProposedAction()
            return
        if event.mimeData().hasText():
            files = parse_plain_path_list_text(event.mimeData().text())
            if files:
                self.filesDropped.emit(files)
                event.acceptProposedAction()
                return
        super().dropEvent(event)


class SeekStepButton(QPushButton):
    def __init__(self, direction: int, seconds: int, parent=None):
        super().__init__(parent)
        self.direction = -1 if direction < 0 else 1
        self.seconds = max(1, int(seconds))
        self.base_size = 63
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.NoFocus)
        self.setFixedSize(self.base_size, self.base_size)
        self.setStyleSheet("background:transparent;border:0;")

    def paintEvent(self, event):
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)

        if not self.isEnabled():
            fill = QColor("#222222")
            border = QColor("#4a4a4a")
            accent = QColor("#9a9a9a")
        elif self.isDown():
            fill = QColor("#353535")
            border = QColor("#ffb36a")
            accent = QColor("#ffd2a1")
        elif self.underMouse():
            fill = QColor("#313131")
            border = QColor("#ff9b45")
            accent = QColor("#ffc283")
        else:
            fill = QColor("#2b2b2b")
            border = QColor("#555555")
            accent = QColor("#ffb36a")

        outer = self.rect().adjusted(1, 1, -1, -1)
        painter.setPen(QPen(border, 1.2))
        painter.setBrush(fill)
        painter.drawEllipse(outer)

        scale = min(self.width(), self.height()) / float(self.base_size or 63)
        pad = max(6, int(round(9 * scale)))
        arc_rect = outer.adjusted(pad, pad, -pad, -pad)
        pen = QPen(accent, max(2.0, 3.0 * scale), Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
        painter.setPen(pen)
        if self.direction < 0:
            start_angle = 36
            span_angle = 285
        else:
            start_angle = 144
            span_angle = -285
        painter.drawArc(arc_rect, start_angle * 16, span_angle * 16)

        end_angle = start_angle + span_angle
        center = arc_rect.center()
        radius = arc_rect.width() / 2.0
        end_rad = math.radians(-end_angle)
        tip = QPointF(
            center.x() + radius * math.cos(end_rad),
            center.y() + radius * math.sin(end_rad),
        )
        tangent_rad = end_rad + (math.pi / 2.0 if span_angle > 0 else -math.pi / 2.0)
        wing = max(5.0, 7.0 * scale)
        arrow_a = QPointF(
            tip.x() - wing * math.cos(tangent_rad - 0.55),
            tip.y() - wing * math.sin(tangent_rad - 0.55),
        )
        arrow_b = QPointF(
            tip.x() - wing * math.cos(tangent_rad + 0.55),
            tip.y() - wing * math.sin(tangent_rad + 0.55),
        )
        painter.drawLine(tip, arrow_a)
        painter.drawLine(tip, arrow_b)

        text_font = QFont(self.font())
        text_font.setBold(True)
        text_font.setPointSize(max(10, int(round(15 * scale))))
        painter.setFont(text_font)
        painter.setPen(accent)
        text_top = int(round(6 * scale))
        text_bottom = int(round(2 * scale))
        painter.drawText(self.rect().adjusted(0, text_top, 0, text_bottom), Qt.AlignCenter, str(self.seconds))


class MiniDropPlayer(QWidget):
    WIDE_PLAYLIST_THRESHOLD = 860
    SEEK_STEP_MS = 10000

    def __init__(self, splash: StartupSplash | None = None):
        super().__init__()
        self.startup_splash = splash
        app_log("MiniDropPlayer init start")
        self.conf_dir = self.app_base_dir() / "_conf"
        self.conf_html_dir = self.conf_dir / "html"
        self.conf_playlist_dir = self.conf_dir / "lst"
        try:
            self.conf_dir.mkdir(parents=True, exist_ok=True)
            self.conf_html_dir.mkdir(parents=True, exist_ok=True)
            self.conf_playlist_dir.mkdir(parents=True, exist_ok=True)
        except Exception as exc:
            app_log(f"[SETTINGS] _conf create failed: {exc}")
        self.help_files = {
            "about": {
                "ja": self.conf_html_dir / "DropMp3_About_ja.html",
                "en": self.conf_html_dir / "DropMp3_About_en.html",
            },
            "operation": {
                "ja": self.conf_html_dir / "DropMp3_Operation_ja.html",
                "en": self.conf_html_dir / "DropMp3_Operation_en.html",
            },
            "install": {
                "ja": self.conf_html_dir / "DropMp3_Install_Help_ja.html",
                "en": self.conf_html_dir / "DropMp3_Install_Help_en.html",
            },
        }
        self.settings = QSettings(str(self.conf_dir / "DropMp3.ini"), QSettings.Format.IniFormat)
        self.current_app_version = read_app_version(self.app_base_dir())
        self.update_bridge = UpdateWorkerBridge(self)
        self.update_bridge.checkFinished.connect(self.on_update_check_finished)
        self.update_bridge.progressChanged.connect(self.on_update_download_progress)
        self.update_bridge.downloadFinished.connect(self.on_update_download_finished)
        self.update_bridge.updateError.connect(self.on_update_error)
        self.update_progress_dialog = None
        self.update_download_context = None
        self.update_check_in_progress = False
        self.update_download_in_progress = False
        self.update_startup_splash("起動準備中...", 8)

        self.setWindowTitle(f"DropMp3 {format_version_label(self.current_app_version)}")
        self.update_startup_splash("アイコンを読み込み中...", 12)
        self.apply_app_icon()
        self.setAcceptDrops(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.resize(720, 520)
        self.setMinimumSize(280, 260)

        self.playlist: list[Path] = []
        self.current_index = -1
        self.user_is_seeking = False
        self.pending_restore_position = 0
        self.restored_once = False
        self.art_source_pixmap = QPixmap()
        self.is_art_only_mode = False
        self.is_one_shot_panel_mode = False
        self.normal_geometry_before_small_mode = None
        self.dragging_small_window = False
        self.drag_start_global = QPoint()
        self.drag_start_window_pos = QPoint()
        self.one_shot_mode = False
        self.one_shot_path: Path | None = None
        self.last_list_index_before_one_shot = -1
        self.one_shot_return_path: Path | None = None
        self.one_shot_return_index = -1
        self.one_shot_return_position = 0
        self.one_shot_return_was_playing = False
        self.repeat_mode = "off"  # off / one / all
        self.repeat_current = False  # 旧設定互換用
        self.random_art_mode = False
        self.random_art_enabled = True
        self.original_art_pixmap = QPixmap()
        self.random_art_paths: list[Path] = []
        self.random_art_timer = QTimer(self)
        self.random_art_delay_timer = QTimer(self)
        self.random_art_delay_timer.setSingleShot(True)
        self.random_art_delay_paused = False
        self.random_art_timer_paused = False
        self.subtitle_cues: list[tuple[int, int, str]] = []
        self.subtitle_primary_cues: list[tuple[int, int, str]] = []
        self.subtitle_secondary_cues: list[tuple[int, int, str]] = []
        self.subtitle_display_mode = 0
        self.subtitles_manually_hidden = False
        self.subtitle_auto_show_enabled = True
        self.left_playlist_visible = False
        self.drawer_open = False
        self.playlist_font_size = 12
        self.volume_font_size = 12
        self.time_font_size = 12
        self.title_font_size = 28
        self.control_icon_scale = 1.0
        self.playlist_order_mode = ""
        self.playlist_search_text = ""
        self.current_playlist_name = self.generate_new_playlist_name()
        self.property_dialogs = []
        self.whisper_dialogs = []
        self.help_dialogs = []

        # Header title style: strong Latin font + Japanese-capable fallbacks.
        # Impact is used for English glyphs; Japanese falls back to Yu Gothic UI / Meiryo.
        self.title_font_families = '"Impact", "Yu Gothic UI Semibold", "Yu Gothic UI", "Meiryo", sans-serif'
        self.title_color_palette = [
            "#ffd1dc",  # pastel pink
            "#bde0fe",  # pastel blue
            "#caffbf",  # pastel green
            "#fff3b0",  # pastel yellow
            "#ffc6ff",  # pastel violet
            "#a0f0ed",  # pastel cyan
            "#ffd6a5",  # pastel orange
            "#d0bfff",  # pastel lavender
        ]
        self.current_title_style_key = ""
        self.current_title_color = "#ffffff"

        self.update_startup_splash("メインウィンドウを準備中...", 22)
        self.player = QMediaPlayer(self)
        self.audio = QAudioOutput(self)
        self.media_devices = QMediaDevices(self)
        self.player.setAudioOutput(self.audio)
        self.audio.setVolume(0.8)
        self.last_known_default_audio_device_id = self.audio_device_id(QMediaDevices.defaultAudioOutput())
        self.subtitle_source_language = str(self.settings.value("subtitle/source_language", "auto") or "auto")
        self.subtitle_target_language = str(self.settings.value("subtitle/target_language", "ja") or "ja")
        self.ollama_model = str(self.settings.value("subtitle/ollama_model", "llama3.1") or "llama3.1")

        self.log_window = LogWindow()
        LOG_BUS.message.connect(self.log_window.append)

        self.tray_icon = None
        self.tray_menu = None
        self.remote_server = None
        self.playlist_window = None
        self.playlist_window_list = None
        self.exit_requested = False

        self.update_startup_splash("UIを構築中...", 38)
        self.build_ui()
        self.update_startup_splash("操作を接続中...", 58)
        self.connect_signals()
        self.setup_media_shortcuts()
        self.update_startup_splash("タスクトレイを準備中...", 66)
        self.setup_tray_icon()
        self.update_startup_splash("設定とプレイリストを復元中...", 72)
        self.load_settings()
        self.setup_remote_control()
        QTimer.singleShot(1800, self.schedule_startup_update_check)

        self.autosave_timer = QTimer(self)
        self.autosave_timer.timeout.connect(self.save_settings)
        self.autosave_timer.start(5000)
        self.update_startup_splash("起動完了", 96)
        app_log("MiniDropPlayer init complete")

    def update_startup_splash(self, message: str, percent: int | None = None):
        splash = getattr(self, "startup_splash", None)
        if splash is not None:
            try:
                splash.update_status(message, percent)
            except Exception as exc:
                app_log(f"[SPLASH] update failed: {exc}")

    def icon_search_dirs(self) -> list[Path]:
        """PyInstaller onefile / onedir / script実行のどれでもアイコンを探す。"""
        dirs: list[Path] = []
        try:
            dirs.append(Path(__file__).resolve().parent)
        except Exception:
            pass
        try:
            if hasattr(sys, "_MEIPASS"):
                dirs.append(Path(sys._MEIPASS))
        except Exception:
            pass
        try:
            dirs.append(Path(sys.executable).resolve().parent)
        except Exception:
            pass
        try:
            dirs.append(Path.cwd())
        except Exception:
            pass

        unique: list[Path] = []
        seen = set()
        for d in dirs:
            key = str(d).lower()
            if key not in seen:
                seen.add(key)
                unique.append(d)
        return unique

    def load_dropmp3_icon(self) -> QIcon:
        T("""ウィンドウ / タスクトレイ用アイコンを取得する。空アイコンを返さない。""")
        names = [
            "DropMp3.ico",
            "DropMp3_icon.ico",
            "icon.ico",
            T("音楽ファイルのインポートアイコン.ico"),
            "DropMp3.png",
            "DropMp3_icon.png",
            "icon.png",
            T("音楽ファイルのインポートアイコン.png"),
        ]

        for d in self.icon_search_dirs():
            for name in names:
                p = d / name
                if p.exists():
                    icon = QIcon(str(p))
                    if not icon.isNull():
                        app_log(f"App/tray icon loaded: {p}")
                        return icon

        try:
            exe_icon = QIcon(str(Path(sys.executable).resolve()))
            if not exe_icon.isNull():
                app_log(f"App/tray icon loaded from executable: {sys.executable}")
                return exe_icon
        except Exception as e:
            app_log(f"Executable icon load failed: {e}")

        try:
            app = QApplication.instance()
            if app is not None:
                fallback = app.style().standardIcon(QStyle.StandardPixmap.SP_MediaPlay)
                if not fallback.isNull():
                    app_log("Fallback tray icon loaded: SP_MediaPlay")
                    return fallback
        except Exception as e:
            app_log(f"Fallback icon load failed: {e}")

        app_log("WARNING: could not prepare a non-null icon")
        return QIcon()

    def apply_app_icon(self):
        T("""EXE化時またはスクリプト実行時に、可能ならアプリ用アイコンを設定する。""")
        icon = self.load_dropmp3_icon()
        if not icon.isNull():
            self.setWindowIcon(icon)
            app = QApplication.instance()
            if app is not None:
                app.setWindowIcon(icon)

    def about_image_path(self) -> Path | None:
        names = [
            "DropMP3.png",
            "DropMp3.png",
            "DropMP3_icon.png",
            "DropMP3_2.ico",
            "DropMP3.ico",
        ]
        for d in self.icon_search_dirs():
            for name in names:
                path = d / name
                if path.exists():
                    return path
        return None

    def current_track_tooltip_text(self) -> str:
        path = self.current_media_path()
        if path is None:
            return T("曲なし")
        return self.get_display_title(path)

    def build_tray_tooltip(self) -> str:
        header = f"DropMp3 - Version {normalize_version_text(self.current_app_version)}"
        current = self.current_track_tooltip_text()
        return f"{header}\n{current}" if current else header

    def setup_tray_icon(self):
        T("""タスクトレイ格納用のアイコンとメニューを準備する。""")
        if not QSystemTrayIcon.isSystemTrayAvailable():
            app_log("System tray is not available")
            return

        icon = self.windowIcon()
        if icon.isNull():
            app = QApplication.instance()
            if app is not None:
                icon = app.windowIcon()

        if icon.isNull():
            icon = self.load_dropmp3_icon()

        if icon.isNull():
            app_log("WARNING: tray icon is still null; tray may not be visible")
        else:
            app_log("Tray icon is non-null")

        self.tray_icon = QSystemTrayIcon(icon, self)
        self.tray_icon.setToolTip(self.build_tray_tooltip())
        self.tray_menu = QMenu(self)
        self.tray_menu.setStyleSheet(self.menu_style())
        self.tray_menu.aboutToShow.connect(self.rebuild_tray_menu)
        self.tray_icon.setContextMenu(self.tray_menu)
        self.tray_icon.activated.connect(self.on_tray_activated)
        self.rebuild_tray_menu()
        self.tray_icon.show()
        app_log("System tray icon prepared")

    def rebuild_tray_menu(self):
        menu = getattr(self, "tray_menu", None)
        if menu is None:
            return
        menu.clear()

        settings_action = QAction(T("設定"), self)
        settings_action.triggered.connect(lambda checked=False: QTimer.singleShot(0, lambda: self.show_gear_menu(QCursor.pos())))
        menu.addAction(settings_action)

        menu.addSeparator()

        player_action = QAction(T("Player表示"), self)
        player_action.triggered.connect(self.restore_from_tray)
        menu.addAction(player_action)

        self.populate_tray_playlist_preview(menu)

        menu.addSeparator()

        about_action = QAction(self.help_label("DropMp3について", "About DropMp3"), self)
        about_action.triggered.connect(lambda checked=False: self.show_about_dialog())
        menu.addAction(about_action)

        help_action = QAction("Help", self)
        help_action.triggered.connect(lambda checked=False: QTimer.singleShot(0, lambda: self.show_help_menu(QCursor.pos())))
        menu.addAction(help_action)

        menu.addSeparator()

        exit_action = QAction(T("終了"), self)
        exit_action.triggered.connect(self.exit_application)
        menu.addAction(exit_action)

    def tray_playlist_preview_indices(self) -> list[int]:
        if not self.playlist:
            return []
        center = self.current_index if self.one_shot_path is None else self.last_list_index_before_one_shot
        if center < 0:
            center = 0
        start = max(0, center - 5)
        end = min(len(self.playlist), center + 5)
        if end - start < 10:
            start = max(0, end - 10)
            end = min(len(self.playlist), start + 10)
        return list(range(start, end))

    def populate_tray_playlist_preview(self, menu: QMenu):
        indices = self.tray_playlist_preview_indices()
        if not indices:
            empty_action = QAction(T("曲がありません"), self)
            empty_action.setEnabled(False)
            menu.addAction(empty_action)
            return
        header_action = QAction(T("再生中前後のプレイリスト"), self)
        header_action.setEnabled(False)
        menu.addAction(header_action)
        for idx in indices:
            path = self.playlist[idx]
            prefix = "▶ " if idx == self.current_index and self.one_shot_path is None else "   "
            title = self.get_display_title(path)
            action = QAction(f"{prefix}{idx + 1:02d}. {title}", self)
            action.setToolTip(str(path))
            action.triggered.connect(lambda checked=False, i=idx: self.play_index(i, autoplay=True))
            menu.addAction(action)

    def minimize_to_tray(self):
        T("""通常Playerの最小化ボタンなどから、タスクトレイへ格納する。""")
        if self.tray_icon is None:
            app_log("Tray icon is not ready; returning to normal player instead")
            self.exit_art_only_mode()
            return

        if self.is_one_shot_panel_mode:
            self.settings.setValue("one_shot_geometry", self.geometry())
        elif self.is_art_only_mode:
            self.settings.setValue("art_only_geometry", self.geometry())

        self.save_settings()
        self.hide_auxiliary_windows_for_tray()
        self.tray_icon.show()
        self.hide()
        app_log("Minimized to system tray")
        try:
            self.tray_icon.showMessage(
                "DropMp3",
                T("タスクトレイに格納しました。アイコンをダブルクリックすると通常Playerに戻ります。"),
                QSystemTrayIcon.MessageIcon.Information,
                2500,
            )
        except Exception:
            pass

    def on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self.show_playlist_window()
        elif reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.restore_from_tray()

    def restore_from_tray(self):
        T("""タスクトレイから通常Playerへ復帰する。""")
        app_log("Restore from system tray")

        # トレイ復帰時は、必ず通常Playerへ戻す。
        if self.is_one_shot_panel_mode:
            self.exit_one_shot_panel_mode()
        elif self.is_art_only_mode:
            self.exit_art_only_mode()
        else:
            self.showNormal()
            self.show()

        self.raise_()
        self.activateWindow()
        self.save_settings()

    def hide_auxiliary_windows_for_tray(self):
        try:
            if self.log_window.isVisible():
                self.log_window.hide()
        except Exception:
            pass
        playlist_window = getattr(self, "playlist_window", None)
        if playlist_window is not None:
            try:
                playlist_window.hide()
            except Exception:
                pass

    def build_ui(self):
        app_log("Build UI")
        self.setStyleSheet("""
            QWidget { background-color: #171717; color: white; }
            QPushButton {
                background-color: #2b2b2b; color: white; border: 1px solid #555;
                border-radius: 20px; font-size: 20px; min-width: 42px; min-height: 42px;
            }
            QPushButton:hover { background-color: #3a3a3a; }
            QPushButton[dropHot="true"] { background-color:#4a2f18; border:2px solid #ffb36a; color:#ffffff; font-size:16px; font-weight:900; }
            QPushButton:checked { color: #ff9b45; border-color: #ff9b45; }
            QSlider::groove:horizontal { height: 6px; background: #444; border-radius: 3px; }
            QSlider::handle:horizontal { background: white; width: 14px; margin: -5px 0; border-radius: 7px; }
            QSlider::sub-page:horizontal { background: #ff7a2f; border-radius: 3px; }
            QLabel { color: white; }
        """)

        self.title_label = ScrollingLabel(T("ここに音声ファイルをDrop"))
        self.title_label.setFixedHeight(44)
        self.title_label.setToolTip("Ctrl+ホイール: タイトル文字サイズ変更")
        self.apply_title_label_style()
        self.title_label.setTextColor("#ffffff")

        self.random_check = QPushButton("🎨")
        self.random_check.setCheckable(True)
        self.random_check.setChecked(True)
        self.random_check.setToolTip(T("ランダム画像表示 ON/OFF\nON: 曲の最初は元画像を表示し、約20秒後からプレイリスト内の画像をランダム表示します\nOFF: 現在の曲に埋め込まれた元画像へ戻します"))
        self.random_check.setFixedSize(42, 42)

        self.header_widget = QWidget()
        self.header_widget.setFixedHeight(48)
        header_layout = QHBoxLayout(self.header_widget)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(8)

        self.load_playlist_button = QPushButton("📋")
        self.load_playlist_button.setToolTip(T("保存済みリストを開く"))
        self.load_playlist_button.setFixedSize(42, 42)
        self.load_playlist_button.setStyleSheet("""
            QPushButton {
                background-color:#2b2b2b; color:white; border:1px solid #666;
                border-radius:21px; font-size:20px; min-width:42px; min-height:42px;
            }
            QPushButton:hover { background-color:#1d3828; border-color:#41db78; color:#ffffff; }
        """)
        self.clear_playlist_button = QPushButton("🧹")
        self.clear_playlist_button.setToolTip(T("再生リストをクリア"))
        self.clear_playlist_button.setFixedSize(42, 42)
        self.clear_playlist_button.setStyleSheet("""
            QPushButton {
                background-color:#2b2b2b; color:white; border:1px solid #666;
                border-radius:21px; font-size:20px; min-width:42px; min-height:42px;
            }
            QPushButton:hover { background-color:#3a3020; border-color:#ff9b45; color:#ffb36a; }
        """)
        self.save_playlist_button = QPushButton("💾")
        self.save_playlist_button.setToolTip(T("再生リストを保存"))
        self.save_playlist_button.setFixedSize(42, 42)
        self.save_playlist_button.setStyleSheet("""
            QPushButton {
                background-color:#2b2b2b; color:white; border:1px solid #666;
                border-radius:21px; font-size:20px; min-width:42px; min-height:42px;
            }
            QPushButton:hover { background-color:#253245; border-color:#66a8ff; color:#ffffff; }
        """)
        self.new_playlist_button = QPushButton("+")
        self.new_playlist_button.setToolTip(T("新しい再生リストを作成"))
        self.new_playlist_button.setFixedSize(42, 42)
        self.new_playlist_button.setStyleSheet("""
            QPushButton {
                background-color:#2b2b2b; color:#f3f7ff; border:1px solid #666;
                border-radius:21px; font-size:28px; min-width:42px; min-height:42px;
                font-family:'Arial Black','Yu Gothic UI Semibold','Meiryo UI'; font-weight:900;
            }
            QPushButton:hover { background-color:#253245; border-color:#66a8ff; color:#ffffff; }
        """)
        self.subtitle_toggle_button = QPushButton("💬")
        self.subtitle_toggle_button.setToolTip(T("字幕表示を切り替えます"))
        self.subtitle_toggle_button.setFixedSize(42, 42)
        self.subtitle_toggle_button.setCheckable(True)
        self.set_subtitle_toggle_button_style(0, False)
        header_layout.addWidget(self.load_playlist_button, alignment=Qt.AlignLeft | Qt.AlignVCenter)
        header_layout.addWidget(self.clear_playlist_button, alignment=Qt.AlignLeft | Qt.AlignVCenter)
        header_layout.addWidget(self.save_playlist_button, alignment=Qt.AlignLeft | Qt.AlignVCenter)
        header_layout.addWidget(self.new_playlist_button, alignment=Qt.AlignLeft | Qt.AlignVCenter)
        header_layout.addSpacing(4)
        header_layout.addWidget(self.title_label, stretch=1)
        header_layout.addWidget(self.subtitle_toggle_button, alignment=Qt.AlignRight | Qt.AlignVCenter)
        header_layout.addWidget(self.random_check, alignment=Qt.AlignRight | Qt.AlignVCenter)
        self.update_random_art_button_style()

        self.one_shot_header_label = QLabel("OneShot")
        self.one_shot_header_label.setAlignment(Qt.AlignCenter)
        self.one_shot_header_label.setFixedHeight(26)
        self.one_shot_header_label.setStyleSheet("color:#ffb36a;background:#111;font-size:16px;font-weight:bold;")
        self.one_shot_header_label.hide()

        self.one_shot_name_label = ScrollingLabel(T("ここに音声ファイルをDrop"))
        self.one_shot_name_label.setFixedHeight(24)
        self.one_shot_name_label.setStyleSheet("color:white;background:#111;font-size:12px;")
        self.one_shot_name_label.hide()

        self.art_title_label = ScrollingLabel(T("ここに音声ファイルをDrop"))
        self.art_title_label.setFixedHeight(26)
        self.art_title_label.setStyleSheet("color:white;background:#111;font-size:12px;")
        self.art_title_label.hide()

        self.art_label = ArtLabel()
        self.art_label.setToolTip(T('クリック: 再生 / 一時停止\nダブルクリック: ミニプレイヤーモード切替\nホイール: 音量調整'))
        self.art_label.setAlignment(Qt.AlignCenter)
        self.art_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.art_label.setStyleSheet("""
            QLabel { background-color:#202020; border-radius:12px; color:#888; font-size:13px; }
        """)
        self.art_label.setText("Album Art")

        self.subtitle_overlay = SubtitleOverlay()

        # 字幕フォント設定は load_settings() から apply_subtitle_style() が呼ばれる前に
        # 必ず初期化しておく。未設定の旧 ini でもここが既定値になる。
        self.subtitle_font = QFont("Yu Gothic UI", 20)
        self.subtitle_font.setBold(True)
        self.subtitle_color = QColor("#66ff88")
        self.subtitle_overlay.set_subtitle_style(self.subtitle_font, self.subtitle_color)

        self.art_stack = QFrame()
        self.art_stack.setMinimumSize(128, 128)
        self.art_stack.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.art_stack.setStyleSheet("QFrame { background:#202020; border-radius:12px; }")
        art_grid = QGridLayout(self.art_stack)
        art_grid.setContentsMargins(0, 0, 0, 0)
        art_grid.setSpacing(0)
        art_grid.addWidget(self.art_label, 0, 0)
        art_grid.addWidget(self.subtitle_overlay, 0, 0)

        self.subtitle_close_button = QPushButton("×", self.art_stack)
        self.subtitle_close_button.setFixedSize(24, 24)
        self.subtitle_close_button.setToolTip(T("字幕を閉じる"))
        self.subtitle_close_button.setStyleSheet("""
            QPushButton {
                background-color: rgba(20,20,20,190); color: white; border: 1px solid #777;
                border-radius: 12px; font-size: 15px; font-weight: bold;
                min-width: 24px; min-height: 24px;
            }
            QPushButton:hover { background-color: rgba(80,45,30,220); border-color:#ff9b45; color:#ffb36a; }
        """)
        self.subtitle_close_button.hide()

        self.subtitle_open_button = QPushButton("💬", self.art_stack)
        self.subtitle_open_button.setFixedSize(30, 30)
        self.subtitle_open_button.setToolTip(T("字幕を表示"))
        self.subtitle_open_button.setStyleSheet("""
            QPushButton {
                background-color: rgba(20,20,20,175); color: white; border: 1px solid #777;
                border-radius: 15px; font-size: 15px;
                min-width: 30px; min-height: 30px;
            }
            QPushButton:hover { background-color: rgba(28,55,75,220); border-color:#43a5ff; color:#43a5ff; }
        """)
        self.subtitle_open_button.hide()

        self.random_art_notice_label = QLabel(T("ランダムでイメージ表示中...."), self.art_stack)
        self.random_art_notice_label.setAlignment(Qt.AlignCenter)
        self.random_art_notice_label.setStyleSheet("color:rgba(255,255,255,220); background:rgba(0,0,0,120); font-size:12px; padding:4px 10px; border-radius:8px;")
        self.random_art_notice_label.hide()

        self.left_panel = QFrame()
        self.left_panel.setMinimumWidth(180)
        self.left_panel.setMaximumWidth(16777215)
        self.apply_left_panel_style()
        self.shuffle_button = QPushButton("🔀")
        self.sort_button = QPushButton("📁")
        self.repeat_button = QPushButton("🔁")
        self.search_playlist_button = QPushButton("🔍")
        self.close_drawer_button = QPushButton("×")
        self.repeat_button.setCheckable(True)
        for b in (self.shuffle_button, self.sort_button, self.repeat_button, self.search_playlist_button):
            b.setFixedSize(34, 34)
        self.update_playlist_toolbar_buttons()
        self.search_playlist_button.setToolTip(T("プレイリストを検索します"))
        self.close_drawer_button.setFixedSize(30, 30)
        self.close_drawer_button.setToolTip(T("リストを閉じる"))
        self.close_drawer_button.setStyleSheet("QPushButton{border-radius:15px;font-size:20px;min-width:30px;min-height:30px;color:#ddd;} QPushButton:hover{color:#ff9b45;border-color:#ff9b45;}")
        self.shuffle_button.setToolTip(T("プレイリストをシャッフルします"))
        self.sort_button.setToolTip(T("プレイリストをファイル名順に並べ替えます"))
        self.repeat_button.setToolTip(T("リピート切替: Off → 1曲 → 全曲"))

        left_toolbar = QHBoxLayout()
        left_toolbar.setContentsMargins(8, 8, 8, 4)
        left_toolbar.addWidget(self.shuffle_button)
        left_toolbar.addWidget(self.sort_button)
        left_toolbar.addWidget(self.repeat_button)
        left_toolbar.addStretch()
        left_toolbar.addWidget(self.search_playlist_button)
        left_toolbar.addWidget(self.close_drawer_button)

        self.left_list = EditablePlaylistWidget()
        self.left_list.setToolTip("Ctrl+ホイール: 文字サイズ変更")
        left_layout = QVBoxLayout(self.left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(0)
        left_layout.addLayout(left_toolbar)
        left_layout.addWidget(self.left_list, stretch=1)
        self.playlist_footer_label = QLabel("0/0")
        self.playlist_footer_label.setAlignment(Qt.AlignCenter)
        self.playlist_footer_label.setMinimumHeight(24)
        self.playlist_footer_label.setStyleSheet("color:#bdbdbd; background:#0b0b0b; border-top:1px solid #333; font-size:12px; padding:3px;")
        left_layout.addWidget(self.playlist_footer_label)
        self.left_panel.hide()

        self.prev_button = QPushButton("⏮")
        self.seek_back_button = SeekStepButton(-1, 10)
        self.play_button = QPushButton("▶")
        self.seek_forward_button = SeekStepButton(1, 10)
        self.next_button = QPushButton("⏭")
        for b in (self.prev_button, self.play_button, self.next_button):
            b.setFixedSize(63, 63)
            b.setStyleSheet("""
                QPushButton {
                    background-color: #2b2b2b; color: white; border: 1px solid #555;
                    border-radius: 31px; font-size: 30px; min-width: 63px; min-height: 63px;
                }
                QPushButton:hover { background-color: #3a3a3a; }
            """)
            b.setFocusPolicy(Qt.NoFocus)
        for b in (self.seek_back_button, self.seek_forward_button):
            b.setFixedSize(63, 63)
        self.prev_button.setToolTip(T("前の曲へ戻ります"))
        self.seek_back_button.setToolTip(T("10秒戻ります"))
        self.play_button.setToolTip(T("再生 / 一時停止を切り替えます"))
        self.seek_forward_button.setToolTip(T("10秒進みます"))
        self.next_button.setToolTip(T("次の曲へ進みます"))
        self.one_shot_button = DropOneShotButton("🎯")
        self.one_shot_button.configure_drop_expand(QSize(42, 42), QSize(96, 60), expanded_text="DROP\n🎯")
        self.one_shot_button.setCheckable(True)
        self.one_shot_button.setToolTip(T("ワンショット再生モード ON/OFF\nONの間は、ドロップした曲をリストに追加せず一時再生します\nこのアイコンに音楽ファイルをDropするとワンショットで再生されます"))
        self.one_shot_button.setStyleSheet("""
            QPushButton {
                background-color: #2b2b2b;
                color: white;
                border: 1px solid #555;
                border-radius: 20px;
                font-size: 20px;
                min-width: 42px;
                min-height: 42px;
            }
            QPushButton:hover { background-color: #3a3a3a; }
            QPushButton[dropHot="true"] {
                background-color:#4a2f18;
                border:2px solid #ffb36a;
                color:#ffffff;
                font-size:16px;
                font-weight:900;
            }
            QPushButton:checked {
                color: #ff9b45;
                border: 2px solid #ff9b45;
                background-color: #3a281c;
            }
        """)
        self.subtitle_font_button = QPushButton("A")
        self.subtitle_font_button.setToolTip(T("字幕フォント / サイズ / 色を変更"))
        self.subtitle_font_button.setFixedSize(42, 42)
        self.subtitle_font_button.setStyleSheet("""
            QPushButton {
                background-color: #2b2b2b;
                color: #ffe6a8;
                border: 1px solid #555;
                border-radius: 20px;
                font-family: 'Arial Black', 'Yu Gothic UI Semibold', 'Meiryo UI';
                font-size: 22px;
                font-weight: 900;
            }
            QPushButton:hover { background-color:#3a3020; border-color:#ffb36a; color:#ffffff; }
        """)
        self.small_subtitle_font_button = QPushButton("A")
        self.small_subtitle_font_button.setToolTip(T("字幕フォント / サイズ / 色を変更"))
        self.small_subtitle_font_button.setFixedSize(30, 30)
        self.small_subtitle_font_button.setStyleSheet("""
            QPushButton {
                background-color: rgba(20,20,20,190); color:#ffe6a8; border:1px solid #666;
                border-radius:15px; font-family:'Arial Black','Yu Gothic UI Semibold','Meiryo UI';
                font-size:16px; font-weight:900; min-width:30px; min-height:30px;
            }
            QPushButton:hover { background-color:#3a3020; border-color:#ffb36a; color:#ffffff; }
        """)
        self.small_subtitle_font_button.hide()
        self.small_one_shot_button = DropOneShotButton("🎯")
        self.small_one_shot_button.configure_drop_expand(QSize(30, 30), QSize(78, 50), expanded_text="DROP\n🎯")
        self.small_one_shot_button.setToolTip(T("このアイコンに音楽ファイルをDropするとワンショットで再生されます\nワンショット再生後、約0.3秒後に通常再生へ戻ります"))
        self.small_one_shot_button.setStyleSheet("""
            QPushButton {
                background-color: rgba(20,20,20,190); color:white; border:1px solid #666;
                border-radius:15px; font-size:15px; min-width:30px; min-height:30px;
            }
            QPushButton:hover { background-color:#3a281c; border-color:#ff9b45; color:#ffb36a; }
            QPushButton[dropHot="true"] { background-color:#4a2f18; border:2px solid #ffb36a; color:#ffffff; font-size:13px; font-weight:900; }
        """)
        self.small_one_shot_button.hide()
        self.gear_button = QPushButton("⚙")
        self.gear_button.setToolTip(T("設定メニューを開きます\nリスト作成、リストクリア、ログ表示などを操作できます"))
        self.help_button = QPushButton("?")
        self.help_button.setToolTip("Help")
        self.help_button.setFixedSize(42, 42)
        self.help_button.setStyleSheet("""
            QPushButton {
                background-color:#2b2b2b; color:#dfffe7; border:1px solid #555;
                border-radius:21px; font-family:'Arial Black','Yu Gothic UI Semibold','Meiryo UI';
                font-size:22px; font-weight:900; min-width:42px; min-height:42px;
            }
            QPushButton:hover { background-color:#1d3828; border-color:#41db78; color:#ffffff; }
        """)

        self.volume_label = VolumeLabel()
        self.update_volume_label()

        control_layout = QHBoxLayout()
        control_layout.setContentsMargins(0, 0, 0, 0)
        control_layout.addWidget(self.volume_label, alignment=Qt.AlignLeft | Qt.AlignVCenter)
        control_layout.addStretch(1)
        control_layout.addWidget(self.prev_button)
        control_layout.addWidget(self.seek_back_button)
        control_layout.addWidget(self.play_button)
        control_layout.addWidget(self.seek_forward_button)
        control_layout.addWidget(self.next_button)
        control_layout.addStretch(1)
        control_layout.addWidget(self.subtitle_font_button)
        control_layout.addWidget(self.one_shot_button)
        control_layout.addWidget(self.gear_button)
        control_layout.addWidget(self.help_button)

        self.small_time_label = QLabel("0:00 / 0:00")
        self.small_time_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.small_time_label.setStyleSheet("color:rgba(255,160,64,180);background:transparent;font-size:12px;font-weight:bold;padding-left:7px;")
        self.small_time_label.hide()
        self.small_play_button = QPushButton("▶")
        self.small_play_button.setToolTip(T("再生 / 一時停止を切り替えます"))
        self.small_play_button.setFixedSize(38, 38)
        self.small_play_button.setFocusPolicy(Qt.NoFocus)
        self.small_play_button.hide()
        self.small_seek_back_button = SeekStepButton(-1, 10)
        self.small_seek_back_button.setToolTip(T("10秒戻ります"))
        self.small_seek_back_button.setFixedSize(30, 30)
        self.small_seek_back_button.hide()
        self.small_seek_forward_button = SeekStepButton(1, 10)
        self.small_seek_forward_button.setToolTip(T("10秒進みます"))
        self.small_seek_forward_button.setFixedSize(30, 30)
        self.small_seek_forward_button.hide()
        self.small_next_button = QPushButton("⏭")
        self.small_next_button.setToolTip(T("次の曲へ進みます"))
        self.small_next_button.setFixedSize(38, 38)
        self.small_next_button.setFocusPolicy(Qt.NoFocus)
        self.small_next_button.hide()

        self.control_icon_widgets = [
            self.prev_button,
            self.seek_back_button,
            self.play_button,
            self.seek_forward_button,
            self.next_button,
            self.small_seek_back_button,
            self.small_play_button,
            self.small_seek_forward_button,
            self.small_next_button,
        ]
        for widget in self.control_icon_widgets:
            widget.installEventFilter(self)
            widget.setToolTip((widget.toolTip() + "\n" if widget.toolTip() else "") + "Ctrl+ホイール: 操作アイコン拡大縮小")
        self.apply_control_icon_scale()

        self.small_control_layout = QHBoxLayout()
        self.small_control_layout.setContentsMargins(0, 0, 8, 8)
        self.small_control_layout.setSpacing(6)
        self.small_control_layout.addWidget(self.small_time_label, stretch=1)
        self.small_control_layout.addWidget(self.small_seek_back_button)
        self.small_control_layout.addWidget(self.small_play_button)
        self.small_control_layout.addWidget(self.small_seek_forward_button)
        self.small_control_layout.addWidget(self.small_next_button)
        self.small_control_layout.addWidget(self.small_subtitle_font_button)
        self.small_control_layout.addWidget(self.small_one_shot_button)

        self.current_time_label = TimeDisplayLabel("0:00")
        self.current_time_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.total_time_label = TimeDisplayLabel("0:00")
        self.total_time_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.position_slider = QSlider(Qt.Horizontal)
        self.position_slider.setToolTip(T("ドラッグして再生位置を移動します"))
        self.position_slider.setRange(0, 0)
        seek_layout = QHBoxLayout()
        seek_layout.setContentsMargins(0, 0, 0, 0)
        seek_layout.addWidget(self.current_time_label)
        seek_layout.addWidget(self.position_slider, stretch=1)
        seek_layout.addWidget(self.total_time_label)

        self.drawer_rail = QFrame()
        self.drawer_rail.setFixedWidth(44)
        self.drawer_rail.setStyleSheet("""
            QFrame { background:#101010; border-right:1px solid #2c2c2c; }
            QPushButton {
                background:transparent; color:#f0f0f0; border:0; border-radius:10px;
                font-size:22px; min-width:36px; min-height:36px;
            }
            QPushButton:hover { background:#252525; color:#ff9b45; }
        """)
        rail_layout = QVBoxLayout(self.drawer_rail)
        rail_layout.setContentsMargins(4, 8, 4, 8)
        rail_layout.setSpacing(12)
        self.drawer_button = QPushButton("☰")
        self.drawer_button.setToolTip(T("再生リストを開く / 閉じる"))
        self.drawer_button.setFixedSize(36, 36)
        rail_layout.addWidget(self.drawer_button)
        rail_layout.addStretch()

        self.main_splitter = QSplitter(Qt.Horizontal)
        self.main_splitter.setChildrenCollapsible(False)
        self.main_splitter.setHandleWidth(7)
        self.main_splitter.setStyleSheet("""
            QSplitter::handle {
                background-color: #303030;
                border-left: 1px solid #444;
                border-right: 1px solid #111;
            }
            QSplitter::handle:hover {
                background-color: #ff7a2f;
            }
        """)
        self.main_splitter.addWidget(self.left_panel)
        self.main_splitter.addWidget(self.art_stack)
        self.main_splitter.setStretchFactor(0, 0)
        self.main_splitter.setStretchFactor(1, 1)
        self.main_splitter.setSizes([320, 720])
        self.main_splitter.splitterMoved.connect(lambda *_: self.save_settings())

        self.main_area_layout = QHBoxLayout()
        self.main_area_layout.setContentsMargins(0, 0, 0, 0)
        self.main_area_layout.setSpacing(0)
        self.main_area_layout.addWidget(self.drawer_rail)
        self.main_area_layout.addWidget(self.main_splitter, stretch=1)

        self.root_layout = QVBoxLayout()
        self.root_layout.setContentsMargins(10, 8, 10, 8)
        self.root_layout.setSpacing(8)
        self.root_layout.addWidget(self.one_shot_header_label)
        self.root_layout.addWidget(self.one_shot_name_label)
        self.root_layout.addWidget(self.art_title_label)
        self.root_layout.addWidget(self.header_widget)
        self.root_layout.addLayout(self.main_area_layout, stretch=1)
        self.root_layout.addLayout(control_layout)
        self.root_layout.addLayout(self.small_control_layout)
        self.root_layout.addLayout(seek_layout)
        self.setLayout(self.root_layout)

        self.normal_control_widgets = [
            self.header_widget, self.prev_button, self.seek_back_button, self.play_button, self.seek_forward_button, self.next_button,
            self.subtitle_font_button, self.one_shot_button, self.gear_button, self.volume_label,
            self.help_button,
            self.current_time_label, self.total_time_label, self.position_slider,
        ]
        self.one_shot_widgets = [self.one_shot_header_label, self.one_shot_name_label]
        self.small_widgets = [self.small_time_label, self.small_seek_back_button, self.small_play_button, self.small_seek_forward_button, self.small_next_button, self.small_subtitle_font_button, self.small_one_shot_button, self.art_title_label]

    def connect_signals(self):
        app_log("Connect signals")
        self.play_button.clicked.connect(self.toggle_play)
        self.small_play_button.clicked.connect(self.toggle_play)
        self.prev_button.clicked.connect(self.play_prev)
        self.seek_back_button.clicked.connect(self.seek_backward_10s)
        self.small_seek_back_button.clicked.connect(self.seek_backward_10s)
        self.seek_forward_button.clicked.connect(self.seek_forward_10s)
        self.small_seek_forward_button.clicked.connect(self.seek_forward_10s)
        self.next_button.clicked.connect(lambda: self.play_next())
        self.small_next_button.clicked.connect(lambda: self.play_next())
        self.gear_button.clicked.connect(lambda _checked=False: self.show_gear_menu())
        self.help_button.clicked.connect(lambda _checked=False: self.show_help_menu())
        self.subtitle_toggle_button.clicked.connect(self.toggle_subtitle_panel_from_header)
        self.subtitle_font_button.clicked.connect(self.open_subtitle_font_dialog)
        self.small_subtitle_font_button.clicked.connect(self.open_subtitle_font_dialog)
        self.one_shot_button.toggled.connect(self.set_one_shot_mode)
        self.one_shot_button.filesDropped.connect(self.play_dropped_one_shot)
        self.small_one_shot_button.filesDropped.connect(self.play_dropped_one_shot)
        self.shuffle_button.clicked.connect(self.shuffle_playlist)
        self.sort_button.clicked.connect(self.sort_playlist_by_filename)
        self.repeat_button.clicked.connect(self.cycle_repeat_mode)
        self.search_playlist_button.clicked.connect(self.search_playlist_dialog)
        self.drawer_button.clicked.connect(self.toggle_playlist_drawer)
        self.load_playlist_button.clicked.connect(self.show_saved_playlist_popup)
        self.clear_playlist_button.clicked.connect(self.confirm_clear_playlist)
        self.save_playlist_button.clicked.connect(self.export_playlist_file_dialog)
        self.new_playlist_button.clicked.connect(self.create_new_playlist)
        self.close_drawer_button.clicked.connect(self.close_playlist_drawer)
        self.left_list.deletePressed.connect(self.delete_selected_from_left_playlist)
        self.left_list.orderChanged.connect(self.apply_left_playlist_order)
        self.left_list.activatedIndex.connect(self.play_playlist_index_from_view)
        self.left_list.filesDroppedAt.connect(self.insert_files_at_left_row)
        self.left_list.itemContextRequested.connect(self.show_left_playlist_item_menu)
        self.left_list.fontWheelChanged.connect(self.on_playlist_font_wheel_changed)
        self.title_label.fontWheelChanged.connect(self.on_title_font_wheel_changed)
        self.current_time_label.wheelChanged.connect(self.on_time_font_wheel_changed)
        self.total_time_label.wheelChanged.connect(self.on_time_font_wheel_changed)
        self.random_art_timer.timeout.connect(self.show_random_playlist_art)
        self.random_art_delay_timer.timeout.connect(self.start_random_art_mode)
        self.random_check.toggled.connect(self.on_random_art_check_toggled)

        self.art_label.doubleClicked.connect(self.on_art_double_clicked)
        self.art_label.clicked.connect(self.on_art_clicked)
        self.art_label.wheelChanged.connect(self.on_art_wheel_changed)
        self.volume_label.wheelChanged.connect(self.on_volume_wheel_changed)
        self.subtitle_close_button.clicked.connect(self.hide_subtitle_panel)
        self.subtitle_open_button.clicked.connect(self.show_subtitle_panel)
        self.art_label.leftPressed.connect(self.on_art_left_pressed)
        self.art_label.leftMoved.connect(self.on_art_left_moved)
        self.art_label.leftReleased.connect(self.on_art_left_released)

        self.player.positionChanged.connect(self.on_position_changed)
        self.player.durationChanged.connect(self.on_duration_changed)
        self.player.playbackStateChanged.connect(self.on_state_changed)
        self.player.mediaStatusChanged.connect(self.on_media_status_changed)
        self.player.errorOccurred.connect(self.on_player_error)
        self.media_devices.audioOutputsChanged.connect(self.on_audio_outputs_changed)
        self.position_slider.sliderPressed.connect(self.on_seek_start)
        self.position_slider.sliderReleased.connect(self.on_seek_end)
        self.position_slider.sliderMoved.connect(self.on_seek_move)

    def audio_device_id(self, device) -> bytes:
        try:
            raw = device.id()
            return bytes(raw) if raw is not None else b""
        except Exception:
            return b""

    def audio_device_name(self, device) -> str:
        try:
            name = str(device.description() or "").strip()
            return name or "Unknown"
        except Exception:
            return "Unknown"

    def on_audio_outputs_changed(self):
        current_device = self.audio.device()
        new_default = QMediaDevices.defaultAudioOutput()
        current_id = self.audio_device_id(current_device)
        previous_default_id = self.last_known_default_audio_device_id
        new_default_id = self.audio_device_id(new_default)
        self.last_known_default_audio_device_id = new_default_id

        if current_id and previous_default_id and current_id != previous_default_id:
            app_log(
                "[AUDIO] audio outputs changed; current device is custom/fixed, "
                f"keep using: {self.audio_device_name(current_device)}"
            )
            return
        if new_default.isNull():
            app_log("[AUDIO] audio outputs changed; no default output device is available")
            return
        if current_id == new_default_id:
            app_log(f"[AUDIO] default output unchanged: {self.audio_device_name(new_default)}")
            return
        try:
            self.audio.setDevice(new_default)
            app_log(
                "[AUDIO] switched output to new system default: "
                f"{self.audio_device_name(new_default)}"
            )
        except Exception as exc:
            app_log(f"[AUDIO] failed to switch to new default output: {exc}")

    def setup_media_shortcuts(self):
        self.media_shortcuts = []
        shortcut_specs = [
            (QKeySequence(Qt.Key_Space), self.handle_toggle_play_shortcut),
            (QKeySequence(Qt.Key_Right), self.handle_seek_forward_shortcut),
            (QKeySequence(Qt.Key_Left), self.handle_seek_backward_shortcut),
        ]
        for sequence, handler in shortcut_specs:
            shortcut = QShortcut(sequence, self)
            shortcut.setContext(Qt.WidgetWithChildrenShortcut)
            shortcut.activated.connect(handler)
            self.media_shortcuts.append(shortcut)

    def is_media_shortcut_blocked(self) -> bool:
        widget = QApplication.focusWidget()
        if widget is None:
            return False
        blocked_types = (QTextEdit, QPlainTextEdit, QComboBox, QSpinBox, QListWidget, QTreeWidget)
        if isinstance(widget, blocked_types):
            return True
        blocked_names = ("QLineEdit", "QAbstractSpinBox", "QAbstractItemView", "QMenu")
        return any(widget.inherits(name) for name in blocked_names)

    def handle_toggle_play_shortcut(self):
        if self.is_media_shortcut_blocked():
            return
        self.toggle_play()

    def handle_seek_backward_shortcut(self):
        if self.is_media_shortcut_blocked():
            return
        self.seek_backward_10s()

    def handle_seek_forward_shortcut(self):
        if self.is_media_shortcut_blocked():
            return
        self.seek_forward_10s()

    def play_dropped_one_shot(self, dropped: list[Path]):
        files = self.normalize_dropped_files(dropped)
        if not files:
            app_log("One-shot button drop ignored: no supported audio files")
            return
        app_log(f"One-shot button drop accepted: {files[0]}")
        self.play_one_shot(files[0], enter_panel=False)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls() or event.mimeData().hasText():
            event.acceptProposedAction()

    def dropEvent(self, event):
        dropped = []
        for url in event.mimeData().urls():
            local = url.toLocalFile()
            if local:
                dropped.append(Path(local))
        if event.mimeData().hasText() and not dropped:
            files = parse_plain_path_list_text(event.mimeData().text())
            if not files:
                app_log("Drop ignored: text/plain did not contain supported audio paths")
                QMessageBox.information(self, T("ファイルがありません"), T("対応している曲が見つかりませんでした。"))
                return
            if self.one_shot_mode:
                self.play_one_shot(files[0])
            else:
                self.import_playlist_drop_with_dialog(files)
            event.acceptProposedAction()
            return
        if not dropped:
            return
        has_playlist = any(p.is_file() and p.suffix.lower() in LIST_FILE_EXTS for p in dropped)
        files = self.normalize_dropped_files(dropped)
        if not files:
            app_log("Drop ignored: no supported audio files")
            QMessageBox.information(self, T("ファイルがありません"), T("対応している曲が見つかりませんでした。"))
            return
        if has_playlist and not self.one_shot_mode:
            self.import_playlist_drop_with_dialog(files)
            event.acceptProposedAction()
            return
        if self.one_shot_mode:
            app_log(f"Drop accepted as one-shot: {len(files)} file(s)")
            self.play_one_shot(files[0])
            event.acceptProposedAction()
            return
        start_index = len(self.playlist)
        self.add_files_to_playlist(files, start_index, autoplay=True)
        app_log(f"Drop accepted at end: {len(files)} file(s)")
        event.acceptProposedAction()

    def normalize_dropped_files(self, dropped: list[Path]) -> list[Path]:
        files = []
        for path in dropped:
            if path.is_file() and path.suffix.lower() in AUDIO_EXTS:
                files.append(path)
            elif path.is_file() and path.suffix.lower() in LIST_FILE_EXTS:
                files.extend(parse_playlist_file(path))
            elif path.is_dir():
                files.extend(self.collect_audio_files(path))
        return files

    def handle_startup_audio_files(self, files: list[Path]):
        normalized = [Path(p) for p in files if Path(p).exists() and Path(p).is_file() and Path(p).suffix.lower() in AUDIO_EXTS]
        if not normalized:
            return
        app_log(f"Startup audio request detected: {normalized[0]}")
        self.play_one_shot(normalized[0], enter_panel=False)

    def import_playlist_drop_with_dialog(self, files: list[Path]):
        msg = QMessageBox(self)
        msg.setWindowTitle(T("リストファイルをDropしました"))
        msg.setText(T("リストファイルをどのように読み込みますか？"))
        add_btn = msg.addButton(T("追加挿入"), QMessageBox.AcceptRole)
        replace_btn = msg.addButton(T("置換挿入"), QMessageBox.DestructiveRole)
        msg.addButton(T("取消"), QMessageBox.RejectRole)
        msg.exec()
        clicked = msg.clickedButton()
        if clicked == add_btn:
            self.add_files_to_playlist(files, len(self.playlist), autoplay=True)
            app_log(f"Playlist drop add/insert: {len(files)} file(s)")
        elif clicked == replace_btn:
            self.playlist = []
            self.current_index = -1
            self.add_files_to_playlist(files, 0, autoplay=True)
            app_log(f"Playlist drop replace/insert: {len(files)} file(s)")
        else:
            app_log("Playlist drop canceled")

    def add_files_to_playlist(self, files: list[Path], insert_index: int | None = None, autoplay: bool = True):
        if not files:
            return
        if insert_index is None:
            insert_index = len(self.playlist)
        insert_index = max(0, min(insert_index, len(self.playlist)))
        was_current_path = self.current_media_path()
        for offset, file in enumerate(files):
            self.playlist.insert(insert_index + offset, file)
        if was_current_path in self.playlist:
            self.current_index = self.playlist.index(was_current_path)
        self.update_playlist_panel()
        self.update_left_panel_visibility()
        self.update_random_art_pool()
        self.save_settings()
        if autoplay:
            self.play_index(insert_index, autoplay=True)

    def insert_files_at_left_row(self, row: int, dropped: list[Path]):
        files = self.normalize_dropped_files(dropped)
        if not files:
            app_log("Left-list drop ignored: no supported audio files")
            return
        app_log(f"Left-list drop accepted: row={row}, files={len(files)}")
        self.add_files_to_playlist(files, row, autoplay=True)

    def collect_audio_files(self, folder: Path):
        app_log(f"Collect audio files from folder: {folder}")
        result = []
        for root, _dirs, names in os.walk(folder):
            for name in names:
                path = Path(root) / name
                if path.suffix.lower() in AUDIO_EXTS:
                    result.append(path)
        app_log(f"Collected {len(result)} audio file(s)")
        return sorted(result)

    def current_media_path(self) -> Path | None:
        if self.one_shot_path is not None:
            return self.one_shot_path
        if 0 <= self.current_index < len(self.playlist):
            return self.playlist[self.current_index]
        return None

    def play_index(self, index: int, autoplay=True, restore_position=0):
        if not self.playlist or not (0 <= index < len(self.playlist)):
            app_log(f"play_index ignored: index={index}")
            return
        self.current_index = index
        self.one_shot_path = None
        path = self.playlist[index]
        app_log(f"Play index={index}, autoplay={autoplay}, restore_position={format_ms(restore_position)}, file={path}")
        self.pending_restore_position = int(restore_position or 0)
        self.restored_once = False
        self.player.setSource(QUrl.fromLocalFile(str(path)))
        self.update_current_title_labels()
        self.update_random_art_pool()
        has_original_art = self.load_album_art(path)
        self.prepare_random_art_for_current_track(has_original_art)
        self.load_subtitles_for(path)
        self.update_playlist_panel()
        self.update_left_panel_visibility()
        if autoplay:
            self.player.play()
        else:
            self.player.pause()
        self.save_settings()

    def play_one_shot(self, path: Path, enter_panel: bool = True):
        current_normal_path = None
        if 0 <= self.current_index < len(self.playlist):
            current_normal_path = self.playlist[self.current_index]
        self.one_shot_return_path = current_normal_path
        self.one_shot_return_index = self.current_index
        self.one_shot_return_position = int(self.player.position()) if current_normal_path is not None and self.one_shot_path is None else 0
        self.one_shot_return_was_playing = self.player.playbackState() == QMediaPlayer.PlayingState

        self.one_shot_path = path
        self.last_list_index_before_one_shot = self.current_index
        if enter_panel and not self.is_one_shot_panel_mode:
            self.enter_one_shot_panel_mode()
        app_log(f"One-shot play: {path}")
        self.pending_restore_position = 0
        self.restored_once = False
        self.player.setSource(QUrl.fromLocalFile(str(path)))
        title = self.get_display_title(path)
        self.one_shot_name_label.setText(title)
        self.art_title_label.setText(title)
        self.title_label.setText("[OneShot] " + title)
        has_original_art = self.load_album_art(path)
        self.prepare_random_art_for_current_track(has_original_art)
        self.load_subtitles_for(path)
        self.refresh_playlist_window()
        self.player.play()
        self.save_settings()

    def restore_after_one_shot(self):
        self.one_shot_name_label.setText(T("ここに音声ファイルをDrop"))
        if self.one_shot_return_path is None or not self.playlist:
            self.update_current_title_labels()
            return
        if self.one_shot_return_path in self.playlist:
            self.current_index = self.playlist.index(self.one_shot_return_path)
        elif 0 <= self.one_shot_return_index < len(self.playlist):
            self.current_index = self.one_shot_return_index
        else:
            self.current_index = 0
        path = self.playlist[self.current_index]
        self.pending_restore_position = max(0, int(self.one_shot_return_position or 0))
        self.restored_once = False
        self.player.setSource(QUrl.fromLocalFile(str(path)))
        self.update_current_title_labels()
        self.art_title_label.setText(self.get_display_title(path))
        has_original_art = self.load_album_art(path)
        self.prepare_random_art_for_current_track(has_original_art)
        self.load_subtitles_for(path)
        self.update_playlist_panel()
        if self.one_shot_return_was_playing:
            self.player.play()
        else:
            self.player.pause()
        self.save_settings()

    def toggle_play(self):
        if self.player.playbackState() == QMediaPlayer.PlayingState:
            app_log("Pause")
            self.player.pause()
        else:
            app_log("Play / resume")
            if self.current_index == -1 and self.playlist and self.one_shot_path is None:
                self.play_index(0, autoplay=True)
            else:
                self.player.play()

    def seek_relative(self, delta_ms: int):
        source = self.player.source()
        if source.isEmpty() and self.current_index < 0 and self.one_shot_path is None:
            return
        duration = max(0, self.player.duration())
        current = self.position_slider.value() if self.user_is_seeking else self.player.position()
        target = max(0, current + delta_ms)
        if duration > 0:
            target = min(target, duration)
        app_log(f"Seek relative: {delta_ms} ms -> {target} ms")
        self.player.setPosition(target)
        if self.user_is_seeking:
            self.position_slider.setValue(target)
        self.current_time_label.setText(format_ms(target))
        self.update_small_time_label(target, duration)
        self.save_settings()

    def seek_backward_10s(self):
        self.seek_relative(-self.SEEK_STEP_MS)

    def seek_forward_10s(self):
        self.seek_relative(self.SEEK_STEP_MS)

    def play_prev(self):
        if not self.playlist:
            return
        if self.one_shot_path is not None:
            base = self.last_list_index_before_one_shot
            if base < 0:
                base = 0
            self.play_index(base, autoplay=True)
            return
        self.play_index((self.current_index - 1) % len(self.playlist), autoplay=True)

    def play_next(self, wrap: bool = True):
        if not self.playlist:
            return
        if self.one_shot_path is not None:
            base = self.last_list_index_before_one_shot
            if base < 0:
                base = self.current_index
            next_index = base + 1
        else:
            next_index = self.current_index + 1
        if next_index >= len(self.playlist):
            if not wrap:
                return
            next_index = 0
        self.play_index(next_index, autoplay=True)

    def on_media_status_changed(self, status):
        app_log(f"Media status changed: {status}")
        if status == QMediaPlayer.EndOfMedia:
            if self.one_shot_path is not None:
                app_log("End of one-shot media; normal playback will resume after 0.3 sec")
                self.one_shot_path = None
                self.player.stop()
                QTimer.singleShot(300, self.restore_after_one_shot)
                self.save_settings()
            elif self.repeat_mode == "one" and 0 <= self.current_index < len(self.playlist):
                app_log("End of media: repeat one")
                self.play_index(self.current_index, autoplay=True)
            elif self.repeat_mode == "all" and self.playlist:
                app_log("End of media: repeat all")
                self.play_next(wrap=True)
            else:
                app_log("End of media: no repeat")
                self.play_next(wrap=False)

    def on_state_changed(self, state):
        app_log(f"Playback state changed: {state}")
        if state == QMediaPlayer.PlayingState:
            self.play_button.setText("⏸")
            self.small_play_button.setText("⏸")
            self.resume_random_art_timers_for_playback_play()
        else:
            self.play_button.setText("▶")
            self.small_play_button.setText("▶")
            # 一時停止・停止中はランダム画像の自動切替も止める。
            self.pause_random_art_timers_for_playback_pause()

    def on_player_error(self, error, error_string):
        app_log(f"[PLAYER ERROR] error={error}, message={error_string}")

    def on_duration_changed(self, duration):
        app_log(f"Duration changed: {format_ms(duration)} ({duration} ms)")
        self.position_slider.setRange(0, max(0, duration))
        self.total_time_label.setText(format_ms(duration))
        self.update_small_time_label(self.player.position(), duration)
        if self.pending_restore_position > 0 and not self.restored_once:
            pos = min(self.pending_restore_position, max(0, duration - 1000))
            app_log(f"Restore playback position: {format_ms(pos)} ({pos} ms)")
            QTimer.singleShot(200, lambda: self.player.setPosition(pos))
            self.restored_once = True

    def on_position_changed(self, position):
        self.current_time_label.setText(format_ms(position))
        self.update_small_time_label(position, self.player.duration())
        self.subtitle_overlay.update_position(position)
        self.update_subtitle_controls()
        if not self.user_is_seeking:
            self.position_slider.setValue(position)

    def update_small_time_label(self, position=None, duration=None):
        if position is None:
            position = self.player.position()
        if duration is None:
            duration = self.player.duration()
        self.small_time_label.setText(f"{format_ms(position)} / {format_ms(duration)}")

    def on_seek_start(self):
        self.user_is_seeking = True

    def on_seek_move(self, position):
        self.current_time_label.setText(format_ms(position))
        self.update_small_time_label(position, self.player.duration())
        self.subtitle_overlay.update_position(position)
        self.update_subtitle_controls()

    def on_seek_end(self):
        self.user_is_seeking = False
        pos = self.position_slider.value()
        self.player.setPosition(pos)
        self.save_settings()

    def get_display_title(self, path: Path):
        try:
            audio = MutagenFile(str(path), easy=True)
            if audio:
                title = audio.get("title", [None])[0]
                artist = audio.get("artist", [None])[0]
                if title and artist:
                    return f"{artist} - {title}"
                if title:
                    return title
        except Exception as e:
            app_log(f"[TAG] title read failed: {e}")
        return path.stem

    def apply_random_title_style(self, title: str):
        if title == self.current_title_style_key:
            return
        self.current_title_style_key = title
        self.current_title_color = random.choice(self.title_color_palette) if title and title != T("ここに音声ファイルをDrop") else "#ffffff"
        try:
            self.apply_title_label_style()
        except Exception as e:
            app_log(f"Title style update failed: {e}")

    def update_current_title_labels(self):
        path = self.current_media_path()
        title = self.get_display_title(path) if path else T("ここに音声ファイルをDrop")
        self.apply_random_title_style(title)
        self.title_label.setText(title)
        self.art_title_label.setText(title)
        self.one_shot_name_label.setText(title)
        app_title = f"DropMp3 {format_version_label(self.current_app_version)}"
        self.setWindowTitle(f"{app_title} - {title}" if path else app_title)
        if self.tray_icon is not None:
            self.tray_icon.setToolTip(self.build_tray_tooltip())

    def update_random_art_pool(self):
        current = self.current_media_path()
        self.random_art_paths = [p for p in self.playlist if p.exists() and p != current]

    def stop_random_art_mode(self, hide_notice: bool = True):
        self.random_art_delay_timer.stop()
        self.random_art_timer.stop()
        self.random_art_mode = False
        self.random_art_delay_paused = False
        self.random_art_timer_paused = False
        if hide_notice:
            self.random_art_notice_label.hide()

    def prepare_random_art_for_current_track(self, has_original_art: bool):
        T("""RandomチェックONなら、元画像を約20秒見せたあとランダム画像へ切替。

        元画像が無い曲は、従来どおり可能なら即ランダム画像を表示する。
        """)
        self.stop_random_art_mode(hide_notice=True)
        self.update_random_art_pool()
        if not self.random_art_enabled:
            return
        if not self.random_art_paths:
            return
        if has_original_art:
            app_log("Random art scheduled after original intro: 20 sec")
            self.random_art_delay_timer.start(20000)
        else:
            app_log("No original album art: random art starts immediately")
            self.start_random_art_mode()

    def start_random_art_mode(self):
        if not self.random_art_enabled:
            self.stop_random_art_mode(hide_notice=True)
            self.restore_original_album_art()
            return
        self.update_random_art_pool()
        if not self.random_art_paths:
            self.stop_random_art_mode(hide_notice=True)
            return
        self.random_art_mode = True
        self.random_art_notice_label.show()
        self.position_random_art_notice()
        self.show_random_playlist_art()
        if self.random_art_mode:
            self.random_art_timer.start(20000)

    def show_random_playlist_art(self):
        if not self.random_art_enabled:
            self.stop_random_art_mode(hide_notice=True)
            self.restore_original_album_art()
            return
        if not self.random_art_paths:
            self.stop_random_art_mode(hide_notice=True)
            return
        candidates = self.random_art_paths[:]
        random.shuffle(candidates)
        for path in candidates:
            image_data = self.extract_album_art(path)
            if not image_data:
                continue
            pixmap = QPixmap()
            if pixmap.loadFromData(image_data) and not pixmap.isNull():
                self.art_source_pixmap = pixmap
                self.art_label.setText("")
                self.set_art_pixmap()
                self.random_art_mode = True
                self.random_art_notice_label.show()
                self.position_random_art_notice()
                return
        self.stop_random_art_mode(hide_notice=True)

    def restore_original_album_art(self):
        if not self.original_art_pixmap.isNull():
            self.art_source_pixmap = self.original_art_pixmap
            self.art_label.setText("")
            self.set_art_pixmap()
        else:
            self.art_source_pixmap = QPixmap()
            self.art_label.setPixmap(QPixmap())
            self.art_label.setText("Album Art")

    def position_random_art_notice(self):
        if not hasattr(self, "random_art_notice_label"):
            return
        self.random_art_notice_label.adjustSize()
        x = max(0, int((self.art_stack.width() - self.random_art_notice_label.width()) / 2))
        y = 18
        self.random_art_notice_label.move(x, y)

    def pause_random_art_timers_for_playback_pause(self):
        T("""音楽の一時停止中は、ランダム画像の自動切替も止める。""")
        self.random_art_delay_paused = self.random_art_delay_timer.isActive()
        self.random_art_timer_paused = self.random_art_timer.isActive()
        if self.random_art_delay_paused:
            self.random_art_delay_timer.stop()
            app_log("Random art delay paused because playback paused")
        if self.random_art_timer_paused:
            self.random_art_timer.stop()
            app_log("Random art timer paused because playback paused")

    def resume_random_art_timers_for_playback_play(self):
        T("""再生再開時に、停止していたランダム画像の自動切替を再開する。""")
        if not self.random_art_enabled:
            self.random_art_delay_paused = False
            self.random_art_timer_paused = False
            return
        self.update_random_art_pool()
        if not self.random_art_paths:
            self.random_art_delay_paused = False
            self.random_art_timer_paused = False
            return
        if self.random_art_mode:
            if not self.random_art_timer.isActive():
                self.random_art_timer.start(20000)
                app_log("Random art timer resumed")
        elif self.random_art_delay_paused:
            # 一時停止前に「曲冒頭20秒の元画像表示待ち」だった場合は、再生再開後に改めて20秒待つ。
            self.random_art_delay_timer.start(20000)
            app_log("Random art delay resumed: 20 sec")
        self.random_art_delay_paused = False
        self.random_art_timer_paused = False

    def update_random_art_button_style(self):
        if not hasattr(self, "random_check"):
            return
        active = bool(getattr(self, "random_art_enabled", False))
        border = "#58a6ff" if active else "#666666"
        background = "#1e3147" if active else "#2b2b2b"
        color = "#ffffff" if active else "#cfcfcf"
        self.random_check.setStyleSheet(f"""
            QPushButton {{
                background-color:{background}; color:{color}; border:2px solid {border};
                border-radius:21px; font-size:19px; min-width:42px; min-height:42px;
            }}
            QPushButton:hover {{ background-color:#353535; border-color:#66a8ff; }}
        """)

    def on_random_art_check_toggled(self, checked: bool):
        self.random_art_enabled = bool(checked)
        self.update_random_art_button_style()
        app_log(f"Random art enabled: {self.random_art_enabled}")
        if not self.random_art_enabled:
            self.stop_random_art_mode(hide_notice=True)
            self.restore_original_album_art()
        else:
            # ONに戻した場合は、現在位置に関係なく20秒待たずにランダムへ入る。
            # 曲開始時はprepare_random_art_for_current_track側で20秒待つ。
            self.start_random_art_mode()
        self.save_settings()

    def load_album_art(self, path: Path):
        image_data = self.extract_album_art(path)
        if not image_data:
            self.original_art_pixmap = QPixmap()
            self.art_source_pixmap = QPixmap()
            self.art_label.setPixmap(QPixmap())
            self.art_label.setText("Album Art")
            return False
        pixmap = QPixmap()
        ok = pixmap.loadFromData(image_data)
        if not ok or pixmap.isNull():
            self.original_art_pixmap = QPixmap()
            self.art_source_pixmap = QPixmap()
            self.art_label.setPixmap(QPixmap())
            self.art_label.setText("Album Art")
            return False
        self.original_art_pixmap = pixmap
        self.art_source_pixmap = pixmap
        self.art_label.setText("")
        self.set_art_pixmap()
        return True

    def extract_album_art(self, path: Path):
        try:
            audio = MutagenFile(str(path))
            if audio is None:
                return None
            if hasattr(audio, "tags") and audio.tags:
                for key in audio.tags.keys():
                    if str(key).startswith("APIC"):
                        return audio.tags[key].data
            if hasattr(audio, "pictures") and audio.pictures:
                return audio.pictures[0].data
            if audio.tags and "covr" in audio.tags:
                covers = audio.tags["covr"]
                if covers:
                    return bytes(covers[0])
        except Exception as e:
            app_log(f"[TAG] album art read failed: {e}")
        return None

    def set_art_pixmap(self):
        if self.art_source_pixmap.isNull():
            return
        target = self.art_label.size()
        if target.width() <= 0 or target.height() <= 0:
            return
        scaled = self.art_source_pixmap.scaled(target, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.art_label.setText("")
        self.art_label.setPixmap(scaled)

    def app_base_dir(self) -> Path:
        T("""EXE配布時はEXEのある場所、Python実行時はスクリプトのある場所を返す。""")
        try:
            if getattr(sys, "frozen", False):
                return Path(sys.executable).resolve().parent
        except Exception:
            pass
        try:
            return Path(__file__).resolve().parent
        except Exception:
            return Path.cwd()

    def release_page_url(self) -> str:
        return f"https://github.com/{APP_GITHUB_REPO}/releases/latest"

    def schedule_startup_update_check(self):
        if not getattr(sys, "frozen", False):
            return
        self.check_for_app_update(silent=True, manual=False)

    def check_for_app_update(self, silent: bool = False, manual: bool = True):
        if self.update_check_in_progress:
            if manual:
                QMessageBox.information(self, T("更新確認"), T("更新確認を実行中です。"))
            return

        self.update_check_in_progress = True

        def worker():
            try:
                release = fetch_latest_release_metadata()
                asset = select_release_asset(release)
                latest_version = normalize_version_text(
                    str(release.get("tag_name") or release.get("name") or "").strip()
                )
                payload = {
                    "silent": bool(silent),
                    "manual": bool(manual),
                    "current_version": self.current_app_version,
                    "latest_version": latest_version,
                    "release_url": str(release.get("html_url", "") or self.release_page_url()),
                    "asset": asset,
                    "release": release,
                    "has_update": bool(latest_version) and version_sort_key(latest_version) > version_sort_key(self.current_app_version),
                }
                self.update_bridge.checkFinished.emit(payload)
            except Exception as exc:
                self.update_bridge.updateError.emit(
                    {
                        "title": T("更新確認"),
                        "message": T("更新確認に失敗しました。\n\n") + str(exc),
                        "silent": bool(silent),
                    }
                )

        threading.Thread(target=worker, daemon=True).start()

    def on_update_check_finished(self, payload: dict):
        self.update_check_in_progress = False
        latest_version = str(payload.get("latest_version", "") or "").strip()
        manual = bool(payload.get("manual"))
        silent = bool(payload.get("silent"))
        if not latest_version:
            if manual and not silent:
                QMessageBox.information(self, T("更新確認"), T("最新版を確認できませんでした。"))
            return
        if not payload.get("has_update"):
            if manual and not silent:
                QMessageBox.information(self, T("更新確認"), T("最新版です。"))
            return

        release_url = str(payload.get("release_url", "") or self.release_page_url())
        current_version = str(payload.get("current_version", self.current_app_version) or self.current_app_version)
        text = (
            T("最新版があります。\n\n現在: ")
            + current_version
            + T("\n最新版: ")
            + latest_version
            + T("\n\n今すぐダウンロードして更新しますか？")
        )

        if not getattr(sys, "frozen", False):
            answer = QMessageBox.question(
                self,
                T("更新"),
                text + "\n\n" + T("この実行形態では自動更新できません。Release ページを開きますか？"),
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.Yes,
            )
            if answer == QMessageBox.Yes:
                QDesktopServices.openUrl(QUrl(release_url))
            return

        if payload.get("asset") is None:
            answer = QMessageBox.question(
                self,
                T("更新"),
                text + "\n\n" + T("配布アセットが見つかりませんでした。"),
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.Yes,
            )
            if answer == QMessageBox.Yes:
                QDesktopServices.openUrl(QUrl(release_url))
            return

        answer = QMessageBox.question(
            self,
            T("更新"),
            text,
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes,
        )
        if answer == QMessageBox.Yes:
            self.download_release_update(payload)

    def download_release_update(self, payload: dict):
        if self.update_download_in_progress:
            QMessageBox.information(self, T("更新"), T("ダウンロード中..."))
            return

        asset = payload.get("asset") or {}
        url = str(asset.get("browser_download_url", "") or "")
        name = str(asset.get("name", "") or "dropmp3_update.zip")
        if not url:
            QMessageBox.warning(self, T("ダウンロード失敗"), T("配布アセットが見つかりませんでした。"))
            return

        self.update_download_in_progress = True
        self.update_download_context = dict(payload)
        self.update_progress_dialog = QProgressDialog(T("ダウンロード中..."), T("中止"), 0, 100, self)
        self.update_progress_dialog.setWindowTitle(T("更新"))
        self.update_progress_dialog.setAutoClose(False)
        self.update_progress_dialog.setAutoReset(False)
        self.update_progress_dialog.setMinimumDuration(0)
        self.update_progress_dialog.setValue(0)
        self.update_progress_dialog.setCancelButton(None)
        self.update_progress_dialog.show()

        def worker():
            temp_dir = Path(tempfile.mkdtemp(prefix="dropmp3_update_"))
            target_path = temp_dir / name
            digest_value = str(asset.get("digest", "") or "").strip()
            expected_sha256 = ""
            if digest_value.lower().startswith("sha256:"):
                expected_sha256 = digest_value.split(":", 1)[1].strip().lower()
            try:
                req = urllib.request.Request(
                    url,
                    headers={
                        "User-Agent": f"{APP_NAME}-updater",
                        "Accept": "application/octet-stream",
                    },
                )
                sha256 = hashlib.sha256()
                with urllib.request.urlopen(req, timeout=APP_UPDATE_TIMEOUT_SEC) as resp, target_path.open("wb") as out_file:
                    total = int(resp.headers.get("Content-Length") or 0)
                    downloaded = 0
                    while True:
                        chunk = resp.read(1024 * 1024)
                        if not chunk:
                            break
                        out_file.write(chunk)
                        sha256.update(chunk)
                        downloaded += len(chunk)
                        percent = int(downloaded * 100 / total) if total > 0 else 0
                        self.update_bridge.progressChanged.emit(percent, f"{downloaded}/{total}" if total > 0 else str(downloaded))
                if expected_sha256 and sha256.hexdigest().lower() != expected_sha256:
                    raise RuntimeError("SHA-256 mismatch")
                result = dict(payload)
                result["download_path"] = str(target_path)
                self.update_bridge.downloadFinished.emit(result)
            except Exception as exc:
                self.update_bridge.updateError.emit(
                    {
                        "title": T("ダウンロード失敗"),
                        "message": str(exc),
                        "silent": False,
                    }
                )

        threading.Thread(target=worker, daemon=True).start()

    def on_update_download_progress(self, percent: int, detail: str):
        dialog = self.update_progress_dialog
        if dialog is None:
            return
        dialog.setLabelText(f"{T('ダウンロード中...')}\n{detail}")
        if percent > 0:
            dialog.setValue(max(0, min(100, int(percent))))

    def on_update_download_finished(self, payload: dict):
        self.update_download_in_progress = False
        dialog = self.update_progress_dialog
        self.update_progress_dialog = None
        if dialog is not None:
            dialog.setValue(100)
            dialog.close()
        self.update_download_context = dict(payload)

        message = (
            T("更新用ファイルのダウンロードが完了しました。\n\n今すぐアプリを終了して更新を適用しますか？")
            + "\n\n"
            + T("起動中の EXE を置き換えるため、アプリを一度終了してから更新します。設定とプレイリストは保持します。")
        )
        answer = QMessageBox.question(
            self,
            T("ダウンロード完了"),
            message,
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes,
        )
        if answer == QMessageBox.Yes:
            self.launch_downloaded_update(payload)

    def on_update_error(self, payload: dict):
        self.update_check_in_progress = False
        self.update_download_in_progress = False
        dialog = self.update_progress_dialog
        self.update_progress_dialog = None
        if dialog is not None:
            dialog.close()
        if payload.get("silent"):
            app_log(f"[UPDATE] {payload.get('title', 'error')}: {payload.get('message', '')}")
            return
        QMessageBox.warning(self, str(payload.get("title", "") or T("更新エラー")), str(payload.get("message", "") or ""))

    def launch_downloaded_update(self, payload: dict):
        if not getattr(sys, "frozen", False):
            QMessageBox.information(self, T("更新"), T("この実行形態では自動更新できません。Release ページを開きますか？"))
            return
        download_path = Path(str(payload.get("download_path", "") or ""))
        if not download_path.exists():
            QMessageBox.warning(self, T("更新エラー"), T("更新を開始できませんでした。\n\n") + str(download_path))
            return

        script_path = download_path.with_suffix(".ps1")
        app_dir = self.app_base_dir()
        exe_path = Path(sys.executable).resolve()
        script_text = f"""$ErrorActionPreference = 'Stop'
$zipPath = {str(download_path)!r}
$appDir = {str(app_dir)!r}
$exePath = {str(exe_path)!r}
$parentPid = {int(os.getpid())}
for ($i = 0; $i -lt 600; $i++) {{
    $proc = Get-Process -Id $parentPid -ErrorAction SilentlyContinue
    if (-not $proc) {{ break }}
    Start-Sleep -Milliseconds 500
}}
$extractRoot = Join-Path ([System.IO.Path]::GetDirectoryName($zipPath)) ('dropmp3_apply_' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Force -Path $extractRoot | Out-Null
Expand-Archive -LiteralPath $zipPath -DestinationPath $extractRoot -Force
$payloadRoot = $extractRoot
$exeCandidate = Get-ChildItem -LiteralPath $extractRoot -Filter 'DropMP3.exe' -File -Recurse | Select-Object -First 1
if ($exeCandidate) {{ $payloadRoot = $exeCandidate.Directory.FullName }}
Get-ChildItem -LiteralPath $payloadRoot -Force -Recurse | ForEach-Object {{
    $relative = [System.IO.Path]::GetRelativePath($payloadRoot, $_.FullName)
    if ([string]::IsNullOrWhiteSpace($relative)) {{ return }}
    if ($relative -ieq '_conf\\DropMp3.ini') {{ return }}
    if ($relative -like '_conf\\lst*') {{ return }}
    if ($relative -like '_conf\\srt*') {{ return }}
    $destination = Join-Path $appDir $relative
    if ($_.PSIsContainer) {{
        New-Item -ItemType Directory -Force -Path $destination | Out-Null
    }} else {{
        $destDir = Split-Path -Parent $destination
        if ($destDir) {{ New-Item -ItemType Directory -Force -Path $destDir | Out-Null }}
        Copy-Item -LiteralPath $_.FullName -Destination $destination -Force
    }}
}}
Start-Sleep -Milliseconds 300
Start-Process -FilePath $exePath
"""
        try:
            script_path.write_text(script_text, encoding="utf-8")
            ok = QProcess.startDetached(
                "powershell.exe",
                [
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(script_path),
                ],
            )
            if not ok:
                raise RuntimeError("startDetached failed")
            self.shutdown_remote_control()
            self.save_settings()
            QApplication.quit()
        except Exception as exc:
            QMessageBox.warning(self, T("更新エラー"), T("更新を開始できませんでした。\n\n") + str(exc))

    def subtitle_file_candidates(self, path: Path, suffix: str) -> list[Path]:
        path = Path(path)
        app_dir = self.app_base_dir()
        conf_srt = app_dir / "_conf" / "srt"
        candidates = [
            path.with_suffix(suffix),
            path.parent / "srt" / f"{path.stem}{suffix}",
            path.parent / "SRT" / f"{path.stem}{suffix}",
            app_dir / "srt" / f"{path.stem}{suffix}",
            app_dir / "SRT" / f"{path.stem}{suffix}",
            conf_srt / f"{path.stem}{suffix}",
        ]
        unique: list[Path] = []
        seen = set()
        for c in candidates:
            try:
                key = str(c.resolve()).lower()
            except Exception:
                key = str(c).lower()
            if key not in seen:
                unique.append(c)
                seen.add(key)
        return unique

    def find_subtitle_variant_for(self, path: Path, suffix: str) -> Path | None:
        for c in self.subtitle_file_candidates(path, suffix):
            try:
                c = c.resolve()
            except Exception:
                pass
            if c.exists() and c.is_file():
                return c
        return None

    def find_srt_for(self, path: Path) -> Path | None:
        return self.find_subtitle_variant_for(path, ".srt")

    def find_srt2_for(self, path: Path) -> Path | None:
        return self.find_subtitle_variant_for(path, ".srt2")

    def read_text_file_flexible(self, file_path: Path) -> str:
        data = Path(file_path).read_bytes()
        for enc in ("utf-8-sig", "utf-8", "cp932", "shift_jis"):
            try:
                return data.decode(enc)
            except Exception:
                pass
        return data.decode("utf-8", errors="replace")

    def subtitle_candidates_for_media(self, path: Path) -> list[Path]:
        candidates = self.subtitle_file_candidates(path, ".srt") + self.subtitle_file_candidates(path, ".srt2")
        unique: list[Path] = []
        seen = set()
        for c in candidates:
            try:
                key = str(c.resolve()).lower()
            except Exception:
                key = str(c).lower()
            if key not in seen:
                unique.append(c)
                seen.add(key)
        return unique

    def open_subtitle_file_in_notepad(self, media_path: Path):
        path = Path(media_path)
        srt_path = self.find_srt_for(path)
        if not srt_path:
            QMessageBox.information(
                self,
                T("字幕確認"),
                T("字幕ファイルは見つかりませんでした。\n\n") + f"{path.stem}.srt",
            )
            app_log(f"Subtitle check skipped: no SRT for {path.name}")
            return
        try:
            subprocess.Popen(["notepad.exe", str(srt_path)])
            app_log(f"Open SRT in Notepad: {srt_path}")
        except Exception as e:
            QMessageBox.warning(
                self,
                T("メモ帳起動失敗"),
                T("メモ帳でSRTを開けませんでした。\n\n") + f"{srt_path}\n\n{e}",
            )
            app_log(f"Open SRT failed: {e}")

    def delete_subtitle_files(self, media_path: Path):
        path = Path(media_path)
        existing = [p for p in self.subtitle_candidates_for_media(path) if p.exists() and p.is_file()]
        if not existing:
            QMessageBox.information(self, T("字幕削除"), f"字幕ファイルは見つかりませんでした。\n\n{path.stem}.srt")
            app_log(f"Subtitle delete skipped: no SRT for {path.name}")
            return

        lines = "\n".join(str(p) for p in existing)
        reply = QMessageBox.question(
            self,
            T("字幕削除"),
            T("次の字幕ファイルを削除しますか？\n\n") + lines,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            app_log(f"Subtitle delete canceled: {path.name}")
            return

        deleted = []
        failed = []
        for srt_path in existing:
            try:
                srt_path.unlink()
                deleted.append(str(srt_path))
            except Exception as exc:
                failed.append(f"{srt_path}\n  {exc}")

        try:
            current = self.current_media_path()
        except Exception:
            current = None
        if current and Path(current) == path:
            self.subtitle_primary_cues = []
            self.subtitle_secondary_cues = []
            self.subtitle_cues = []
            self.subtitle_display_mode = 0
            self.subtitles_manually_hidden = False
            self.subtitle_overlay.set_cues([])
            self.update_subtitle_controls()

        if failed:
            QMessageBox.warning(
                self,
                T("字幕削除"),
                T("一部の字幕ファイルを削除できませんでした。\n\n削除済み:\n")
                + ("\n".join(deleted) if deleted else T("なし"))
                + T("\n\n失敗:\n")
                + "\n".join(failed),
            )
        else:
            QMessageBox.information(self, T("字幕削除"), T("字幕ファイルを削除しました。"))
        app_log(f"Subtitle deleted for {path.name}: {len(deleted)} file(s)")

    def load_subtitles_for(self, path: Path):
        srt_path = self.find_srt_for(path)
        srt2_path = self.find_srt2_for(path)
        if not srt_path and not srt2_path:
            app_log(f"SRT not found for: {path.name}")
            self.subtitle_primary_cues = []
            self.subtitle_secondary_cues = []
            self.subtitle_cues = []
            self.subtitle_display_mode = 0
            self.subtitles_manually_hidden = False
            self.subtitle_overlay.set_cues([])
            self.update_subtitle_controls()
            return
        try:
            self.subtitle_primary_cues = parse_srt(srt_path) if srt_path else []
            self.subtitle_secondary_cues = parse_srt(srt2_path) if srt2_path else []
            modes = self.subtitle_available_modes()
            if self.subtitle_auto_show_enabled and modes:
                if self.subtitle_display_mode not in modes:
                    self.subtitle_display_mode = modes[0]
                self.subtitles_manually_hidden = False
            else:
                self.subtitle_display_mode = 0
                self.subtitles_manually_hidden = True
            self.apply_active_subtitle_mode()
            self.update_subtitle_controls()
            app_log(
                f"SRT loaded: primary={srt_path if srt_path else 'none'} ({len(self.subtitle_primary_cues)} cues), "
                f"secondary={srt2_path if srt2_path else 'none'} ({len(self.subtitle_secondary_cues)} cues)"
            )
        except Exception as e:
            app_log(f"[SRT ERROR] {srt_path or srt2_path}: {e}")
            self.subtitle_primary_cues = []
            self.subtitle_secondary_cues = []
            self.subtitle_cues = []
            self.subtitle_display_mode = 0
            self.subtitles_manually_hidden = False
            self.subtitle_overlay.set_cues([])
            self.update_subtitle_controls()

    def subtitle_available_modes(self) -> list[int]:
        modes: list[int] = []
        if self.subtitle_primary_cues:
            modes.append(1)
        if self.subtitle_secondary_cues:
            modes.append(2)
        return modes

    def subtitle_mode_tooltip(self) -> str:
        modes = self.subtitle_available_modes()
        if not modes:
            return T("字幕ファイルがありません")
        if modes == [1]:
            return T("字幕表示: .srt を表示 / 非表示")
        if modes == [2]:
            return T("字幕表示: .srt2 を表示 / 非表示")
        return T("字幕表示: オフ → .srt → .srt2 を切り替えます")

    def set_subtitle_auto_show_enabled(self, checked: bool):
        self.subtitle_auto_show_enabled = bool(checked)
        app_log(f"Subtitle auto show: {'ON' if self.subtitle_auto_show_enabled else 'OFF'}")
        current = self.current_media_path()
        if current is not None and (self.subtitle_primary_cues or self.subtitle_secondary_cues):
            modes = self.subtitle_available_modes()
            if self.subtitle_auto_show_enabled and modes:
                self.subtitle_display_mode = modes[0]
                self.subtitles_manually_hidden = False
            else:
                self.subtitle_display_mode = 0
                self.subtitles_manually_hidden = True
            self.apply_active_subtitle_mode()
            self.subtitle_overlay.update_position(self.player.position())
            self.update_subtitle_controls()
        self.save_settings()

    def apply_active_subtitle_mode(self):
        mode = self.subtitle_display_mode
        cues: list[tuple[int, int, str]] = []
        if mode == 1:
            cues = self.subtitle_primary_cues
        elif mode == 2:
            cues = self.subtitle_secondary_cues
        if self.subtitle_cues is not cues:
            self.subtitle_cues = cues
            self.subtitle_overlay.set_cues(cues)
        if mode == 0 or self.subtitles_manually_hidden or not cues:
            self.subtitle_overlay.hide()

    def set_subtitle_toggle_button_style(self, mode: int, enabled: bool):
        border = "#666666"
        text_color = "#ffffff" if enabled else "#777777"
        background = "#2b2b2b"
        if enabled and mode == 1:
            border = "#58a6ff"
            background = "#1e3147"
        elif enabled and mode == 2:
            border = "#36c96b"
            background = "#193624"
        if not enabled:
            background = "#202020"
        self.subtitle_toggle_button.setStyleSheet(f"""
            QPushButton {{
                border: 2px solid {border};
                border-radius: 21px;
                background: {background};
                color: {text_color};
                font-size: 18px;
                min-width:42px;
                min-height:42px;
            }}
            QPushButton:hover {{ background: #353535; }}
        """)

    def estimate_subtitle_box_height(self) -> int:
        if not self.subtitle_cues or self.subtitle_overlay.current_index < 0:
            return 0
        # SubtitleOverlay は最大5行、12pt太字、余白つきで描画している。
        font = QFont(self.font())
        font.setPointSize(12)
        font.setBold(True)
        metrics = QFontMetrics(font)
        line_h = metrics.height() + 5
        return line_h * 5 + 12

    def update_subtitle_controls(self):
        if not hasattr(self, "subtitle_overlay"):
            return
        has_any = bool(self.subtitle_primary_cues or self.subtitle_secondary_cues)
        self.apply_active_subtitle_mode()
        has_srt = bool(self.subtitle_cues)
        has_current = has_srt and self.subtitle_overlay.current_index >= 0
        should_show_panel = has_srt and not self.subtitles_manually_hidden and self.subtitle_display_mode != 0

        if hasattr(self, "subtitle_toggle_button"):
            self.subtitle_toggle_button.blockSignals(True)
            self.subtitle_toggle_button.setEnabled(has_any)
            self.subtitle_toggle_button.setChecked(bool(self.subtitle_display_mode and not self.subtitles_manually_hidden and has_srt))
            self.subtitle_toggle_button.blockSignals(False)
            self.set_subtitle_toggle_button_style(self.subtitle_display_mode if not self.subtitles_manually_hidden else 0, has_any)
            self.subtitle_toggle_button.setToolTip(self.subtitle_mode_tooltip())

        if not hasattr(self, "subtitle_close_button"):
            return
        self.subtitle_close_button.hide()
        self.subtitle_open_button.hide()

        if not has_any:
            self.subtitle_overlay.hide()
            return

        if self.subtitles_manually_hidden:
            self.subtitle_overlay.hide()
        else:
            self.subtitle_overlay.setVisible(should_show_panel and has_current)

    def hide_subtitle_panel(self):
        if not self.subtitle_primary_cues and not self.subtitle_secondary_cues:
            return
        app_log("Subtitle panel hidden")
        self.subtitles_manually_hidden = True
        self.subtitle_display_mode = 0
        self.subtitle_overlay.hide()
        self.update_subtitle_controls()

    def show_subtitle_panel(self):
        modes = self.subtitle_available_modes()
        if not modes:
            return
        app_log("Subtitle panel shown")
        if self.subtitle_display_mode not in modes:
            self.subtitle_display_mode = modes[0]
        self.subtitles_manually_hidden = False
        self.apply_active_subtitle_mode()
        self.subtitle_overlay.update_position(self.player.position())
        self.update_subtitle_controls()

    def toggle_subtitle_panel_from_header(self):
        modes = self.subtitle_available_modes()
        if not modes:
            return
        current = 0 if self.subtitles_manually_hidden else self.subtitle_display_mode
        cycle = [0] + modes
        try:
            idx = cycle.index(current)
        except ValueError:
            idx = 0
        next_mode = cycle[(idx + 1) % len(cycle)]
        if next_mode == 0:
            self.hide_subtitle_panel()
            return
        self.subtitle_display_mode = next_mode
        self.subtitles_manually_hidden = False
        self.apply_active_subtitle_mode()
        self.subtitle_overlay.update_position(self.player.position())
        self.update_subtitle_controls()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.set_art_pixmap()
        self.update_left_panel_visibility()
        self.update_subtitle_controls()
        self.position_random_art_notice()

    def update_left_panel_visibility(self):
        if self.is_art_only_mode or self.is_one_shot_panel_mode:
            self.left_panel.hide()
            if hasattr(self, "drawer_rail"):
                self.drawer_rail.hide()
            self.left_playlist_visible = False
            return

        has_playlist = bool(self.playlist)
        if hasattr(self, "drawer_rail"):
            self.drawer_rail.setVisible(has_playlist)

        # ドロワーは明示的に開いた時だけ左リストを表示する。
        # これにより、横幅が広い時でも「左に開ける場所」が常に分かる。
        should_show = bool(self.drawer_open and has_playlist)
        was_visible = self.left_playlist_visible
        self.left_panel.setVisible(should_show)
        self.left_playlist_visible = should_show
        self.header_widget.setVisible(not self.is_art_only_mode and not self.is_one_shot_panel_mode)
        if hasattr(self, "drawer_button"):
            self.drawer_button.setText("‹" if should_show else "☰")
            self.drawer_button.setToolTip(T("再生リストを閉じる") if should_show else T("再生リストを開く"))
        if should_show:
            self.restore_main_splitter_sizes_later()
        self.update_playlist_panel()

    def toggle_playlist_drawer(self):
        self.drawer_open = not bool(self.drawer_open)
        app_log(f"Playlist drawer: {'OPEN' if self.drawer_open else 'CLOSED'}")
        self.update_left_panel_visibility()
        self.save_settings()

    def close_playlist_drawer(self):
        self.drawer_open = False
        app_log("Playlist drawer: CLOSED")
        self.update_left_panel_visibility()
        self.save_settings()

    def on_art_clicked(self):
        self.toggle_play()

    def update_volume_label(self):
        if hasattr(self, "volume_label"):
            percent = int(round(float(self.audio.volume()) * 100))
            self.volume_label.setText(f"{T('音量 ')}{percent}%")

    def apply_title_label_style(self):
        if not hasattr(self, "title_label"):
            return
        self.title_label.setTextColor(self.current_title_color)
        self.title_label.setStyleSheet(
            f"color: {self.current_title_color}; "
            f"font-family: {self.title_font_families}; "
            f"font-size: {self.title_font_size}px; "
            "font-weight: 900; letter-spacing: 0.4px;"
        )
        self.title_label.setFixedHeight(max(44, int(self.title_font_size * 1.55)))

    def apply_left_panel_style(self):
        if not hasattr(self, "left_panel"):
            return
        self.left_panel.setStyleSheet(f"""
            QFrame {{ background:#111; border-right:1px solid #333; }}
            QLabel {{ color:#ffb36a; font-size:12px; }}
            QListWidget {{
                background:#111; border:0; outline:none; font-size:{self.playlist_font_size}px;
            }}
            QListWidget::item {{ padding:5px 7px; border-bottom:1px solid #242424; }}
            QListWidget::item:selected {{ background:#3a2a18; color:#ff9b45; }}
            QListWidget::item:hover {{ background:#252525; }}
        """)

    def change_playlist_font_size_by_wheel(self, delta: int, event=None):
        step_count = int(delta / 120) if abs(delta) >= 120 else (1 if delta > 0 else -1)
        self.playlist_font_size = max(8, min(28, int(self.playlist_font_size) + step_count))
        self.apply_left_panel_style()
        if event is not None and hasattr(event, "globalPosition"):
            tip_pos = event.globalPosition().toPoint() + QPoint(22, 0)
        else:
            tip_pos = self.left_list.mapToGlobal(QPoint(16, 16))
        QToolTip.showText(tip_pos, f"リスト文字サイズ {self.playlist_font_size}px", self.left_list)
        app_log(f"Playlist font size changed by wheel: {self.playlist_font_size}px")
        self.save_settings()

    def change_volume_font_size_by_wheel(self, delta: int, event=None):
        step_count = int(delta / 120) if abs(delta) >= 120 else (1 if delta > 0 else -1)
        self.volume_font_size = max(8, min(28, int(self.volume_font_size) + step_count))
        self.volume_label.set_display_font_size(self.volume_font_size)
        if event is not None and hasattr(event, "globalPosition"):
            tip_pos = event.globalPosition().toPoint() + QPoint(22, 0)
        else:
            tip_pos = self.volume_label.mapToGlobal(QPoint(self.volume_label.width() + 8, int(self.volume_label.height() / 2)))
        QToolTip.showText(tip_pos, f"音量文字サイズ {self.volume_font_size}px", self.volume_label)
        app_log(f"Volume label font size changed by wheel: {self.volume_font_size}px")
        self.save_settings()

    def change_time_font_size_by_wheel(self, delta: int, event=None, owner=None):
        step_count = int(delta / 120) if abs(delta) >= 120 else (1 if delta > 0 else -1)
        self.time_font_size = max(8, min(28, int(self.time_font_size) + step_count))
        for label in (self.current_time_label, self.total_time_label):
            label.set_display_font_size(self.time_font_size)
        widget = owner or self.current_time_label
        if event is not None and hasattr(event, "globalPosition"):
            tip_pos = event.globalPosition().toPoint() + QPoint(22, 0)
        else:
            tip_pos = widget.mapToGlobal(QPoint(widget.width() + 8, int(widget.height() / 2)))
        QToolTip.showText(tip_pos, f"時間文字サイズ {self.time_font_size}px", widget)
        app_log(f"Time label font size changed by wheel: {self.time_font_size}px")
        self.save_settings()

    def change_title_font_size_by_wheel(self, delta: int, event=None):
        step_count = int(delta / 120) if abs(delta) >= 120 else (1 if delta > 0 else -1)
        self.title_font_size = max(16, min(72, int(self.title_font_size) + step_count))
        self.apply_title_label_style()
        if event is not None and hasattr(event, "globalPosition"):
            tip_pos = event.globalPosition().toPoint() + QPoint(22, 0)
        else:
            tip_pos = self.title_label.mapToGlobal(QPoint(self.title_label.width() + 8, int(self.title_label.height() / 2)))
        QToolTip.showText(tip_pos, f"タイトル文字サイズ {self.title_font_size}px", self.title_label)
        app_log(f"Title font size changed by wheel: {self.title_font_size}px")
        self.save_settings()

    def apply_control_icon_scale(self):
        scale = max(0.7, min(2.5, float(self.control_icon_scale)))
        self.control_icon_scale = scale

        prev_next_size = max(40, int(round(63 * scale)))
        prev_next_radius = prev_next_size // 2
        prev_next_font = max(20, int(round(30 * scale)))
        seek_size = max(32, int(round(63 * 0.7 * scale)))
        play_size = max(54, int(round(63 * 1.5 * scale)))
        play_radius = play_size // 2
        play_font = max(26, int(round(30 * 1.5 * scale)))
        small_seek_size = max(18, int(round(30 * scale)))
        small_play_size = max(30, int(round(38 * 1.5 * scale)))
        small_next_size = max(24, int(round(38 * scale)))

        button_style = (
            "QPushButton {"
            "background-color:#2b2b2b; color:white; border:1px solid #555;"
            f"border-radius:{prev_next_radius}px; font-size:{prev_next_font}px;"
            f"min-width:{prev_next_size}px; min-height:{prev_next_size}px;"
            "}"
            "QPushButton:hover { background-color:#3a3a3a; }"
        )
        play_style = (
            "QPushButton {"
            "background-color:#2b2b2b; color:white; border:1px solid #555;"
            f"border-radius:{play_radius}px; font-size:{play_font}px;"
            f"min-width:{play_size}px; min-height:{play_size}px;"
            "}"
            "QPushButton:hover { background-color:#3a3a3a; }"
        )
        small_button_style = (
            "QPushButton {"
            "background-color: rgba(20,20,20,190); color:white; border:1px solid #666;"
            "font-size:20px;"
            "}"
            "QPushButton:hover { background-color:#3a3a3a; color:#ffb36a; border-color:#ff9b45; }"
        )
        small_play_style = (
            "QPushButton {"
            "background-color: rgba(20,20,20,190); color:white; border:1px solid #666;"
            f"border-radius:{small_play_size // 2}px; font-size:{max(18, int(round(24 * scale)))}px;"
            f"min-width:{small_play_size}px; min-height:{small_play_size}px;"
            "}"
            "QPushButton:hover { background-color:#3a3a3a; color:#ffb36a; border-color:#ff9b45; }"
        )

        self.prev_button.setFixedSize(prev_next_size, prev_next_size)
        self.next_button.setFixedSize(prev_next_size, prev_next_size)
        self.prev_button.setStyleSheet(button_style)
        self.next_button.setStyleSheet(button_style)
        self.play_button.setFixedSize(play_size, play_size)
        self.play_button.setStyleSheet(play_style)
        self.seek_back_button.setFixedSize(seek_size, seek_size)
        self.seek_forward_button.setFixedSize(seek_size, seek_size)

        self.small_play_button.setFixedSize(small_play_size, small_play_size)
        self.small_play_button.setStyleSheet(small_play_style)
        self.small_seek_back_button.setFixedSize(small_seek_size, small_seek_size)
        self.small_seek_forward_button.setFixedSize(small_seek_size, small_seek_size)
        self.small_next_button.setFixedSize(small_next_size, small_next_size)
        self.small_next_button.setStyleSheet(
            small_button_style +
            f"QPushButton {{ border-radius:{small_next_size // 2}px; min-width:{small_next_size}px; min-height:{small_next_size}px; }}"
        )

    def change_control_icon_scale_by_wheel(self, delta: int, event=None, owner=None):
        step_count = int(delta / 120) if abs(delta) >= 120 else (1 if delta > 0 else -1)
        self.control_icon_scale = max(0.7, min(2.5, self.control_icon_scale + step_count * 0.1))
        self.apply_control_icon_scale()
        widget = owner or self.play_button
        if event is not None and hasattr(event, "globalPosition"):
            tip_pos = event.globalPosition().toPoint() + QPoint(22, 0)
        else:
            tip_pos = widget.mapToGlobal(QPoint(widget.width() + 8, int(widget.height() / 2)))
        QToolTip.showText(tip_pos, f"操作アイコン倍率 {int(round(self.control_icon_scale * 100))}%", widget)
        app_log(f"Control icon scale changed: {self.control_icon_scale:.2f}")
        self.save_settings()

    def change_volume_by_wheel(self, delta: int, event=None, owner=None):
        step_count = int(delta / 120) if abs(delta) >= 120 else (1 if delta > 0 else -1)
        new_volume = max(0.0, min(1.0, self.audio.volume() + step_count * 0.05))
        self.audio.setVolume(new_volume)
        self.update_volume_label()
        percent = int(round(new_volume * 100))
        if event is not None and hasattr(event, "globalPosition"):
            tip_pos = event.globalPosition().toPoint() + QPoint(22, 0)
        else:
            widget = owner or self.volume_label
            tip_pos = widget.mapToGlobal(QPoint(widget.width() + 8, int(widget.height() / 2)))
        QToolTip.showText(tip_pos, f"{T('音量 ')}{percent}%", owner or self)
        app_log(f"Volume changed by wheel: {percent}%")
        self.save_settings()

    def on_art_wheel_changed(self, delta: int, event):
        self.change_volume_by_wheel(delta, event, self.art_label)

    def on_volume_wheel_changed(self, delta: int, event):
        if event is not None and event.modifiers() & Qt.ControlModifier:
            self.change_volume_font_size_by_wheel(delta, event)
            return
        self.change_volume_by_wheel(delta, event, self.volume_label)

    def on_playlist_font_wheel_changed(self, delta: int, event):
        self.change_playlist_font_size_by_wheel(delta, event)

    def on_title_font_wheel_changed(self, delta: int, event):
        self.change_title_font_size_by_wheel(delta, event)

    def on_time_font_wheel_changed(self, delta: int, event):
        self.change_time_font_size_by_wheel(delta, event, self.sender())

    def eventFilter(self, obj, event):
        if (
            obj in getattr(self, "control_icon_widgets", [])
            and event.type() == QEvent.Type.Wheel
            and event.modifiers() & Qt.ControlModifier
        ):
            delta = event.angleDelta().y()
            if delta:
                self.change_control_icon_scale_by_wheel(delta, event, obj)
                event.accept()
                return True
        return super().eventFilter(obj, event)

    def on_art_double_clicked(self):
        if self.is_one_shot_panel_mode:
            # ワンショットの小型表示は従来通り、ダブルクリックで通常モードへ戻す。
            self.set_one_shot_mode(False)
            return
        if self.is_art_only_mode:
            # 通常ミニプレイヤーのダブルクリックは、元の通常Playerへ戻す。
            self.exit_art_only_mode()
        else:
            self.enter_art_only_mode()

    def on_art_left_pressed(self, event):
        if self.is_art_only_mode or self.is_one_shot_panel_mode:
            self.dragging_small_window = True
            self.drag_start_global = event.globalPosition().toPoint()
            self.drag_start_window_pos = self.pos()

    def on_art_left_moved(self, event):
        if (self.is_art_only_mode or self.is_one_shot_panel_mode) and self.dragging_small_window:
            delta = event.globalPosition().toPoint() - self.drag_start_global
            self.move(self.drag_start_window_pos + delta)

    def on_art_left_released(self, event):
        if self.is_art_only_mode or self.is_one_shot_panel_mode:
            self.dragging_small_window = False
            self.save_settings()

    def hide_normal_controls(self):
        for w in self.normal_control_widgets:
            w.hide()
        self.left_panel.hide()
        if hasattr(self, "drawer_rail"):
            self.drawer_rail.hide()

    def show_normal_controls(self):
        for w in self.normal_control_widgets:
            w.show()
        self.update_left_panel_visibility()

    def hide_one_shot_controls(self):
        for w in self.one_shot_widgets:
            w.hide()

    def show_one_shot_controls(self):
        for w in self.one_shot_widgets:
            w.show()

    def hide_small_controls(self):
        for w in self.small_widgets:
            w.hide()

    def show_small_controls(self, show_next: bool):
        self.art_title_label.show()
        self.small_time_label.show()
        self.small_seek_back_button.show()
        self.small_play_button.show()
        self.small_seek_forward_button.show()
        self.small_next_button.setVisible(show_next)
        self.update_small_time_label()

    def enter_art_only_mode(self):
        if self.is_art_only_mode or self.is_one_shot_panel_mode:
            return
        app_log("Enter art-only mode")
        self.normal_geometry_before_small_mode = self.geometry()
        self.hide_normal_controls()
        self.hide_one_shot_controls()
        self.show_small_controls(show_next=True)
        self.root_layout.setContentsMargins(0, 0, 0, 0)
        self.root_layout.setSpacing(0)
        self.art_stack.setStyleSheet("QFrame{background:#000;border-radius:0px;}")
        self.art_label.setStyleSheet("QLabel{background:#000;border-radius:0px;color:#888;font-size:13px;}")
        self.is_art_only_mode = True
        saved_geo = self.settings.value("art_only_geometry")
        self.hide()
        self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint)
        self.setFixedSize(256, 326)
        if saved_geo:
            self.setGeometry(saved_geo)
            self.setFixedSize(256, 326)
        else:
            self.move(self.normal_geometry_before_small_mode.topLeft())
        self.show()
        self.set_art_pixmap()
        self.save_settings()

    def exit_art_only_mode(self):
        if not self.is_art_only_mode:
            return
        app_log("Exit art-only mode")
        self.settings.setValue("art_only_geometry", self.geometry())
        self.is_art_only_mode = False
        self.hide_small_controls()
        self.show_normal_controls()
        self.root_layout.setContentsMargins(10, 8, 10, 8)
        self.root_layout.setSpacing(8)
        self.art_stack.setStyleSheet("QFrame{background:#202020;border-radius:12px;}")
        self.art_label.setStyleSheet("QLabel{background:#202020;border-radius:12px;color:#888;font-size:13px;}")
        self.hide()
        self.setWindowFlags(Qt.Window)
        self.setMinimumSize(280, 260)
        self.setMaximumSize(16777215, 16777215)
        if self.normal_geometry_before_small_mode:
            self.setGeometry(self.normal_geometry_before_small_mode)
        else:
            self.resize(720, 520)
        self.show()
        self.set_art_pixmap()
        self.save_settings()

    def enter_one_shot_panel_mode(self):
        if self.is_one_shot_panel_mode:
            return
        if self.is_art_only_mode:
            self.exit_art_only_mode()
        app_log("Enter one-shot panel mode")
        self.normal_geometry_before_small_mode = self.geometry()
        self.hide_normal_controls()
        self.show_one_shot_controls()
        self.show_small_controls(show_next=False)
        self.root_layout.setContentsMargins(0, 0, 0, 0)
        self.root_layout.setSpacing(0)
        self.art_stack.setStyleSheet("QFrame{background:#000;border-radius:0px;}")
        self.art_label.setStyleSheet("QLabel{background:#000;border-radius:0px;color:#888;font-size:13px;}")
        self.is_one_shot_panel_mode = True
        saved_geo = self.settings.value("one_shot_geometry")
        self.hide()
        self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint)
        self.setFixedSize(256, 350)
        if saved_geo:
            self.setGeometry(saved_geo)
            self.setFixedSize(256, 350)
        else:
            self.move(self.normal_geometry_before_small_mode.topLeft())
        self.show()
        self.set_art_pixmap()
        self.save_settings()

    def exit_one_shot_panel_mode(self):
        if not self.is_one_shot_panel_mode:
            return
        app_log("Exit one-shot panel mode")
        self.settings.setValue("one_shot_geometry", self.geometry())
        self.is_one_shot_panel_mode = False
        self.hide_one_shot_controls()
        self.hide_small_controls()
        self.show_normal_controls()
        self.root_layout.setContentsMargins(10, 8, 10, 8)
        self.root_layout.setSpacing(8)
        self.art_stack.setStyleSheet("QFrame{background:#202020;border-radius:12px;}")
        self.art_label.setStyleSheet("QLabel{background:#202020;border-radius:12px;color:#888;font-size:13px;}")
        self.hide()
        self.setWindowFlags(Qt.Window)
        self.setMinimumSize(280, 260)
        self.setMaximumSize(16777215, 16777215)
        if self.normal_geometry_before_small_mode:
            self.setGeometry(self.normal_geometry_before_small_mode)
        else:
            self.resize(720, 520)
        self.show()
        self.set_art_pixmap()
        self.save_settings()

    def playlist_toolbar_button_style(self, active: bool = False, repeat_mode: str = "") -> str:
        border_color = "#66a8ff" if active else "#555"
        text_color = "#66a8ff" if active else "#ffffff"
        border_width = 1
        border_style = "solid"
        if repeat_mode == "one":
            border_width = 2
        elif repeat_mode == "all":
            border_width = 3
            border_style = "double"
        return (
            "QPushButton{"
            "background-color:#2b2b2b;"
            f"color:{text_color};"
            f"border:{border_width}px {border_style} {border_color};"
            "border-radius:17px;font-size:16px;min-width:34px;min-height:34px;"
            "}"
            "QPushButton:hover{background-color:#3a3a3a;}"
        )

    def update_playlist_toolbar_buttons(self):
        if not all(hasattr(self, name) for name in ("shuffle_button", "sort_button", "repeat_button")):
            return
        self.shuffle_button.setStyleSheet(self.playlist_toolbar_button_style(self.playlist_order_mode == "shuffle"))
        self.sort_button.setStyleSheet(self.playlist_toolbar_button_style(self.playlist_order_mode == "filename"))
        repeat_mode = getattr(self, "repeat_mode", "off")
        self.repeat_button.setStyleSheet(self.playlist_toolbar_button_style(repeat_mode != "off", repeat_mode))
        if hasattr(self, "search_playlist_button"):
            self.search_playlist_button.setStyleSheet(self.playlist_toolbar_button_style(bool(getattr(self, "playlist_search_text", ""))))

    def set_repeat_current(self, checked: bool):
        # 旧設定/旧メニュー互換: Trueなら1曲リピートとして扱う
        self.repeat_mode = "one" if checked else "off"
        self.update_repeat_button()
        app_log(f"Repeat mode: {self.repeat_mode}")
        self.save_settings()

    def cycle_repeat_mode(self, _checked=False):
        order = ["off", "one", "all"]
        try:
            i = order.index(self.repeat_mode)
        except ValueError:
            i = 0
        self.repeat_mode = order[(i + 1) % len(order)]
        self.update_repeat_button()
        app_log(f"Repeat mode: {self.repeat_mode}")
        self.save_settings()

    def update_repeat_button(self):
        mode = getattr(self, "repeat_mode", "off")
        self.repeat_current = (mode == "one")
        self.repeat_button.blockSignals(True)
        self.repeat_button.setChecked(mode != "off")
        self.repeat_button.blockSignals(False)
        if mode == "one":
            self.repeat_button.setText("🔂")
            self.repeat_button.setToolTip(T("リピート: 1曲\nクリックで全曲リピートに切替"))
        elif mode == "all":
            self.repeat_button.setText("🔁")
            self.repeat_button.setToolTip(T("リピート: 全曲\nクリックでOffに切替"))
        else:
            self.repeat_button.setText("🔁")
            self.repeat_button.setToolTip(T("リピート: Off\nクリックで1曲リピートに切替"))
        self.update_playlist_toolbar_buttons()

    def set_repeat_mode(self, mode: str):
        if mode not in ("off", "one", "all"):
            mode = "off"
        self.repeat_mode = mode
        self.update_repeat_button()
        app_log(f"Repeat mode: {self.repeat_mode}")
        self.save_settings()

    def shuffle_playlist(self):
        if len(self.playlist) <= 1:
            return
        current_path = self.current_media_path()
        random.shuffle(self.playlist)
        if current_path in self.playlist:
            self.current_index = self.playlist.index(current_path)
        self.playlist_order_mode = "shuffle"
        self.update_playlist_toolbar_buttons()
        self.update_playlist_panel()
        self.save_settings()

    def sort_playlist_by_filename(self):
        if len(self.playlist) <= 1:
            return
        if self.playlist_search_text:
            self.clear_playlist_search()
        current_path = self.current_media_path()
        self.playlist.sort(key=lambda p: (p.parent.as_posix().lower(), p.name.lower()))
        if current_path in self.playlist:
            self.current_index = self.playlist.index(current_path)
        self.playlist_order_mode = "filename"
        self.update_playlist_toolbar_buttons()
        self.update_playlist_panel()
        self.save_settings()

    def delete_selected_from_left_playlist(self):
        selected_rows = sorted({
            int(item.data(Qt.UserRole))
            for item in self.left_list.selectedItems()
            if item.data(Qt.UserRole) is not None
        })
        if not selected_rows:
            item = self.left_list.currentItem()
            if item and item.data(Qt.UserRole) is not None:
                selected_rows = [int(item.data(Qt.UserRole))]
        selected_rows = [r for r in selected_rows if 0 <= r < len(self.playlist)]
        if not selected_rows:
            return

        current_path = self.current_media_path()
        deleting_current = self.current_index in selected_rows and self.one_shot_path is None
        first_deleted = selected_rows[0]
        removed = [self.playlist[r] for r in selected_rows]

        for r in reversed(selected_rows):
            self.playlist.pop(r)

        app_log(f"Playlist delete: {len(removed)} item(s)")
        for path in removed[:10]:
            app_log(f"  removed: {path}")
        if len(removed) > 10:
            app_log(f"  ... and {len(removed) - 10} more")

        if not self.playlist:
            self.clear_playlist()
            return

        if current_path in self.playlist and not deleting_current:
            self.current_index = self.playlist.index(current_path)
        else:
            self.current_index = min(first_deleted, len(self.playlist) - 1)

        self.update_playlist_panel()
        if deleting_current:
            self.play_index(self.current_index, autoplay=True)
        self.save_settings()

    def apply_left_playlist_order(self):
        if self.playlist_search_text:
            self.clear_playlist_search()
        current_path = self.current_media_path()
        new_paths = []
        for i in range(self.left_list.count()):
            new_paths.append(Path(self.left_list.item(i).data(Qt.UserRole + 1)))
        self.playlist = new_paths
        if current_path in self.playlist:
            self.current_index = self.playlist.index(current_path)
        self.update_playlist_panel()
        self.save_settings()

    def play_playlist_index_from_view(self, index: int):
        if 0 <= index < len(self.playlist):
            self.play_index(index, autoplay=True)

    def clear_playlist_search(self):
        if not self.playlist_search_text:
            return
        app_log("Playlist search cleared")
        self.playlist_search_text = ""
        self.update_playlist_toolbar_buttons()
        self.update_playlist_panel()

    def search_playlist_dialog(self):
        if not self.playlist:
            return
        text, ok = QInputDialog.getText(
            self,
            T("プレイリスト検索"),
            T("検索文字を入力してください。空欄で全件表示に戻します。"),
            text=self.playlist_search_text,
        )
        if not ok:
            return
        query = str(text or "").strip()
        if not query:
            self.clear_playlist_search()
            return
        self.playlist_search_text = query
        app_log(f"Playlist search: {query}")
        self.update_playlist_toolbar_buttons()
        self.update_playlist_panel()
        first_match = self.first_playlist_search_match()
        if first_match is not None:
            self.play_index(first_match, autoplay=True)
        else:
            QToolTip.showText(self.search_playlist_button.mapToGlobal(QPoint(0, 34)), T("一致する項目がありません"), self.search_playlist_button)

    def first_playlist_search_match(self) -> int | None:
        query = self.playlist_search_text.strip().lower()
        if not query:
            return 0 if self.playlist else None
        for i, path in enumerate(self.playlist):
            haystacks = [
                self.get_display_title(path),
                path.name,
                str(path),
            ]
            if any(query in str(value).lower() for value in haystacks):
                return i
        return None

    def playlist_view_indices(self) -> list[int]:
        query = self.playlist_search_text.strip().lower()
        if not query:
            return list(range(len(self.playlist)))
        indices: list[int] = []
        for i, path in enumerate(self.playlist):
            haystacks = [
                self.get_display_title(path),
                path.name,
                str(path),
            ]
            if any(query in str(value).lower() for value in haystacks):
                indices.append(i)
        return indices

    def update_playlist_panel(self):
        if not hasattr(self, "left_list"):
            return
        old_block = self.left_list.blockSignals(True)
        self.left_list.clear()
        view_indices = self.playlist_view_indices()
        for i in view_indices:
            path = self.playlist[i]
            number = f"{i + 1:02d}. "
            title = self.get_display_title(path)
            text = number + title
            item = QListWidgetItem(text)
            item.setData(Qt.UserRole, i)
            item.setData(Qt.UserRole + 1, str(path))
            item.setToolTip(str(path))
            has_srt = bool(self.find_srt_for(path))
            has_srt2 = bool(self.find_srt2_for(path))
            if has_srt2:
                item.setForeground(QColor("#36c96b"))
                item.setToolTip(str(path) + T("\n字幕: 第2字幕あり"))
            elif has_srt:
                item.setForeground(QColor("#58a6ff"))
                item.setToolTip(str(path) + T("\n字幕: あり"))
            if i == self.current_index and self.one_shot_path is None:
                item.setForeground(QColor("#ff9b45"))
                font = item.font()
                font.setBold(True)
                item.setFont(font)
                item.setText("▶ " + text)
            self.left_list.addItem(item)
        if self.one_shot_path is None and self.current_index in view_indices:
            view_row = view_indices.index(self.current_index)
            self.left_list.setCurrentRow(view_row)
            self.left_list.scrollToItem(self.left_list.item(view_row), QAbstractItemView.PositionAtCenter)
        self.left_list.blockSignals(old_block)
        self.update_playlist_footer()
        self.refresh_playlist_window()

    def update_playlist_footer(self):
        if hasattr(self, "playlist_footer_label"):
            total = len(self.playlist)
            current = self.current_index + 1 if 0 <= self.current_index < total else 0
            if self.playlist_search_text:
                visible = self.left_list.count() if hasattr(self, "left_list") else len(self.playlist_view_indices())
                self.playlist_footer_label.setText(f"{current}/{total}  検索:{visible}")
            else:
                self.playlist_footer_label.setText(f"{current}/{total}")

    def apply_subtitle_style(self, font: Optional[QFont] = None, color: Optional[QColor] = None) -> None:
        if font is not None:
            self.subtitle_font = QFont(font)
        if color is not None:
            self.subtitle_color = QColor(color)
        if hasattr(self, "subtitle_overlay"):
            self.subtitle_overlay.set_subtitle_style(self.subtitle_font, self.subtitle_color)

    def open_subtitle_font_dialog(self):
        old_font = QFont(self.subtitle_font)
        old_color = QColor(self.subtitle_color)
        dlg = SubtitleFontDialog(self, old_font, old_color)
        dlg.preview_changed.connect(self.apply_subtitle_style)
        result = dlg.exec()
        if result == QDialog.DialogCode.Accepted:
            self.apply_subtitle_style(dlg.selected_font(), dlg.selected_color())
            self.save_settings()
            app_log(
                f"Subtitle font updated: family={self.subtitle_font.family()}, "
                f"size={self.subtitle_font.pointSize()}, color={self.subtitle_color.name()}"
            )
        else:
            self.apply_subtitle_style(old_font, old_color)
            app_log("Subtitle font change canceled")

    def show_gear_menu(self, global_pos: QPoint | None = None):
        menu = QMenu(self)
        menu.setStyleSheet(self.menu_style())

        export_menu = QMenu(T("リストファイルを作成..."), menu)
        export_menu.setStyleSheet(self.menu_style())
        wpl_action = QAction(T("WPLを作成"), self)
        wpl_action.setEnabled(bool(self.playlist))
        wpl_action.triggered.connect(self.export_wpl_playlist)
        export_menu.addAction(wpl_action)
        m3u8_action = QAction(T("M3U8を作成"), self)
        m3u8_action.setEnabled(bool(self.playlist))
        m3u8_action.triggered.connect(self.export_m3u8_playlist)
        export_menu.addAction(m3u8_action)
        menu.addMenu(export_menu)

        clear_action = QAction(T("リストをクリア"), self)
        clear_action.setEnabled(bool(self.playlist))
        clear_action.triggered.connect(self.clear_playlist)
        menu.addAction(clear_action)

        menu.addSeparator()
        shuffle_action = QAction(T("リストをシャッフル"), self)
        shuffle_action.setEnabled(bool(self.playlist))
        shuffle_action.triggered.connect(self.shuffle_playlist)
        menu.addAction(shuffle_action)

        sort_action = QAction(T("ファイル名順に並べ替え"), self)
        sort_action.setEnabled(bool(self.playlist))
        sort_action.triggered.connect(self.sort_playlist_by_filename)
        menu.addAction(sort_action)

        repeat_menu = menu.addMenu(T("リピート"))
        for label, mode in (("Off", "off"), (T("1曲"), "one"), (T("全曲"), "all")):
            act = QAction(label, self)
            act.setCheckable(True)
            act.setChecked(self.repeat_mode == mode)
            act.triggered.connect(lambda _checked=False, m=mode: self.set_repeat_mode(m))
            repeat_menu.addAction(act)

        menu.addSeparator()
        subtitle_auto_show_action = QAction(T("字幕を表示する"), self)
        subtitle_auto_show_action.setCheckable(True)
        subtitle_auto_show_action.setChecked(bool(self.subtitle_auto_show_enabled))
        subtitle_auto_show_action.triggered.connect(self.set_subtitle_auto_show_enabled)
        menu.addAction(subtitle_auto_show_action)

        menu.addSeparator()
        log_action = QAction(T("ログウィンドウを表示 / 非表示  F12"), self)
        log_action.triggered.connect(self.toggle_log_window)
        menu.addAction(log_action)
        update_action = QAction(T("GitHub Release の更新確認"), self)
        update_action.triggered.connect(lambda _checked=False: self.check_for_app_update(silent=False, manual=True))
        menu.addAction(update_action)

        pos = global_pos if global_pos is not None else self.gear_button.mapToGlobal(self.gear_button.rect().bottomLeft())
        menu.exec(pos)

    def help_label(self, ja: str, en: str) -> str:
        return ja if APP_UI_LANGUAGE == "ja" else en

    def show_help_menu(self, global_pos: QPoint | None = None):
        menu = QMenu(self)
        menu.setStyleSheet(self.menu_style())

        about_action = QAction(self.help_label("DropMp3について", "About DropMp3"), self)
        about_action.triggered.connect(lambda checked=False: self.show_about_dialog())
        menu.addAction(about_action)

        operation_action = QAction(self.help_label("操作方法", "Operation Guide"), self)
        operation_action.triggered.connect(lambda checked=False: self.open_help_page("operation"))
        menu.addAction(operation_action)

        install_action = QAction(self.help_label("Install方法", "Install Guide"), self)
        install_action.triggered.connect(lambda checked=False: self.open_help_page("install"))
        menu.addAction(install_action)

        pos = global_pos if global_pos is not None else self.help_button.mapToGlobal(self.help_button.rect().bottomLeft())
        menu.exec(pos)

    def position_dialog_above_tray(self, dialog: QDialog):
        tray_icon = getattr(self, "tray_icon", None)
        if tray_icon is not None:
            try:
                tray_geo = tray_icon.geometry()
                if tray_geo.isValid():
                    target = QPoint(
                        tray_geo.center().x() - int(dialog.width() / 2),
                        tray_geo.top() - dialog.height() - 12,
                    )
                    screen = QApplication.screenAt(tray_geo.center()) or QApplication.primaryScreen()
                    if screen is not None:
                        available = screen.availableGeometry()
                        target.setX(max(available.left() + 8, min(target.x(), available.right() - dialog.width() - 8)))
                        target.setY(max(available.top() + 8, min(target.y(), available.bottom() - dialog.height() - 8)))
                    dialog.move(target)
                    return
            except Exception as exc:
                app_log(f"[ABOUT] tray position failed: {exc}")
        fallback = QCursor.pos()
        dialog.move(fallback.x() - int(dialog.width() / 2), fallback.y() - dialog.height() - 16)

    def show_about_dialog(self):
        dialog = QDialog(self)
        dialog.setWindowTitle(self.help_label("DropMp3について", "About DropMp3"))
        dialog.setModal(False)
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        dialog.setWindowFlag(Qt.WindowType.Tool, True)
        dialog.setStyleSheet("""
            QDialog { background:#171717; color:#f3f3f3; border:1px solid #2f6fb6; }
            QLabel { color:#f3f3f3; }
            QLabel#aboutTitle { font-size:24px; font-weight:700; color:#ffffff; }
            QLabel#aboutBody { font-size:13px; line-height:1.5; }
            QPushButton {
                background:#2b2b2b; color:#f0f0f0; border:1px solid #5f6d7f;
                border-radius:5px; padding:7px 18px; min-width:84px;
            }
            QPushButton:hover { background:#234c7a; border-color:#59a7ff; }
        """)

        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(14, 14, 14, 12)
        layout.setSpacing(10)

        header = QLabel(self.help_label("DropMp3について", "About DropMp3"))
        header.setObjectName("aboutTitle")
        layout.addWidget(header)

        body_layout = QHBoxLayout()
        body_layout.setSpacing(14)

        image_label = QLabel()
        image_label.setFixedSize(180, 180)
        image_label.setAlignment(Qt.AlignCenter)
        image_path = self.about_image_path()
        if image_path is not None:
            pixmap = QPixmap(str(image_path))
            if not pixmap.isNull():
                image_label.setPixmap(pixmap.scaled(180, 180, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        body_layout.addWidget(image_label)

        text_browser = QTextBrowser()
        text_browser.setOpenExternalLinks(True)
        text_browser.setFrameShape(QFrame.NoFrame)
        text_browser.setStyleSheet("background:transparent; border:none; color:#f3f3f3;")
        version_label = format_version_label(self.current_app_version)
        github_url = f"https://github.com/{APP_GITHUB_REPO}/"
        text_browser.setHtml(
            f"""
            <div style="font-size:13px; color:#f3f3f3;">
              <div style="font-size:22px; font-weight:700; color:#ffffff; margin-bottom:10px;">DropMp3 {version_label}</div>
              <div style="margin-bottom:12px;">音声ファイルをドラッグ&ドロップして再生できる、常駐型のミニプレイヤーです。</div>
              <div style="margin-bottom:12px;">GitHub: <a href="{github_url}" style="color:#7db7ff;">{github_url}</a></div>
              <div style="margin-bottom:12px;">トレイ左クリック: プレイリスト表示<br>トレイ左ダブルクリック: Player表示<br>トレイ右クリック: メニュー表示</div>
              <div>現在曲: {escape(self.current_track_tooltip_text())}</div>
            </div>
            """
        )
        body_layout.addWidget(text_browser, 1)

        layout.addLayout(body_layout)

        button_row = QHBoxLayout()
        button_row.addStretch(1)
        ok_button = QPushButton("OK")
        ok_button.clicked.connect(dialog.close)
        button_row.addWidget(ok_button)
        layout.addLayout(button_row)

        dialog.resize(700, 360)
        self.position_dialog_above_tray(dialog)
        self.help_dialogs.append(dialog)
        dialog.destroyed.connect(lambda *_: self.help_dialogs.remove(dialog) if dialog in self.help_dialogs else None)
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def show_playlist_window(self):
        if self.playlist_window is None:
            dialog = QDialog(None)
            dialog.setWindowTitle(T("プレイリスト表示"))
            dialog.setModal(False)
            dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)
            dialog.setWindowFlag(Qt.WindowType.Tool, True)
            dialog.setStyleSheet("""
                QDialog{background:#181818;color:#eeeeee;}
                QListWidget{background:#101010;color:#eeeeee;border:1px solid #333;outline:none;}
                QListWidget::item{padding:6px;border-bottom:1px solid #242424;}
                QListWidget::item:selected{background:#2d4a35;color:#fff;}
                QLabel{color:#dfffe7;font-weight:bold;}
                QPushButton{background:#2b2b2b;color:#fff;border:1px solid #666;border-radius:5px;padding:6px 16px;}
                QPushButton:hover{background:#1d3828;border-color:#41db78;}
            """)
            layout = QVBoxLayout(dialog)
            layout.setContentsMargins(10, 10, 10, 10)
            layout.setSpacing(8)
            title = QLabel(T("現在の再生リスト"))
            layout.addWidget(title)
            list_widget = QListWidget()
            list_widget.setSelectionMode(QAbstractItemView.SingleSelection)
            list_widget.itemDoubleClicked.connect(lambda item: self.play_playlist_window_index(int(item.data(Qt.UserRole))))
            layout.addWidget(list_widget, 1)
            close_button = QPushButton(T("閉じる"))
            close_button.clicked.connect(dialog.hide)
            layout.addWidget(close_button, alignment=Qt.AlignRight)
            dialog.resize(560, 520)
            self.playlist_window = dialog
            self.playlist_window_list = list_widget
        self.refresh_playlist_window()
        self.playlist_window.show()
        self.playlist_window.raise_()
        self.playlist_window.activateWindow()

    def play_playlist_window_index(self, index: int):
        if 0 <= index < len(self.playlist):
            self.play_index(index, autoplay=True)
            if self.playlist_window is not None:
                self.playlist_window.raise_()

    def refresh_playlist_window(self):
        list_widget = getattr(self, "playlist_window_list", None)
        if list_widget is None:
            return
        list_widget.clear()
        if not self.playlist:
            empty = QListWidgetItem(T("曲がありません"))
            empty.setFlags(Qt.NoItemFlags)
            list_widget.addItem(empty)
            return
        current_row = -1
        for i, path in enumerate(self.playlist):
            prefix = "▶ " if i == self.current_index and self.one_shot_path is None else "   "
            item = QListWidgetItem(f"{prefix}{i + 1:02d}. {self.get_display_title(path)}")
            item.setData(Qt.UserRole, i)
            item.setToolTip(str(path))
            if i == self.current_index and self.one_shot_path is None:
                item.setForeground(QColor("#ff9b45"))
                current_row = i
            list_widget.addItem(item)
        if current_row >= 0:
            list_widget.setCurrentRow(current_row)
            list_widget.scrollToItem(list_widget.item(current_row), QAbstractItemView.PositionAtCenter)

    def help_path_for(self, page_key: str) -> Path:
        lang = "ja" if APP_UI_LANGUAGE == "ja" else "en"
        files = getattr(self, "help_files", {})
        path = files.get(page_key, {}).get(lang)
        if path:
            return path
        suffix = "Install_Help" if page_key == "install" else page_key.capitalize()
        return self.app_base_dir() / "_conf" / "html" / f"DropMp3_{suffix}_{lang}.html"

    def open_help_page(self, page_key: str):
        help_path = self.help_path_for(page_key)
        if not help_path.exists() and page_key == "install":
            legacy = self.app_base_dir() / "_conf" / "html" / "DropMp3_Install_Help.html"
            if legacy.exists():
                help_path = legacy
        if not help_path.exists():
            legacy = self.app_base_dir() / "_conf" / help_path.name
            if legacy.exists():
                help_path = legacy
        if not help_path.exists():
            QMessageBox.information(self, self.help_label("Help未作成", "Help not found"), f"Helpファイルが見つかりません。\n\n{help_path}")
            return
        self.show_help_window(help_path, page_key)

    def help_window_title(self, page_key: str) -> str:
        titles = {
            "about": self.help_label("DropMp3について", "About DropMp3"),
            "operation": self.help_label("DropMp3 操作方法", "DropMp3 Operation Guide"),
            "install": self.help_label("DropMp3 Install方法", "DropMp3 Install Guide"),
        }
        return titles.get(page_key, self.help_label("DropMp3 Help", "DropMp3 Help"))

    def show_help_window(self, help_path: Path, page_key: str):
        dialog = QDialog(self)
        dialog.setWindowTitle(self.help_window_title(page_key))
        dialog.setModal(False)
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        dialog.setStyleSheet("""
            QDialog { background:#151515; color:#f0f0f0; }
            QLabel { color:#e8f5e9; font-size:16px; font-weight:700; }
            QTextBrowser {
                background:#101214;
                color:#e8ece8;
                border:1px solid #323a32;
                border-radius:6px;
                padding:0px;
                selection-background-color:#227a45;
            }
            QPushButton {
                background:#2b2b2b;
                color:#f0f0f0;
                border:1px solid #555;
                border-radius:5px;
                padding:7px 16px;
                min-width:84px;
            }
            QPushButton:hover { background:#1f3a2a; border-color:#41db78; }
        """)

        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(14, 12, 14, 14)
        layout.setSpacing(10)

        title_label = QLabel(self.help_window_title(page_key))
        layout.addWidget(title_label)

        browser = QTextBrowser()
        browser.setOpenExternalLinks(True)
        browser.setSearchPaths([str(help_path.parent), str(self.app_base_dir())])
        browser.setSource(QUrl.fromLocalFile(str(help_path)))
        layout.addWidget(browser, 1)

        button_row = QHBoxLayout()
        open_external_button = QPushButton(self.help_label("外部で開く", "Open External"))
        close_button = QPushButton(T("閉じる"))
        button_row.addStretch(1)
        button_row.addWidget(open_external_button)
        button_row.addWidget(close_button)
        layout.addLayout(button_row)

        open_external_button.clicked.connect(lambda checked=False, p=help_path: QDesktopServices.openUrl(QUrl.fromLocalFile(str(p))))
        close_button.clicked.connect(dialog.close)

        self.position_help_window_center(dialog)
        self.help_dialogs.append(dialog)
        dialog.destroyed.connect(lambda *_: self.help_dialogs.remove(dialog) if dialog in self.help_dialogs else None)
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def position_help_window_center(self, dialog: QDialog):
        try:
            app_geo = self.frameGeometry()
            width = min(980, max(620, int(app_geo.width() * 0.72)))
            height = min(760, max(460, int(app_geo.height() * 0.72)))
            dialog.resize(width, height)
            dialog.move(app_geo.center() - dialog.rect().center())
        except Exception as exc:
            app_log(f"[HELP] center failed: {exc}")

    def set_one_shot_mode(self, checked: bool):
        self.one_shot_mode = bool(checked)
        if hasattr(self, "one_shot_button") and self.one_shot_button.isChecked() != self.one_shot_mode:
            self.one_shot_button.blockSignals(True)
            self.one_shot_button.setChecked(self.one_shot_mode)
            self.one_shot_button.blockSignals(False)
        app_log(f"One-shot mode: {'ON' if self.one_shot_mode else 'OFF'}")
        if self.one_shot_mode:
            self.enter_one_shot_panel_mode()
        else:
            if self.is_one_shot_panel_mode:
                self.exit_one_shot_panel_mode()
            self.one_shot_path = None
            self.one_shot_return_path = None
            self.one_shot_return_index = -1
            self.one_shot_return_position = 0
            self.one_shot_return_was_playing = False
            self.one_shot_name_label.setText(T("ここに音声ファイルをDrop"))
            if self.playlist and 0 <= self.current_index < len(self.playlist):
                path = self.playlist[self.current_index]
                title = self.get_display_title(path)
                self.title_label.setText(title)
                self.art_title_label.setText(title)
                self.load_album_art(path)
                self.load_subtitles_for(path)
        self.save_settings()

    def confirm_clear_playlist(self):
        if not self.playlist:
            return
        result = QMessageBox.question(
            self,
            T("再生リストをクリア"),
            T("現在の再生リストをすべて消去します。よろしいですか？"),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if result != QMessageBox.Yes:
            return
        self.clear_playlist()
        self.set_current_playlist_name(self.generate_new_playlist_name())
        self.save_settings()
        app_log("Playlist cleared by confirmation")

    def create_new_playlist(self):
        if self.playlist:
            result = QMessageBox.question(
                self,
                T("新しい再生リスト"),
                T("現在の再生リストをクリアして、新しい再生リストを作成します。よろしいですか？"),
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if result != QMessageBox.Yes:
                return
        self.set_current_playlist_name(self.generate_new_playlist_name())
        self.clear_playlist()
        self.save_settings()
        app_log(f"New playlist created: {self.current_playlist_name}")

    def write_wpl_playlist_file(self, playlist_path: Path):
        lines = ['<?wpl version="1.0"?>', '<smil>', '  <head>', '    <meta name="Generator" content="DropMp3"/>', '    <title>DropMp3 Playlist</title>', '  </head>', '  <body>', '    <seq>']
        for path in self.playlist:
            if path.exists():
                src = escape(relative_or_absolute_path(path, playlist_path), quote=True)
                lines.append(f'      <media src="{src}"/>')
        lines += ['    </seq>', '  </body>', '</smil>']
        playlist_path.write_text("\n".join(lines), encoding="utf-8-sig")

    def write_m3u8_playlist_file(self, playlist_path: Path):
        lines = ["#EXTM3U"]
        for path in self.playlist:
            if not path.exists():
                continue
            title = self.get_display_title(path)
            duration_sec = -1
            try:
                media = MutagenFile(str(path))
                if media and media.info and getattr(media.info, "length", None):
                    duration_sec = int(media.info.length)
            except Exception:
                pass
            lines.append(f"#EXTINF:{duration_sec},{title}")
            lines.append(relative_or_absolute_path(path, playlist_path))
        playlist_path.write_text("\n".join(lines), encoding="utf-8-sig")

    def playlist_timestamp(self) -> str:
        return datetime.now().strftime("%Y%m%d_%H%M%S")

    def generate_new_playlist_name(self) -> str:
        return datetime.now().strftime("DropMp3_%y%m%d%H%M")

    def sanitize_playlist_name(self, name: str | None) -> str:
        text = re.sub(r'[\\/:*?"<>|]+', "_", str(name or "").strip())
        text = text.rstrip(". ")
        return text or self.generate_new_playlist_name()

    def set_current_playlist_name(self, name: str | None):
        self.current_playlist_name = self.sanitize_playlist_name(name)

    def default_playlist_path(self, suffix: str = ".m3u8") -> Path:
        conf_dir = self.app_base_dir() / "_conf" / "lst"
        try:
            conf_dir.mkdir(parents=True, exist_ok=True)
        except Exception as exc:
            app_log(f"[PLAYLIST] _conf/lst create failed: {exc}")
        return conf_dir / f"{self.current_playlist_name}{suffix}"

    def saved_playlist_files(self) -> list[Path]:
        roots = [
            self.app_base_dir() / "_conf" / "lst",
            self.app_base_dir() / "_conf",
        ]
        files: list[Path] = []
        for root in roots:
            if not root.exists():
                continue
            for pattern in ("DropMp3_*.m3u8", "DropMp3_*.wpl", "DropMp3_Playlist*.m3u8", "DropMp3_Playlist*.wpl", "playlist*.m3u8", "playlist*.wpl"):
                files.extend(root.glob(pattern))
        unique = {}
        for p in files:
            try:
                unique[str(p.resolve()).lower()] = p
            except Exception:
                unique[str(p).lower()] = p
        return sorted(unique.values(), key=lambda p: p.stat().st_mtime if p.exists() else 0, reverse=True)

    def playlist_preview_items(self, playlist_path: Path) -> list[Path]:
        try:
            return parse_playlist_file(playlist_path)
        except Exception as exc:
            app_log(f"Playlist preview failed: {playlist_path}: {exc}")
            return []

    def show_saved_playlist_popup(self):
        files = self.saved_playlist_files()
        if not files:
            QMessageBox.information(self, T("リストファイルなし"), f"保存済みリストが見つかりません。\n\n{self.app_base_dir() / '_conf' / 'lst'}")
            return

        dialog = QDialog(self)
        dialog.setWindowTitle(T("保存済みリスト"))
        dialog.setModal(False)
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        dialog.setStyleSheet("""
            QDialog{background:#181818;color:#eee;}
            QListWidget{background:#101010;color:#eee;border:1px solid #333;outline:none;}
            QListWidget::item{padding:6px;border-bottom:1px solid #242424;}
            QListWidget::item:selected{background:#2d4a35;color:#fff;}
            QLabel{color:#eee;}
            QPushButton{background:#2b2b2b;color:#fff;border:1px solid #666;border-radius:5px;padding:6px 16px;}
            QPushButton:hover{background:#1d3828;border-color:#41db78;}
        """)
        layout = QHBoxLayout(dialog)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        list_widget = QListWidget()
        list_widget.setMinimumWidth(360)
        list_font = list_widget.font()
        list_font.setPointSize(int(self.playlist_font_size))
        list_widget.setFont(list_font)
        for path in files:
            item = QListWidgetItem(path.name)
            item.setData(Qt.UserRole, str(path))
            item.setToolTip(str(path))
            row_height = max(40, int(self.playlist_font_size * 2.8))
            item.setSizeHint(QSize(340, row_height))
            list_widget.addItem(item)
        layout.addWidget(list_widget)

        right = QVBoxLayout()
        title = QLabel(T("リスト内容プレビュー"))
        title.setStyleSheet("font-weight:bold;color:#dfffe7;")
        preview = QListWidget()
        preview.setMinimumWidth(520)
        preview.setMinimumHeight(360)
        preview_font = preview.font()
        preview_font.setPointSize(int(self.playlist_font_size))
        preview.setFont(preview_font)
        right.addWidget(title)
        right.addWidget(preview, 1)

        buttons = QDialogButtonBox()
        load_button = buttons.addButton(T("読込"), QDialogButtonBox.ButtonRole.AcceptRole)
        close_button = buttons.addButton(T("閉じる"), QDialogButtonBox.ButtonRole.RejectRole)
        right.addWidget(buttons)
        layout.addLayout(right)

        def update_preview(item):
            preview.clear()
            if not item:
                return
            path = Path(item.data(Qt.UserRole))
            entries = self.playlist_preview_items(path)
            if not entries:
                preview.addItem(T("リスト内に再生対象がありません。"))
                return
            for i, media in enumerate(entries, 1):
                preview.addItem(f"{i:02d}. {media.name}")
            if len(entries) > 10:
                preview.scrollToTop()

        def load_current():
            item = list_widget.currentItem()
            if not item:
                return
            path = Path(item.data(Qt.UserRole))
            entries = self.playlist_preview_items(path)
            if not entries:
                QMessageBox.information(dialog, T("リストファイルなし"), T("リスト内に再生対象がありません。"))
                return
            self.player.stop()
            self.playlist = entries
            self.playlist_search_text = ""
            self.current_index = -1
            self.one_shot_path = None
            self.drawer_open = False
            self.set_current_playlist_name(path.stem)
            self.update_playlist_toolbar_buttons()
            self.update_playlist_panel()
            self.update_left_panel_visibility()
            self.add_files_to_playlist([], autoplay=False)
            self.play_index(0, autoplay=True)
            self.save_settings()
            app_log(f"Playlist loaded from saved list: {path}")
            dialog.close()

        list_widget.currentItemChanged.connect(lambda current, _previous: update_preview(current))
        list_widget.itemEntered.connect(update_preview)
        list_widget.itemDoubleClicked.connect(lambda _item: load_current())
        load_button.clicked.connect(load_current)
        close_button.clicked.connect(dialog.close)
        list_widget.setMouseTracking(True)
        if list_widget.count():
            list_widget.setCurrentRow(0)
            update_preview(list_widget.currentItem())

        dialog.resize(980, 520)
        pos = self.load_playlist_button.mapToGlobal(self.load_playlist_button.rect().topRight())
        dialog.move(pos + QPoint(8, 0))
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def export_playlist_file_dialog(self):
        if not self.playlist:
            QMessageBox.information(self, T("ファイルがありません"), T("保存する再生リストがありません。"))
            return
        save_path, selected_filter = QFileDialog.getSaveFileName(
            self,
            T("再生リストファイルを保存"),
            str(self.default_playlist_path(".m3u8")),
            T("再生リストファイル (*.m3u8 *.wpl);;M3U8 Playlist (*.m3u8);;Windows Media Player Playlist (*.wpl)"),
        )
        if not save_path:
            return
        low = save_path.lower()
        if not (low.endswith(".m3u8") or low.endswith(".wpl")):
            save_path += ".wpl" if "WPL" in selected_filter or "Windows" in selected_filter else ".m3u8"
        playlist_path = Path(save_path)
        try:
            if playlist_path.suffix.lower() == ".wpl":
                self.write_wpl_playlist_file(playlist_path)
            else:
                if playlist_path.suffix.lower() != ".m3u8":
                    playlist_path = playlist_path.with_suffix(".m3u8")
                self.write_m3u8_playlist_file(playlist_path)
            self.set_current_playlist_name(playlist_path.stem)
            app_log(f"Playlist exported: {playlist_path}")
            QMessageBox.information(self, T("保存完了"), T("再生リストを保存しました。"))
        except Exception as e:
            app_log(f"[PLAYLIST EXPORT ERROR] {e}")
            QMessageBox.warning(self, T("保存失敗"), f"{T('プレイリスト保存失敗')}\n\n{e}")

    def export_wpl_playlist(self):
        if not self.playlist:
            return
        save_path, _ = QFileDialog.getSaveFileName(self, T("WPLリストファイルを作成"), str(self.default_playlist_path(".wpl")), "Windows Media Player Playlist (*.wpl)")
        if not save_path:
            return
        if not save_path.lower().endswith(".wpl"):
            save_path += ".wpl"
        playlist_path = Path(save_path)
        try:
            lines = ['<?wpl version="1.0"?>', '<smil>', '  <head>', '    <meta name="Generator" content="DropMp3"/>', '    <title>DropMp3 Playlist</title>', '  </head>', '  <body>', '    <seq>']
            for path in self.playlist:
                if path.exists():
                    src = escape(relative_or_absolute_path(path, playlist_path), quote=True)
                    lines.append(f'      <media src="{src}"/>')
            lines += ['    </seq>', '  </body>', '</smil>']
            playlist_path.write_text("\n".join(lines), encoding="utf-8-sig")
            self.set_current_playlist_name(playlist_path.stem)
            app_log(f"WPL exported: {playlist_path}")
        except Exception as e:
            app_log(f"[WPL ERROR] {e}")
            QMessageBox.warning(self, T("保存失敗"), f"WPLリストファイルの保存に失敗しました。\n\n{e}")

    def export_m3u8_playlist(self):
        if not self.playlist:
            return
        save_path, _ = QFileDialog.getSaveFileName(self, T("M3U8リストファイルを作成"), str(self.default_playlist_path(".m3u8")), "M3U8 Playlist (*.m3u8)")
        if not save_path:
            return
        if not save_path.lower().endswith(".m3u8"):
            save_path += ".m3u8"
        playlist_path = Path(save_path)
        try:
            lines = ["#EXTM3U"]
            for path in self.playlist:
                if not path.exists():
                    continue
                title = self.get_display_title(path)
                duration_sec = -1
                try:
                    media = MutagenFile(str(path))
                    if media and media.info and getattr(media.info, "length", None):
                        duration_sec = int(media.info.length)
                except Exception:
                    pass
                lines.append(f"#EXTINF:{duration_sec},{title}")
                lines.append(relative_or_absolute_path(path, playlist_path))
            playlist_path.write_text("\n".join(lines), encoding="utf-8-sig")
            self.set_current_playlist_name(playlist_path.stem)
            app_log(f"M3U8 exported: {playlist_path}")
        except Exception as e:
            app_log(f"[M3U8 ERROR] {e}")
            QMessageBox.warning(self, T("保存失敗"), f"M3U8リストファイルの保存に失敗しました。\n\n{e}")


    def show_left_playlist_item_menu(self, index: int, global_pos: QPoint):
        T("""左側ドロワーの曲リストで右クリックした時の個別メニュー。""")
        if not (0 <= index < len(self.playlist)):
            return
        path = self.playlist[index]
        self.left_list.setCurrentRow(index)

        menu = QMenu(self)
        menu.setStyleSheet(self.menu_style())

        prop_action = QAction(T("プロパティ"), self)
        prop_action.triggered.connect(lambda checked=False, p=path: self.show_media_properties(p))
        menu.addAction(prop_action)
        menu.addSeparator()

        subtitle_action = QAction(T("字幕依頼"), self)
        subtitle_action.triggered.connect(lambda checked=False, p=path: self.request_subtitle_with_whisper(p))
        menu.addAction(subtitle_action)

        check_subtitle_action = QAction(T("字幕確認"), self)
        check_subtitle_action.triggered.connect(lambda checked=False, p=path: self.open_subtitle_file_in_notepad(p))
        menu.addAction(check_subtitle_action)

        delete_subtitle_action = QAction(T("字幕削除"), self)
        delete_subtitle_action.triggered.connect(lambda checked=False, p=path: self.delete_subtitle_files(p))
        menu.addAction(delete_subtitle_action)

        menu.addSeparator()
        remove_action = QAction(T("リストから削除"), self)
        remove_action.triggered.connect(lambda checked=False, i=index: self.delete_playlist_index(i))
        menu.addAction(remove_action)

        menu.addSeparator()
        exit_action = QAction(T("終了"), self)
        exit_action.triggered.connect(self.exit_application)
        menu.addAction(exit_action)

        menu.exec(global_pos)

    def delete_playlist_index(self, index: int):
        T("""指定行をプレイリストから削除する。左リストの右クリック用。""")
        if not (0 <= index < len(self.playlist)):
            return
        deleting_current = index == self.current_index and self.one_shot_path is None
        removed = self.playlist.pop(index)
        app_log(f"Playlist delete by menu: {removed}")
        if not self.playlist:
            self.clear_playlist()
            return
        if index < self.current_index:
            self.current_index -= 1
        elif index == self.current_index:
            self.current_index = min(index, len(self.playlist) - 1)
        self.update_playlist_panel()
        self.update_left_panel_visibility()
        if deleting_current:
            self.play_index(self.current_index, autoplay=True)
        self.save_settings()

    def position_dialog_over_player(self, dialog: QDialog, width: int | None = None, height: int | None = None):
        T("""別ウィンドウをPlayer上部へ出す。""")
        try:
            if width and height:
                dialog.resize(width, height)
            geo = self.frameGeometry()
            dsize = dialog.sizeHint()
            if dialog.width() > 0 and dialog.height() > 0:
                dsize = dialog.size()
            x = geo.x() + max(0, (geo.width() - dsize.width()) // 2)
            y = geo.y() + 28
            dialog.move(x, y)
        except Exception as e:
            app_log(f"[DIALOG] position failed: {e}")

    def mime_for_path(self, path: Path) -> str:
        """Return a best-effort MIME type for the detail/properties window."""
        try:
            guessed, _ = mimetypes.guess_type(str(path))
            if guessed:
                return guessed
        except Exception:
            pass
        suffix = path.suffix.lower()
        fallback = {
            ".mp3": "audio/mpeg",
            ".m4a": "audio/mp4",
            ".aac": "audio/aac",
            ".wav": "audio/wav",
            ".flac": "audio/flac",
            ".ogg": "audio/ogg",
            ".opus": "audio/opus",
            ".wma": "audio/x-ms-wma",
            ".mp4": "video/mp4",
            ".m4v": "video/x-m4v",
            ".mov": "video/quicktime",
            ".mkv": "video/x-matroska",
            ".avi": "video/x-msvideo",
            ".webm": "video/webm",
        }
        return fallback.get(suffix, "application/octet-stream")

    def request_subtitle_with_whisper(self, path: Path):
        """Backward-compatible menu handler.

        Older context-menu wiring calls this name; the visible progress-dialog
        implementation lives in request_subtitles().
        """
        return self.request_subtitles(path)

    def show_media_properties(self, path: Path):
        """ffprobe があれば、整形済みの詳細情報を別ウィンドウで表示する。"""
        ffprobe = shutil.which("ffprobe") or shutil.which("ffprobe.exe")
        if not ffprobe:
            QMessageBox.information(self, T("ffprobe未検出"), T("ffprobe がInstallされていません。\n\nFFmpegをInstallして、ffprobe.exe をPATHに追加してください。"))
            app_log("ffprobe not found")
            return
        if not path.exists():
            QMessageBox.warning(self, T("ファイルなし"), f"ファイルが見つかりません。\n\n{path}")
            return

        cmd = [ffprobe, "-v", "quiet", "-print_format", "json", "-show_format", "-show_streams", str(path)]
        app_log("ffprobe property request: " + " ".join(cmd))
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=20)
        except Exception as e:
            QMessageBox.warning(self, T("ffprobe実行失敗"), f"{T('ffprobe の実行に失敗しました。\n\n')}{e}")
            app_log(f"ffprobe exception: {e}")
            return
        if result.returncode != 0:
            QMessageBox.warning(self, T("ffprobeエラー"), result.stderr.strip() or T("ffprobe がエラーを返しました。"))
            app_log(f"ffprobe error: {result.stderr.strip()}")
            return
        try:
            info = json.loads(result.stdout or "{}")
        except Exception as e:
            QMessageBox.warning(self, T("ffprobe解析失敗"), f"{T('ffprobe のJSON解析に失敗しました。\n\n')}{e}")
            return

        def fmt_duration(v):
            try:
                sec = float(v)
                h = int(sec // 3600); m = int((sec % 3600) // 60); ss = int(sec % 60)
                return f"{h:02d}:{m:02d}:{ss:02d}" if h else f"{m:02d}:{ss:02d}"
            except Exception:
                return ""

        def fmt_size(v):
            try:
                n = int(v); return f"{n:,} bytes / {n / 1024 / 1024:.3f} MiB"
            except Exception:
                return "" if v is None else str(v)

        def fmt_bitrate(v):
            try:
                n = int(float(v)); return f"{n:,} bps ({n / 1000:.1f} kbps)"
            except Exception:
                return "" if v is None else str(v)

        dialog = QDialog(self)
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        dialog.setWindowTitle(f"{T('詳細情報: ')}{path.name}")
        dialog.setStyleSheet("""
            QDialog{background:#202020; color:#eee;}
            QTreeWidget{background:#242424; color:#f0f0f0; border:1px solid #444; alternate-background-color:#303030; font-size:11pt;}
            QTreeWidget::item{padding:3px 4px;}
            QTreeWidget::item:selected{background:#0b73bd; color:#fff;}
            QHeaderView::section{background:#3a3a3a; color:#fff; padding:6px; border:1px solid #555;}
            QPushButton{background:#2b2b2b; color:#fff; border:1px solid #666; border-radius:5px; padding:6px 18px;}
        """)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(8, 8, 8, 8)

        tree = QTreeWidget()
        tree.setColumnCount(2)
        tree.setHeaderLabels([T("項目"), T("値")])
        tree.setAlternatingRowColors(True)
        tree.setUniformRowHeights(True)
        tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        tree.header().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        tree.setColumnWidth(0, 270)
        layout.addWidget(tree, 1)

        def root(name):
            item = QTreeWidgetItem([name, ""]); tree.addTopLevelItem(item); return item
        def add(parent, name, value=""):
            item = QTreeWidgetItem([str(name), "" if value is None else str(value)]); parent.addChild(item); return item

        fmt = info.get("format", {}) or {}
        streams = info.get("streams", []) or []
        v_streams = [x for x in streams if x.get("codec_type") == "video"]
        a_streams = [x for x in streams if x.get("codec_type") == "audio"]

        b = root(T("基本"))
        add(b, T("ファイル名"), path.name)
        add(b, T("パス"), str(path))
        add(b, "MIME", self.mime_for_path(path))
        try:
            stp = path.stat()
            add(b, T("サイズ"), fmt_size(stp.st_size))
            add(b, T("更新日時"), datetime.fromtimestamp(stp.st_mtime).strftime("%Y-%m-%d %H:%M:%S"))
        except Exception:
            pass
        if fmt.get("duration"):
            add(b, T("長さ"), fmt_duration(fmt.get("duration")))
            try: add(b, T("長さ (ms)"), int(float(fmt.get("duration")) * 1000))
            except Exception: pass
        if v_streams:
            v0 = v_streams[0]
            if v0.get("width") and v0.get("height"): add(b, T("画角"), f"{v0.get('width')} x {v0.get('height')}")
            add(b, T("映像コーデック"), v0.get("codec_name", ""))
            add(b, T("映像ビットレート"), fmt_bitrate(v0.get("bit_rate")) if v0.get("bit_rate") else T("不明"))
            if v0.get("pix_fmt"): add(b, T("色形式"), v0.get("pix_fmt"))
            if v0.get("color_space"): add(b, T("色空間"), v0.get("color_space"))
        if a_streams:
            a0 = a_streams[0]
            add(b, T("音声コーデック"), a0.get("codec_name", ""))
            if a0.get("bit_rate"): add(b, T("音声ビットレート"), fmt_bitrate(a0.get("bit_rate")))
            if a0.get("sample_rate"): add(b, T("サンプルレート"), a0.get("sample_rate"))
            if a0.get("channels"): add(b, T("チャンネル数"), a0.get("channels"))

        f = root(T("フォーマット"))
        add(f, T("コンテナ"), fmt.get("format_name", ""))
        add(f, T("コンテナ詳細"), fmt.get("format_long_name", ""))
        if fmt.get("duration"): add(f, T("長さ (秒)"), fmt.get("duration"))
        if fmt.get("bit_rate"): add(f, T("ビットレート"), fmt_bitrate(fmt.get("bit_rate")))
        add(f, T("ストリーム数"), fmt.get("nb_streams", ""))

        tags = fmt.get("tags", {}) or {}
        if tags:
            t = root(T("タグ(フォーマット)"))
            for k in sorted(tags.keys(), key=lambda x: str(x).lower()): add(t, k, tags.get(k, ""))

        for i, st in enumerate(streams):
            kind = T("音声") if st.get("codec_type") == "audio" else T("映像") if st.get("codec_type") == "video" else st.get("codec_type", "stream")
            r = root(f"{kind} {T('ストリーム #')}{i}")
            for label, key in [(T("コーデック"), "codec_name"), (T("コーデック詳細"), "codec_long_name"), (T("プロファイル"), "profile"), (T("幅"), "width"), (T("高さ"), "height"), (T("色形式"), "pix_fmt"), (T("サンプルレート"), "sample_rate"), (T("チャンネル数"), "channels"), (T("チャンネルレイアウト"), "channel_layout"), (T("ビットレート"), "bit_rate"), (T("時間ベース"), "time_base"), (T("フレームレート"), "r_frame_rate"), (T("平均フレームレート"), "avg_frame_rate")]:
                if key in st and st.get(key) not in (None, ""):
                    add(r, label, fmt_bitrate(st.get(key)) if key == "bit_rate" else st.get(key))
            st_tags = st.get("tags", {}) or {}
            if st_tags:
                rt = add(r, T("タグ"), "")
                for k in sorted(st_tags.keys(), key=lambda x: str(x).lower()): add(rt, k, st_tags.get(k, ""))

        tree.expandAll()
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(dialog.close)
        layout.addWidget(buttons)

        self.position_dialog_over_player(dialog, 980, 700)
        self.property_dialogs.append(dialog)
        dialog.destroyed.connect(lambda *_: self.property_dialogs.remove(dialog) if dialog in self.property_dialogs else None)
        dialog.show(); dialog.raise_(); dialog.activateWindow()

    def find_whisper_command(self):
        exe = shutil.which("whisper") or shutil.which("whisper.exe") or shutil.which("whisper.cmd") or shutil.which("whisper.bat")
        if exe:
            return exe, [], exe
        try:
            code = "import importlib.util, sys; sys.exit(0 if importlib.util.find_spec('whisper') else 1)"
            r = subprocess.run([sys.executable, "-c", code], capture_output=True, timeout=5)
            if r.returncode == 0:
                return sys.executable, ["-m", "whisper"], f"{sys.executable} -m whisper"
        except Exception as e:
            app_log(f"whisper module check failed: {e}")
        return None, [], ""

    def subtitle_whisper_language_for(self, path: Path) -> tuple[str, str]:
        lang = str(self.settings.value("subtitle/source_language", getattr(self, "subtitle_source_language", "auto")) or "auto").strip().lower()
        if not lang or lang in ("auto", "detect", "自動"):
            return "auto", T("Whisper自動判定")
        return lang, T("設定ファイル指定")

    def subtitle_translation_target(self) -> str:
        return str(self.settings.value("subtitle/target_language", getattr(self, "subtitle_target_language", "ja")) or "ja").strip().lower()

    def subtitle_language_label(self, lang: str) -> str:
        mapping = {"auto": "Auto", "ja": "日本語", "en": "English", "both": "Both"}
        return mapping.get(str(lang).strip().lower(), str(lang))

    def subtitle_output_paths(self, path: Path) -> tuple[Path, Path]:
        out_dir = self.app_base_dir() / "_conf" / "srt"
        return out_dir / f"{path.stem}.srt", out_dir / f"{path.stem}.srt2"

    def ollama_translate_text(self, text: str, target_lang: str, source_lang: str = "auto") -> str:
        if not text.strip():
            return text
        model = str(self.settings.value("subtitle/ollama_model", getattr(self, "ollama_model", "llama3.1")) or "llama3.1").strip()
        endpoint = str(self.settings.value("subtitle/ollama_endpoint", "http://127.0.0.1:11434/api/generate") or "").strip()
        prompt = (
            "Translate the following subtitle text only. "
            f"Source language: {source_lang}. Target language: {target_lang}. "
            "Keep meaning natural, keep line breaks, and return only the translated subtitle text.\n\n"
            + text
        )
        payload = json.dumps({"model": model, "prompt": prompt, "stream": False}, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(endpoint, data=payload, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=120) as response:
            data = json.loads(response.read().decode("utf-8", errors="replace") or "{}")
        translated = str(data.get("response", "")).strip()
        return translated or text

    def translate_srt_with_ollama(self, input_srt_path: Path, output_srt_path: Path, target_lang: str, source_lang: str = "auto") -> tuple[bool, str]:
        try:
            original = self.read_text_file_flexible(input_srt_path)
            blocks = re.split(r"\r?\n\s*\r?\n", original.strip())
            translated_blocks = []
            changed = 0
            for block in blocks:
                lines = [ln.rstrip() for ln in block.splitlines()]
                if not lines:
                    continue
                time_idx = next((i for i, ln in enumerate(lines) if "-->" in ln), -1)
                if time_idx < 0:
                    translated_blocks.append("\n".join(lines))
                    continue
                head = lines[:time_idx + 1]
                body = lines[time_idx + 1:]
                body_text = "\n".join(body).strip()
                if body_text:
                    translated = self.ollama_translate_text(body_text, target_lang, source_lang)
                    body = translated.splitlines() or body
                    changed += 1
                translated_blocks.append("\n".join(head + body))
            output_srt_path.write_text("\n\n".join(translated_blocks).rstrip() + "\n", encoding="utf-8", newline="\n")
            return True, f"Ollama translated {changed} subtitle block(s) to {target_lang}: {output_srt_path.name}"
        except (urllib.error.URLError, TimeoutError) as exc:
            return False, f"Ollama connection failed: {exc}"
        except Exception as exc:
            return False, f"Ollama translation failed: {exc}"

    def copy_srt_file(self, input_srt_path: Path, output_srt_path: Path):
        text = self.read_text_file_flexible(input_srt_path)
        output_srt_path.write_text(text, encoding="utf-8", newline="\n")

    def translate_or_copy_subtitle(self, input_srt_path: Path, output_srt_path: Path, target_lang: str, source_lang: str, log_edit: QPlainTextEdit | None = None) -> bool:
        normalized_source = str(source_lang or "auto").strip().lower()
        normalized_target = str(target_lang or "").strip().lower()
        try:
            if normalized_source and normalized_source != "auto" and normalized_source == normalized_target:
                self.copy_srt_file(input_srt_path, output_srt_path)
                message = f"Copied subtitle without translation: {output_srt_path.name}"
                app_log(message)
                if log_edit is not None:
                    log_edit.appendPlainText(message)
                return True
            ok, message = self.translate_srt_with_ollama(input_srt_path, output_srt_path, normalized_target, normalized_source)
            app_log(message)
            if log_edit is not None:
                log_edit.appendPlainText(message)
            return ok
        except Exception as exc:
            message = f"Subtitle output failed: {output_srt_path.name} / {exc}"
            app_log(message)
            if log_edit is not None:
                log_edit.appendPlainText(message)
            return False

    def suspected_subtitle_lines(self, srt_text: str) -> list[str]:
        T("""Whisperの幻聴字幕っぽい行を抽出する。""")
        suspicious_terms = [T("作曲"), T("作曲者"), T("李宗盛"), T("ご視聴ありがとうございました")]
        lines = []
        seen = {}
        for raw in srt_text.splitlines():
            line = raw.strip()
            if not line:
                continue
            if re.fullmatch(r"\d+", line):
                continue
            if "-->" in line:
                continue
            normalized = re.sub(r"\s+", "", line)
            if any(term in line for term in suspicious_terms):
                lines.append(raw)
                continue
            seen[normalized] = seen.get(normalized, 0) + 1
            if len(normalized) >= 6 and seen[normalized] >= 4:
                lines.append(raw)
        # 重複を保ったまま多すぎる場合は最大表示を抑える
        return lines

    def sanitize_srt_text(self, srt_text: str) -> tuple[str, int]:
        T("""怪しい字幕本文だけを除去し、SRT番号を振り直す。""")
        suspicious_terms = [T("作曲"), T("作曲者"), T("李宗盛"), T("ご視聴ありがとうございました")]
        blocks = re.split(r"\r?\n\s*\r?\n", srt_text.strip())
        cleaned_blocks = []
        removed = 0
        body_counts = {}
        for block in blocks:
            lines = [ln.rstrip() for ln in block.splitlines() if ln.strip()]
            if not lines:
                continue
            time_idx = next((i for i, ln in enumerate(lines) if "-->" in ln), -1)
            if time_idx < 0:
                continue
            time_line = lines[time_idx]
            body = lines[time_idx + 1:]
            keep_body = []
            for line in body:
                normalized = re.sub(r"\s+", "", line.strip())
                body_counts[normalized] = body_counts.get(normalized, 0) + 1
                bad = any(term in line for term in suspicious_terms)
                bad = bad or (len(normalized) >= 6 and body_counts[normalized] >= 4)
                if bad:
                    removed += 1
                else:
                    keep_body.append(line)
            if keep_body:
                cleaned_blocks.append([time_line] + keep_body)
        out = []
        for i, lines in enumerate(cleaned_blocks, 1):
            out.append(str(i))
            out.extend(lines)
            out.append("")
        return "\n".join(out).rstrip() + "\n", removed

    def request_subtitles(self, path: Path):
        T("""字幕変換条件を選んでから Whisper 実行へ進める。""")
        path = Path(path)
        dialog = QDialog(self)
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        dialog.setWindowTitle(f"{T('字幕依頼 - ')}{path.name}")
        dialog.setStyleSheet("""
            QDialog{background:#181818; color:#eee;}
            QLabel{color:#f0f0f0;}
            QComboBox{
                background:#101010; color:#f0f0f0; border:1px solid #444;
                padding:6px 10px; min-height:34px;
            }
            QPushButton{
                background:#2b2b2b; color:#fff; border:1px solid #666; border-radius:5px; padding:8px 16px;
            }
        """)
        layout = QVBoxLayout(dialog)
        header = QLabel(f"{T('字幕変換設定: ')}{path.name}")
        header.setStyleSheet("QLabel{font-weight:bold; font-size:14px;}")
        header.setWordWrap(True)
        layout.addWidget(header)

        info = QLabel(T("元言語と変換先を選んで『字幕変換』を押すと Whisper / Ollama 処理を開始します。"))
        info.setWordWrap(True)
        layout.addWidget(info)

        source_box = QComboBox()
        source_box.addItem("Auto", "auto")
        source_box.addItem("日本語", "ja")
        source_box.addItem("English", "en")
        source_box.setCurrentIndex(max(0, source_box.findData(self.subtitle_source_language)))

        target_box = QComboBox()
        target_box.addItem("日本語", "ja")
        target_box.addItem("English", "en")
        target_box.addItem("Both", "both")
        target_box.setCurrentIndex(max(0, target_box.findData(self.subtitle_target_language)))

        source_row = QHBoxLayout()
        source_row.addWidget(QLabel(T("元言語")))
        source_row.addWidget(source_box, 1)
        layout.addLayout(source_row)

        target_row = QHBoxLayout()
        target_row.addWidget(QLabel(T("字幕変換")))
        target_row.addWidget(target_box, 1)
        layout.addLayout(target_row)

        note = QLabel(T("Both を選ぶと .srt に日本語、.srt2 に English を保存します。"))
        note.setStyleSheet("QLabel{color:#8ec5ff;}")
        note.setWordWrap(True)
        layout.addWidget(note)

        buttons = QDialogButtonBox()
        run_button = buttons.addButton(T("字幕変換"), QDialogButtonBox.ButtonRole.AcceptRole)
        cancel_button = buttons.addButton(T("閉じる"), QDialogButtonBox.ButtonRole.RejectRole)
        layout.addWidget(buttons)

        def start_request():
            self.subtitle_source_language = str(source_box.currentData() or "auto")
            self.subtitle_target_language = str(target_box.currentData() or "ja")
            self.settings.setValue("subtitle/source_language", self.subtitle_source_language)
            self.settings.setValue("subtitle/target_language", self.subtitle_target_language)
            dialog.close()
            self.run_subtitle_request(path, self.subtitle_source_language, self.subtitle_target_language)

        run_button.clicked.connect(start_request)
        cancel_button.clicked.connect(dialog.close)
        self.position_dialog_over_player(dialog, 500, 240)
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def run_subtitle_request(self, path: Path, source_lang: str, target_lang: str):
        T("""Whisper を別プロセスで起動し、進捗ウィンドウに状態とログを表示する。""")
        path = Path(path)
        app_log(f"Subtitle request target: {path}")
        if not path.exists():
            QMessageBox.warning(self, T("ファイルなし"), f"ファイルが見つかりません。\n\n{path}")
            return

        program, prefix_args, command_desc = self.find_whisper_command()
        if not program:
            QMessageBox.information(self, T("Whisper未検出"), T("Whisper がInstallされていません。\n\n例:\n  pip install -U openai-whisper\n\nまたは whisper.exe をPATHに追加してください。"))
            app_log("whisper not found")
            return

        out_dir = self.app_base_dir() / "_conf" / "srt"
        try:
            out_dir.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            QMessageBox.warning(self, T("SRTフォルダ作成失敗"), f"SRT出力フォルダを作成できませんでした。\n\n{out_dir}\n\n{e}")
            return

        expected_srt, expected_srt2 = self.subtitle_output_paths(path)
        raw_srt = out_dir / f"{path.stem}.whisper_raw.srt"
        try:
            for stale in (expected_srt, expected_srt2, raw_srt):
                if stale.exists():
                    stale.unlink()
                    app_log(f"Old subtitle removed before request: {stale}")
        except Exception as e:
            QMessageBox.warning(self, T("古いSRT削除失敗"), f"古いSRTを削除できませんでした。\n\n{expected_srt}\n\n{e}")
            return

        lang = str(source_lang or "auto").strip().lower()
        lang_reason = T("依頼ダイアログ指定")
        # medium を既定にする。VRAM/時間は使うが、base/small より幻聴字幕を抑えやすい。
        whisper_args = [
            str(path),
            "--model", "medium",
            "--task", "transcribe",
            "--output_format", "srt",
            "--output_dir", str(out_dir),
            "--verbose", "True",
        ]
        if lang and lang != "auto":
            whisper_args[3:3] = ["--language", lang]
        all_args = prefix_args + whisper_args
        app_log("Whisper subtitle request: " + " ".join([command_desc] + whisper_args))

        dialog = QDialog(self)
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        dialog.setWindowTitle(f"{T('字幕依頼 - ')}{path.name}")
        dialog.setStyleSheet("""
            QDialog{background:#181818; color:#eee;}
            QPlainTextEdit{background:#101010; color:#e8e8e8; border:1px solid #333; font-family:Consolas, 'Yu Gothic UI'; font-size:9pt;}
            QProgressBar{background:#101010; color:#fff; border:1px solid #444; height:22px; text-align:center;}
            QProgressBar::chunk{background:#ff8a2a;}
            QLabel#WarnLabel{color:#ffcc66; font-weight:bold; padding:4px;}
            QPushButton{background:#2b2b2b; color:#fff; border:1px solid #666; border-radius:5px; padding:6px 14px;}
            QPushButton:disabled{color:#777; border-color:#444;}
        """)
        layout = QVBoxLayout(dialog)
        title = QLabel(f"{T('Whisperで字幕を作成中:\n')}{path.name}")
        title.setWordWrap(True)
        title.setStyleSheet("QLabel{font-weight:bold; padding:4px;}")
        layout.addWidget(title)
        target = QLabel(
            f"{T('対象: ')}{path}"
            f"{T('\n出力: ')}{expected_srt}"
            f"{(T(' / ') + str(expected_srt2)) if target_lang == 'both' else ''}"
            f"{T('\n元言語: ')}{self.subtitle_language_label(lang)} / {lang_reason}"
            f"{T('\n変換先: ')}{self.subtitle_language_label(target_lang)}"
            f"{T('\nモデル: medium')}"
        )
        target.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(target)
        progress = QProgressBar()
        progress.setRange(0, 0)
        progress.setFormat(T("起動準備中..."))
        layout.addWidget(progress)
        warn_label = QLabel("")
        warn_label.setObjectName("WarnLabel")
        warn_label.setWordWrap(True)
        warn_label.hide()
        layout.addWidget(warn_label)
        log_edit = QPlainTextEdit()
        log_edit.setReadOnly(True)
        log_edit.setMaximumBlockCount(4000)
        log_edit.appendPlainText(T("字幕作成を開始します。"))
        log_edit.appendPlainText("Command : " + command_desc + " " + " ".join(whisper_args))
        log_edit.appendPlainText("Input   : " + str(path))
        log_edit.appendPlainText("Output  : " + str(expected_srt) + (f" | {expected_srt2}" if target_lang == "both" else ""))
        log_edit.appendPlainText(f"Source  : {self.subtitle_language_label(lang)} ({lang_reason})")
        log_edit.appendPlainText(f"Target  : {self.subtitle_language_label(target_lang)}")
        log_edit.appendPlainText("Model   : medium")
        log_edit.appendPlainText(T("※ 古いSRTは依頼開始時に削除済みです。"))
        log_edit.appendPlainText("")
        layout.addWidget(log_edit, 1)
        buttons = QDialogButtonBox()
        cancel_button = buttons.addButton(T("中止"), QDialogButtonBox.ButtonRole.RejectRole)
        open_srt_button = buttons.addButton(T("SRTをメモ帳で開く"), QDialogButtonBox.ButtonRole.ActionRole)
        clean_srt_button = buttons.addButton(T("怪しい字幕行を除去して保存"), QDialogButtonBox.ButtonRole.ActionRole)
        close_button = buttons.addButton(T("閉じる"), QDialogButtonBox.ButtonRole.AcceptRole)
        open_srt_button.setEnabled(False)
        clean_srt_button.setEnabled(False)
        close_button.setEnabled(False)
        layout.addWidget(buttons)

        proc = QProcess(dialog)
        proc.setProgram(program)
        proc.setArguments(all_args)
        proc.setWorkingDirectory(str(path.parent))
        proc.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        env = QProcessEnvironment.systemEnvironment()
        env.insert("PYTHONUTF8", "1")
        env.insert("PYTHONIOENCODING", "utf-8")
        proc.setProcessEnvironment(env)

        def decode_process_data(data) -> str:
            raw = bytes(data)
            for enc in ("utf-8-sig", "utf-8", "cp932", "shift_jis"):
                try:
                    return raw.decode(enc)
                except Exception:
                    pass
            return raw.decode("utf-8", errors="replace")

        def read_text_flexible(file_path: Path) -> str:
            data = file_path.read_bytes()
            for enc in ("utf-8-sig", "utf-8", "cp932", "shift_jis"):
                try:
                    return data.decode(enc)
                except Exception:
                    pass
            return data.decode("utf-8", errors="replace")

        def append_output():
            data = decode_process_data(proc.readAllStandardOutput())
            if data:
                log_edit.moveCursor(QTextCursor.MoveOperation.End)
                log_edit.insertPlainText(data)
                log_edit.moveCursor(QTextCursor.MoveOperation.End)
                log_edit.verticalScrollBar().setValue(log_edit.verticalScrollBar().maximum())
                for line in data.splitlines():
                    app_log(f"[WHISPER] {line}")

        def started():
            progress.setFormat(T("Whisper実行中... mediumモデルで変換中"))
            log_edit.appendPlainText(T("Whisperプロセスを起動しました。"))
            log_edit.appendPlainText(T("変換ログはここに逐次表示します。何も出ない時間があっても medium モデルのロード中/解析中の可能性があります。\n"))
            app_log("Whisper process started")

        def finish_success_text():
            try:
                text = read_text_flexible(expected_srt)
                expected_srt.write_text(text, encoding="utf-8", newline="\n")
                return text
            except Exception as e:
                log_edit.appendPlainText(f"{T('\nSRT文字コード正規化に失敗: ')}{e}")
                app_log(f"SRT normalize failed: {e}")
                return ""

        def build_target_subtitles():
            if not expected_srt.exists():
                return
            try:
                text = read_text_flexible(expected_srt)
                raw_srt.write_text(text, encoding="utf-8", newline="\n")
            except Exception as exc:
                log_edit.appendPlainText(f"Raw SRT backup failed: {exc}")
                app_log(f"Raw SRT backup failed: {exc}")
                return
            if target_lang == "both":
                self.translate_or_copy_subtitle(raw_srt, expected_srt, "ja", lang, log_edit)
                self.translate_or_copy_subtitle(raw_srt, expected_srt2, "en", lang, log_edit)
            else:
                self.translate_or_copy_subtitle(raw_srt, expected_srt, target_lang, lang, log_edit)

        def finished(exit_code, status):
            append_output()
            progress.setRange(0, 100)
            if exit_code == 0 and expected_srt.exists():
                text = finish_success_text()
                build_target_subtitles()
                if expected_srt.exists():
                    text = read_text_flexible(expected_srt)
                suspicious = self.suspected_subtitle_lines(text) if text else []
                progress.setValue(100)
                progress.setFormat(T("完了"))
                log_edit.appendPlainText(T("\n完了しました。"))
                log_edit.appendPlainText("SRT : " + str(expected_srt))
                if expected_srt2.exists():
                    log_edit.appendPlainText("SRT2: " + str(expected_srt2))
                open_srt_button.setEnabled(True)
                if suspicious:
                    warn_label.setText(f"{T('幻聴字幕の可能性あり: 怪しい字幕行を ')}{len(suspicious)}{T(' 行検出しました。必要なら『怪しい字幕行を除去して保存』を押してください。')}")
                    warn_label.show()
                    clean_srt_button.setEnabled(True)
                    log_edit.appendPlainText(T("\n[警告] 幻聴字幕の可能性あり。検出例:"))
                    for line in suspicious[:30]:
                        log_edit.appendPlainText("  " + line)
                    if len(suspicious) > 30:
                        log_edit.appendPlainText(f"{T('  ... 他 ')}{len(suspicious) - 30}{T(' 行')}")
                    app_log(f"Whisper suspicious subtitles detected: {len(suspicious)}")
                else:
                    warn_label.setText(T("怪しい定型字幕は検出されませんでした。"))
                    warn_label.show()
                    clean_srt_button.setEnabled(False)
                app_log(f"Whisper completed: {expected_srt}" + (f", {expected_srt2}" if expected_srt2.exists() else ""))
                self.update_playlist_panel()
                if self.current_media_path() == path:
                    self.subtitle_display_mode = 1 if expected_srt.exists() else (2 if expected_srt2.exists() else 0)
                    self.subtitles_manually_hidden = False
                    self.load_subtitles_for(path)
            else:
                progress.setValue(0)
                progress.setFormat(T("失敗 / 中断"))
                log_edit.appendPlainText(f"{T('\n終了しました: exit_code=')}{exit_code}, status={status}")
                if not expected_srt.exists():
                    log_edit.appendPlainText(T("SRTファイルが見つかりません。Whisperのログを確認してください。"))
                app_log(f"[Whisper finished] exit_code={exit_code}, status={status}, expected={expected_srt}")
            cancel_button.setEnabled(False)
            close_button.setEnabled(True)

        def error_occurred(error):
            progress.setRange(0, 100)
            progress.setValue(0)
            progress.setFormat(T("起動失敗"))
            log_edit.appendPlainText(f"{T('\nWhisper起動エラー: ')}{error}")
            log_edit.appendPlainText(T("PATH上の whisper.exe / whisper.cmd、または python -m whisper を確認してください。"))
            cancel_button.setEnabled(False)
            close_button.setEnabled(True)
            app_log(f"[Whisper QProcess ERROR] {error}")

        def open_srt_in_notepad():
            if not expected_srt.exists():
                QMessageBox.information(dialog, T("SRT未作成"), f"SRTファイルはまだ作成されていません。\n\n{expected_srt}")
                return
            try:
                subprocess.Popen(["notepad.exe", str(expected_srt)])
                app_log(f"Open SRT in Notepad: {expected_srt}")
            except Exception as e:
                QMessageBox.warning(dialog, T("メモ帳起動失敗"), f"メモ帳でSRTを開けませんでした。\n\n{expected_srt}\n\n{e}")
                app_log(f"Open SRT failed: {e}")

        def clean_srt():
            if not expected_srt.exists():
                QMessageBox.information(dialog, T("SRT未作成"), f"SRTファイルはまだ作成されていません。\n\n{expected_srt}")
                return
            try:
                original = read_text_flexible(expected_srt)
                cleaned, removed = self.sanitize_srt_text(original)
                backup = expected_srt.with_suffix(".srt.bak")
                backup.write_text(original, encoding="utf-8", newline="\n")
                expected_srt.write_text(cleaned, encoding="utf-8", newline="\n")
                log_edit.appendPlainText(f"{T('\n怪しい字幕行を除去して保存しました: ')}{removed}{T(' 行削除')}")
                log_edit.appendPlainText(T("バックアップ: ") + str(backup))
                warn_label.setText(f"{T('怪しい字幕行を除去して保存しました（')}{removed}{T('行削除）。バックアップも保存済みです。')}")
                clean_srt_button.setEnabled(False)
                app_log(f"SRT sanitized: removed={removed}, file={expected_srt}, backup={backup}")
                if self.current_media_path() == path:
                    self.load_subtitles_for(path)
            except Exception as e:
                QMessageBox.warning(dialog, T("SRT除去保存失敗"), f"怪しい字幕行の除去に失敗しました。\n\n{expected_srt}\n\n{e}")
                app_log(f"SRT sanitize failed: {e}")

        def cancel():
            if proc.state() != QProcess.ProcessState.NotRunning:
                app_log("Whisper cancel requested")
                log_edit.appendPlainText(T("\n中止要求を送信しました..."))
                proc.kill()
            else:
                dialog.close()

        proc.started.connect(started)
        proc.readyReadStandardOutput.connect(append_output)
        proc.finished.connect(finished)
        proc.errorOccurred.connect(error_occurred)
        cancel_button.clicked.connect(cancel)
        open_srt_button.clicked.connect(open_srt_in_notepad)
        clean_srt_button.clicked.connect(clean_srt)
        close_button.clicked.connect(dialog.close)
        self.position_dialog_over_player(dialog, 820, 580)
        self.whisper_dialogs.append(dialog)
        dialog.destroyed.connect(lambda *_: self.whisper_dialogs.remove(dialog) if dialog in self.whisper_dialogs else None)
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()
        proc.start()

    def menu_style(self):
        return """
            QMenu { background-color:#151515; color:white; border:1px solid #333; font-size:13px; }
            QMenu::item { padding:6px 24px 6px 24px; }
            QMenu::item:selected { background-color:#333333; }
            QMenu::separator { height:1px; background:#505050; margin:6px 4px; }
        """

    def contextMenuEvent(self, event):
        menu = QMenu(self)
        menu.setStyleSheet(self.menu_style())

        if self.left_playlist_visible:
            # 左側リスト表示中は右クリック側のリストを抑止
            pass
        elif not self.playlist:
            action = QAction(T("曲がありません"), self)
            action.setEnabled(False)
            menu.addAction(action)
        else:
            list_widget = PlaylistMenuList()
            row_height = 31
            visible_rows = min(10, len(self.playlist))
            list_widget.setMinimumWidth(620)
            list_widget.setMaximumHeight(row_height * visible_rows + 6)
            for i, path in enumerate(self.playlist):
                number = f"{i + 1:02d}. "
                playing = "▶ " if i == self.current_index and self.one_shot_path is None else "   "
                text = playing + number + self.get_display_title(path)
                item = QListWidgetItem(text)
                item.setData(Qt.UserRole, i)
                item.setToolTip(str(path))
                item.setSizeHint(QSize(600, row_height))
                has_srt = bool(self.find_srt_for(path))
                has_srt2 = bool(self.find_srt2_for(path))
                if has_srt2:
                    item.setForeground(QColor("#36c96b"))
                    item.setToolTip(str(path) + T("\n字幕: 第2字幕あり"))
                elif has_srt:
                    item.setForeground(QColor("#58a6ff"))
                    item.setToolTip(str(path) + T("\n字幕: あり"))
                if i == self.current_index and self.one_shot_path is None:
                    item.setForeground(QColor("#ff9b45"))
                list_widget.addItem(item)
                if i == self.current_index and self.one_shot_path is None:
                    list_widget.setCurrentItem(item)
            list_action = QWidgetAction(menu)
            list_action.setDefaultWidget(list_widget)
            menu.addAction(list_action)

            def activate_index(idx: int):
                menu.close()
                self.play_index(idx, autoplay=True)
            list_widget.itemActivatedByIndex.connect(activate_index)
            list_widget.itemClicked.connect(lambda item: activate_index(int(item.data(Qt.UserRole))))

        menu.addSeparator()
        exit_action = QAction(T("終了"), self)
        exit_action.triggered.connect(self.exit_application)
        menu.addAction(exit_action)
        menu.exec(event.globalPos())

    def exit_application(self):
        app_log("Exit selected")
        self.exit_requested = True
        self.shutdown_remote_control()
        self.save_settings()
        if self.tray_icon is not None:
            self.tray_icon.hide()
        QApplication.quit()

    def clear_playlist(self):
        app_log("Clear playlist")
        self.player.stop()
        self.playlist.clear()
        self.playlist_search_text = ""
        self.drawer_open = False
        self.current_index = -1
        self.one_shot_path = None
        self.last_list_index_before_one_shot = -1
        self.one_shot_return_path: Path | None = None
        self.one_shot_return_index = -1
        self.one_shot_return_position = 0
        self.one_shot_return_was_playing = False
        self.pending_restore_position = 0
        self.restored_once = False
        self.subtitle_primary_cues = []
        self.subtitle_secondary_cues = []
        self.subtitle_cues = []
        self.subtitle_display_mode = 0
        self.subtitles_manually_hidden = False
        self.subtitle_overlay.set_cues([])
        self.update_subtitle_controls()
        self.title_label.setText(T("ここに音声ファイルをDrop"))
        self.art_title_label.setText(T("ここに音声ファイルをDrop"))
        self.one_shot_name_label.setText(T("ここに音声ファイルをDrop"))
        self.setWindowTitle("DropMp3")
        self.stop_random_art_mode(hide_notice=True)
        self.original_art_pixmap = QPixmap()
        self.art_source_pixmap = QPixmap()
        self.art_label.setPixmap(QPixmap())
        self.art_label.setText("Album Art")
        self.position_slider.setValue(0)
        self.position_slider.setRange(0, 0)
        self.current_time_label.setText("0:00")
        self.total_time_label.setText("0:00")
        self.update_small_time_label(0, 0)
        self.update_playlist_panel()
        self.update_playlist_toolbar_buttons()
        self.update_left_panel_visibility()
        self.update_random_art_pool()
        self.save_settings()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_F12:
            self.toggle_log_window()
            event.accept()
            return
        super().keyPressEvent(event)

    def toggle_log_window(self):
        if self.log_window.isVisible():
            app_log("Hide log window")
            self.log_window.hide()
        else:
            app_log("Show log window")
            self.log_window.show()
            self.log_window.raise_()
            self.log_window.activateWindow()

    def save_settings(self):
        if self.is_art_only_mode:
            if self.normal_geometry_before_small_mode:
                self.settings.setValue("geometry", self.normal_geometry_before_small_mode)
            self.settings.setValue("art_only_geometry", self.geometry())
        elif self.is_one_shot_panel_mode:
            if self.normal_geometry_before_small_mode:
                self.settings.setValue("geometry", self.normal_geometry_before_small_mode)
            self.settings.setValue("one_shot_geometry", self.geometry())
        else:
            self.settings.setValue("geometry", self.geometry())
        self.settings.setValue("log_geometry", self.log_window.geometry())
        self.settings.setValue("log_visible", self.log_window.isVisible())
        paths = [str(p) for p in self.playlist if p.exists()]
        self.settings.setValue("playlist_json", json.dumps(paths, ensure_ascii=False))
        self.settings.setValue("current_index", self.current_index)
        if self.one_shot_path is None:
            self.settings.setValue("position", int(self.player.position() or 0))
        self.settings.setValue("volume", float(self.audio.volume()))
        self.settings.setValue("one_shot_mode", self.one_shot_mode)
        self.settings.setValue("repeat_mode", self.repeat_mode)
        self.settings.setValue("repeat_current", self.repeat_current)
        self.settings.setValue("random_art_enabled", self.random_art_enabled)
        self.settings.setValue("subtitle/font", self.subtitle_font.toString())
        self.settings.setValue("subtitle/color", self.subtitle_color.name())
        self.settings.setValue("subtitle/auto_show", self.subtitle_auto_show_enabled)
        self.settings.setValue("subtitle/source_language", self.subtitle_source_language)
        self.settings.setValue("subtitle/target_language", self.subtitle_target_language)
        self.settings.setValue("subtitle/ollama_model", self.ollama_model)
        self.settings.setValue("drawer_open", self.drawer_open)
        self.settings.setValue("playlist_font_size", int(self.playlist_font_size))
        self.settings.setValue("volume_font_size", int(self.volume_font_size))
        self.settings.setValue("time_font_size", int(self.time_font_size))
        self.settings.setValue("title_font_size", int(self.title_font_size))
        self.settings.setValue("control_icon_scale", float(self.control_icon_scale))
        self.settings.setValue("playlist_order_mode", self.playlist_order_mode)
        self.settings.setValue("current_playlist_name", self.current_playlist_name)
        if hasattr(self, "main_splitter"):
            sizes = self.main_splitter.sizes()
            # 左ドロワーを閉じている時は left=0 になりやすいので、
            # その値で最後に調整したスプリッター位置を上書きしない。
            # 「左リストが実際に表示されていて、左右とも幅がある」時だけ保存する。
            try:
                if (
                    getattr(self, "left_playlist_visible", False)
                    and self.left_panel.isVisible()
                    and len(sizes) == 2
                    and int(sizes[0]) >= 80
                    and int(sizes[1]) >= 128
                ):
                    self.settings.setValue("main_splitter_sizes_json", json.dumps([int(sizes[0]), int(sizes[1])]))
                    self.settings.sync()
                    app_log(f"Saved splitter sizes: left={int(sizes[0])}, art={int(sizes[1])}")
            except Exception as e:
                app_log(f"[SETTINGS] splitter save failed: {e}")

    def restore_main_splitter_sizes_later(self):
        def restore():
            try:
                if not hasattr(self, "main_splitter"):
                    return
                raw = self.settings.value("main_splitter_sizes_json", "")
                if not raw:
                    return
                sizes = json.loads(raw)
                if isinstance(sizes, list) and len(sizes) == 2:
                    left = max(120, int(sizes[0]))
                    right = max(128, int(sizes[1]))
                    if left > 0 and right > 0:
                        self.main_splitter.setSizes([left, right])
                        app_log(f"Restored splitter sizes: left={left}, art={right}")
            except Exception as e:
                app_log(f"[SETTINGS] splitter restore failed: {e}")

        # ドロワー表示直後・レイアウト確定後の両方で復元する。
        QTimer.singleShot(0, restore)
        QTimer.singleShot(150, restore)
        QTimer.singleShot(500, restore)

    def load_settings(self):
        app_log("Load settings")
        self.update_startup_splash("設定とプレイリストを復元中...", 74)
        geo = self.settings.value("geometry")
        if geo:
            self.setGeometry(geo)
        log_geo = self.settings.value("log_geometry")
        if log_geo:
            self.log_window.setGeometry(log_geo)
        try:
            self.audio.setVolume(float(self.settings.value("volume", 0.8)))
        except Exception:
            self.audio.setVolume(0.8)
        try:
            self.playlist_font_size = max(8, min(28, int(self.settings.value("playlist_font_size", self.playlist_font_size))))
        except Exception:
            self.playlist_font_size = 12
        try:
            self.volume_font_size = max(8, min(28, int(self.settings.value("volume_font_size", self.volume_font_size))))
        except Exception:
            self.volume_font_size = 12
        try:
            self.time_font_size = max(8, min(28, int(self.settings.value("time_font_size", self.time_font_size))))
        except Exception:
            self.time_font_size = 12
        try:
            self.title_font_size = max(16, min(72, int(self.settings.value("title_font_size", self.title_font_size))))
        except Exception:
            self.title_font_size = 28
        try:
            self.control_icon_scale = max(0.7, min(2.5, float(self.settings.value("control_icon_scale", self.control_icon_scale))))
        except Exception:
            self.control_icon_scale = 1.0
        self.playlist_order_mode = str(self.settings.value("playlist_order_mode", "") or "")
        if self.playlist_order_mode not in ("shuffle", "filename"):
            self.playlist_order_mode = ""
        self.set_current_playlist_name(self.settings.value("current_playlist_name", self.current_playlist_name))
        self.apply_left_panel_style()
        self.apply_title_label_style()
        self.apply_control_icon_scale()
        if hasattr(self, "volume_label"):
            self.volume_label.set_display_font_size(self.volume_font_size)
        if hasattr(self, "current_time_label") and hasattr(self, "total_time_label"):
            self.current_time_label.set_display_font_size(self.time_font_size)
            self.total_time_label.set_display_font_size(self.time_font_size)
        self.update_startup_splash("字幕設定を読み込み中...", 78)
        font_str = self.settings.value("subtitle/font", "")
        if font_str:
            loaded_font = QFont()
            if loaded_font.fromString(str(font_str)):
                self.subtitle_font = loaded_font
        color_str = self.settings.value("subtitle/color", "#78ff91")
        color = QColor(str(color_str))
        if color.isValid():
            self.subtitle_color = color
        self.subtitle_auto_show_enabled = bool_from_settings(self.settings.value("subtitle/auto_show", True), True)
        self.subtitle_source_language = str(self.settings.value("subtitle/source_language", self.subtitle_source_language) or "auto")
        self.subtitle_target_language = str(self.settings.value("subtitle/target_language", self.subtitle_target_language) or "ja")
        self.ollama_model = str(self.settings.value("subtitle/ollama_model", self.ollama_model) or "llama3.1")
        self.apply_subtitle_style()
        self.update_volume_label()
        self.one_shot_mode = bool_from_settings(self.settings.value("one_shot_mode", False), False)
        self.one_shot_button.blockSignals(True)
        self.one_shot_button.setChecked(self.one_shot_mode)
        self.one_shot_button.blockSignals(False)
        self.random_art_enabled = bool_from_settings(self.settings.value("random_art_enabled", True), True)
        self.random_check.blockSignals(True)
        self.random_check.setChecked(self.random_art_enabled)
        self.random_check.blockSignals(False)
        self.update_random_art_button_style()
        repeat_mode = str(self.settings.value("repeat_mode", "")).lower()
        if repeat_mode not in ("off", "one", "all"):
            repeat_mode = "one" if bool_from_settings(self.settings.value("repeat_current", False), False) else "off"
        self.repeat_mode = repeat_mode
        self.update_repeat_button()
        self.drawer_open = bool_from_settings(self.settings.value("drawer_open", False), False)
        self.restore_main_splitter_sizes_later()

        self.update_startup_splash("保存済みプレイリストを確認中...", 82)
        try:
            paths = json.loads(self.settings.value("playlist_json", "[]"))
        except Exception:
            paths = []
        self.playlist = []
        for p in paths:
            path = Path(p)
            if path.exists() and path.suffix.lower() in AUDIO_EXTS:
                self.playlist.append(path)
        try:
            index = int(self.settings.value("current_index", -1))
        except Exception:
            index = -1
        try:
            position = int(self.settings.value("position", 0))
        except Exception:
            position = 0
        app_log(f"Playlist restored: {len(self.playlist)} file(s), index={index}, position={format_ms(position)}")
        self.update_startup_splash("プレイリストを表示中...", 88)
        self.update_playlist_panel()
        if self.playlist and 0 <= index < len(self.playlist):
            self.update_startup_splash("前回の曲を復元中...", 92)
            self.play_index(index, autoplay=False, restore_position=position)
        self.update_left_panel_visibility()
        if self.one_shot_mode:
            QTimer.singleShot(100, self.enter_one_shot_panel_mode)
        if bool_from_settings(self.settings.value("log_visible", False), False):
            self.log_window.show()


    def setup_remote_control(self):
        self.remote_server = RemoteControlServer(self, "DropMp3", 8765)
        self.remote_server.start()
        app = QApplication.instance()
        if app is not None:
            try:
                app.aboutToQuit.connect(self.shutdown_remote_control)
            except Exception:
                pass

    def shutdown_remote_control(self):
        server = getattr(self, "remote_server", None)
        if server is not None:
            try:
                server.shutdown()
            except Exception as exc:
                app_log(f"[REMOTE] shutdown skipped: {exc}")
            self.remote_server = None

    def open_remote_control_url(self):
        server = getattr(self, "remote_server", None)
        url = getattr(server, "url", "") or "http://127.0.0.1:8765/"
        app_log(f"[REMOTE] open remote control URL: {url}")
        QDesktopServices.openUrl(QUrl(url))

    def remote_state_text(self) -> str:
        state = self.player.playbackState()
        if state == QMediaPlayer.PlayingState:
            return T("再生中")
        if state == QMediaPlayer.PausedState:
            return T("一時停止")
        return T("停止")

    def remote_playlist_payload(self) -> dict:
        items = []
        for index, media in enumerate(self.playlist):
            try:
                title = self.get_display_title(media)
            except Exception:
                title = Path(media).stem
            items.append({
                "index": index,
                "title": str(title),
                "path": str(media),
                "current": bool(index == self.current_index and self.one_shot_path is None),
                "exists": bool(Path(media).exists()),
            })
        return {"ok": True, "count": len(items), "items": items}

    def remote_status_payload(self) -> dict:
        current = self.current_media_path()
        try:
            title = self.get_display_title(current) if current is not None else ""
        except Exception:
            title = Path(current).stem if current is not None else ""
        state = self.player.playbackState()
        if state == QMediaPlayer.PlayingState:
            state_key = "playing"
        elif state == QMediaPlayer.PausedState:
            state_key = "paused"
        else:
            state_key = "stopped"
        return {
            "ok": True,
            "app": "DropMp3",
            "state": state_key,
            "state_text": self.remote_state_text(),
            "index": int(self.current_index),
            "count": len(self.playlist),
            "title": str(title),
            "path": str(current or ""),
            "position_ms": int(self.player.position() or 0),
            "duration_ms": int(self.player.duration() or 0),
            "volume": float(self.audio.volume()),
            "remote_url": getattr(getattr(self, "remote_server", None), "url", ""),
        }

    def remote_set_position(self, ms: int):
        duration = max(0, int(self.player.duration() or 0))
        target = max(0, int(ms or 0))
        if duration > 0:
            target = min(target, duration)
        self.player.setPosition(target)
        if hasattr(self, "position_slider"):
            self.position_slider.setValue(target)
        if hasattr(self, "current_time_label"):
            self.current_time_label.setText(format_ms(target))
        self.update_small_time_label(target, duration)
        if hasattr(self, "subtitle_overlay"):
            self.subtitle_overlay.update_position(target)
        self.save_settings()

    def remote_set_volume(self, value):
        vol = float(value)
        if vol > 1.0:
            vol = vol / 100.0
        vol = max(0.0, min(1.0, vol))
        self.audio.setVolume(vol)
        self.update_volume_label()
        self.save_settings()

    def remote_handle_command(self, command: str, params: dict) -> dict:
        command = str(command or "").strip().lower()
        params = dict(params or {})
        if command == "status":
            return self.remote_status_payload()
        if command == "playlist":
            return self.remote_playlist_payload()
        if command == "play":
            raw_index = params.get("index", "")
            if str(raw_index).strip() != "":
                self.play_index(int(raw_index), autoplay=True)
            elif self.current_index < 0 and self.playlist and self.one_shot_path is None:
                self.play_index(0, autoplay=True)
            else:
                self.player.play()
            return self.remote_status_payload()
        if command == "pause":
            self.player.pause()
            return self.remote_status_payload()
        if command == "stop":
            self.player.stop()
            return self.remote_status_payload()
        if command == "toggle":
            self.toggle_play()
            return self.remote_status_payload()
        if command == "next":
            self.play_next()
            return self.remote_status_payload()
        if command == "prev":
            self.play_prev()
            return self.remote_status_payload()
        if command == "seek":
            self.remote_set_position(int(float(params.get("ms", params.get("value", 0)) or 0)))
            return self.remote_status_payload()
        if command == "volume":
            self.remote_set_volume(params.get("value", params.get("volume", 0)))
            return self.remote_status_payload()
        if command == "oneshot":
            raw_path = str(params.get("path", "") or "").strip()
            path = Path(raw_path) if raw_path else None
            if path is None or not path.exists() or path.suffix.lower() not in AUDIO_EXTS:
                return {"ok": False, "error": f"invalid path: {raw_path}"}
            self.play_one_shot(path, enter_panel=False)
            return self.remote_status_payload()
        if command == "show":
            self.restore_from_tray()
            return self.remote_status_payload()
        return {"ok": False, "error": f"unknown command: {command}"}

    def changeEvent(self, event):
        T("""通常Playerの最小化ボタンが押されたら、タスクトレイへ格納する。""")
        super().changeEvent(event)
        try:
            if event.type() == QEvent.Type.WindowStateChange and self.isMinimized():
                if not self.is_art_only_mode and not self.is_one_shot_panel_mode:
                    app_log("Window minimize button detected: minimize to tray")
                    # 最小化状態のままhideすると復帰時の状態が不安定になるため、いったん通常状態へ戻してから隠す。
                    QTimer.singleShot(0, self.showNormal)
                    QTimer.singleShot(0, self.minimize_to_tray)
        except Exception as e:
            app_log(f"[WINDOW] changeEvent minimize-to-tray failed: {e}")

    def closeEvent(self, event):
        """Close button hides the player and keeps the tray resident alive."""
        if not self.exit_requested:
            app_log("Window close intercepted: keep app resident in tray")
            event.ignore()
            self.minimize_to_tray()
            return

        app_log("Application closing by explicit exit")
        self.shutdown_remote_control()
        self.save_settings()
        try:
            self.stop_random_art_mode(hide_notice=True)
            self.player.stop()
            app_log("Player stopped by explicit exit")
        except Exception as e:
            app_log(f"[CLOSE] player.stop failed: {e}")
        if self.tray_icon is not None:
            self.tray_icon.hide()
        try:
            self.hide_auxiliary_windows_for_tray()
            self.log_window.close()
        except Exception:
            pass
        event.accept()


def main():
    startup_audio_files = collect_startup_audio_files(sys.argv[1:])
    if startup_audio_files and try_forward_one_shot_to_existing_instance(startup_audio_files):
        return

    startup_version = read_app_version(Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent)
    app_log("Application process started")
    app_log(f"Python: {sys.version}")
    app_log(f"Executable: {sys.executable}")
    app_log(f"Script: {Path(__file__).resolve()}")
    app_log(f"Working directory: {Path.cwd()}")
    qInstallMessageHandler(qt_message_handler)
    app_log("Qt message handler installed")
    sys.stdout = StreamBridge(sys.stdout, "STDOUT")
    sys.stderr = StreamBridge(sys.stderr, "STDERR")
    app_log("stdout/stderr bridge installed")
    app = QApplication(sys.argv)
    # トレイ格納中はウィンドウが非表示でも再生を継続できるようにする。
    app.setQuitOnLastWindowClosed(False)
    splash = StartupSplash(startup_version)
    splash.show()
    splash.update_status("起動準備中...", 5)

    # PyInstaller の --splash を使ってビルドした場合、
    # Python/Qt 側の詳細Splashが表示できた時点で、
    # bootloader側のSplashを閉じる。通常の python 実行では何もしない。
    try:
        import pyi_splash  # type: ignore
        pyi_splash.close()
        app_log("PyInstaller boot splash closed")
    except Exception:
        pass

    w = MiniDropPlayer(splash=splash)
    splash.update_status("メイン画面を表示中...", 98)
    w.show()
    if startup_audio_files:
        w.handle_startup_audio_files(startup_audio_files)
    splash.update_status("起動完了", 100)
    QTimer.singleShot(250, splash.close)
    app_log("Main window shown")
    code = app.exec()
    app_log(f"Application exited: code={code}")
    sys.exit(code)


if __name__ == "__main__":
    main()
