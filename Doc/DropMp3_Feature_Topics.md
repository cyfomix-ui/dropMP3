# DropMp3 Feature Topics

Created: 2026-05-31  
Target version: i18n / Splash / Extended One-Shot / Playlist I/O / Multi-Selection build

## Overview

DropMp3 is a compact Windows music player centered around drag-and-drop operation.

It supports audio playback, album-art display, subtitles, playlist editing, mini player mode, system tray minimization, one-shot playback, random jacket display, ffprobe / Whisper integration, playlist import/export, and drag-and-drop cooperation with other applications.

---

## 1. Automatic Japanese / English UI switching

When the Windows display language is Japanese, DropMp3 uses Japanese UI text.

On non-Japanese Windows environments, it switches major UI labels, tooltips, dialogs, context menus, Whisper progress messages, and related messages to English.

You can also force the UI language with environment variables.

```powershell
$env:DROPMP3_UI_LANG="ja"
python .\dropMp3.py

$env:DROPMP3_UI_LANG="en"
python .\dropMp3.py
```

---

## 2. Startup Splash and progress display

DropMp3 shows a progress Splash while the main window is being prepared.

It displays startup steps such as restoring settings, checking the saved playlist, building the UI, and restoring the previous track.

For PyInstaller OneFile distribution, `--splash` can also be used to show an early Splash before Python / Qt startup completes.

---

## 3. Drag-and-drop instant playback

Drop audio files onto the window to play them immediately.

Dropping multiple files adds them to the playlist.

Dropping a folder scans it and adds supported audio files.

---

## 4. Supported audio files

Main supported extensions:

```text
.mp3
.wav
.flac
.ogg
.m4a
.aac
.wma
.aiff
.aif
```

Actual playback support depends on the Qt Multimedia / FFmpeg backend available on the system.

---

## 5. Playlist management

The left drawer can show the current playlist.

The currently playing track is highlighted in orange.
Tracks with detected subtitle files are shown in blue.

Main playlist operations:

- Click a track to play it
- `Ctrl + Click` to select multiple individual tracks
- `Shift + Click` to select a range
- Delete selected tracks with the Delete key
- Delete multiple selected tracks at once
- Reorder tracks by drag-and-drop
- Move multiple selected tracks as a group
- Shuffle
- Sort by folder / file order
- Repeat mode: `Off / One track / All tracks`
- Open properties from the list context menu
- Request subtitle generation
- Check subtitles
- Delete subtitles

---

## 6. Dropping playlist files

Exported playlist files can be dropped into DropMp3.

Supported playlist file types:

```text
.m3u
.m3u8
.wpl
.pls
.txt
.list
.playlist
```

`.txt`, `.list`, and `.playlist` are treated as plain text lists containing one full file path per line.

Example:

```text
D:\Music\song1.mp3
D:\Music\song2.flac
"D:\Music\song with space.m4a"
```

Blank lines and lines beginning with `#` or `;` are ignored.

---

## 7. Playlist drop position behavior

Dropping a playlist file onto the left playlist inserts its tracks at the dropped position.

Dropping a playlist file onto the jacket image or main body shows a confirmation dialog.

- Add / Insert
- Replace / Insert
- Cancel

This lets the user choose whether to append to the current playlist or replace it.

---

## 8. Playlist saving

The playlist save icon is placed on the left side of the title row.

The output format is selected by the file extension.

```text
playlist.m3u8 → Save as M3U8
playlist.wpl  → Save as WPL
```

If no extension is specified, DropMp3 adds one based on the selected file dialog filter.

---

## 9. Playlist clear

The playlist clear icon is placed on the left side of the title row.

It does not clear the list immediately. A confirmation dialog is shown first.

The playlist is cleared only when the user confirms.

---

## 10. Drag-and-drop to external applications

Dragging tracks from the playlist to Explorer passes them as actual files so they can be copied.

Dragging tracks to text editors passes the full file paths as text.

When multiple tracks are selected, DropMp3 passes multiple file URLs and newline-separated full paths.

---

## 11. Left drawer UI

DropMp3 uses a ChatGPT-like left drawer.

The drawer is opened and closed with the hamburger icon.

The playlist clear and save icons are placed on the title row, while the hamburger icon remains on the original vertical rail area.

The drawer open/closed state is saved.

---

## 12. Splitter support

A splitter is placed between the left playlist and the jacket image area.

You can widen the list or enlarge the jacket display.

The splitter position is saved and restored at the next launch.

---

## 13. Jacket image display

DropMp3 displays embedded album art from audio files.

The image is scaled as large as possible within the current window size.

The track title font size is 28px.

---

## 14. Mini player / icon mode

Double-clicking the jacket image switches to a compact mini player.

The mini player supports playback control, next track, time display, one-shot icon, and font icon.

When returning from mini player mode by double-clicking, DropMp3 suppresses the accidental single-click pause that can occur after the double-click event.

---

## 15. System tray minimization

Pressing the minimize button on the normal player can hide the app into the system tray instead of the taskbar.

Double-click the tray icon to restore the normal player.

Double-clicking the mini player returns to the normal player instead of sending it to the tray.

---

## 16. One-shot playback

The target-like icon toggles one-shot playback mode.

In one-shot playback, dropped audio is played temporarily without adding it to the playlist.

It is useful for checking samples, sound effects, and generated audio.

After one-shot playback ends, normal playback resumes after about 0.3 seconds.

---

## 17. Direct drop onto the one-shot icon

Both the normal window and mini player have a one-shot icon.

You can drop an audio file directly onto the one-shot icon to play it as a one-shot.

When an audio file is dragged over the icon, the icon expands temporarily to make the drop target easier to see.

Tooltip text:

```text
このアイコンに音楽ファイルをDropするとワンショットで再生されます
Drop an audio file on this icon to play it as a one-shot.
```

---

## 18. Subtitle display

DropMp3 automatically searches for `.srt` files with the same base name as the audio file and displays subtitles synchronized to playback time.

Search targets:

```text
Same folder as the audio file
srt / SRT folder beside the audio file
srt / SRT folder beside the EXE
```

SRT files can be read as UTF-8 or Shift_JIS.

The current subtitle line is shown in green, and surrounding lines are shown in white.

---

## 19. Check subtitles / Delete subtitles

The playlist context menu contains subtitle-related actions.

Menu order:

```text
Properties
----------
Request subtitles
Check subtitles
Delete subtitles
```

Check subtitles searches for the matching `.srt` file and opens it in Notepad if found.

Delete subtitles removes the matching subtitle file after a confirmation dialog.

---

## 20. ffprobe / Whisper integration

### Properties

If `ffprobe` is available, DropMp3 obtains media information for the selected track and shows it in a separate window.

### Request subtitles

If `Whisper` is available, DropMp3 starts SRT subtitle generation in a separate process.

A progress window shows the current processing status.

---

## 21. Volume, seek, and basic controls

DropMp3 supports play / pause, previous / next track, seek bar operation, and volume control with the mouse wheel.

You can adjust volume over the volume label or over the jacket image.

---

## 22. Random jacket display

When `Random` is enabled, DropMp3 can display album-art images from other tracks in the playlist.

It first shows the original image for the current track, then switches to random images at intervals.

---

## 23. Log window

Press `F12` to show the log window.

The log can show startup information, Python environment, Qt Multimedia / FFmpeg backend information, playback state, subtitle search information, and errors.

---

## 24. Intended use cases

DropMp3 is useful for:

- Checking AI-generated songs
- Organizing Suno / ACE-Step output
- Checking audio with SRT lyrics
- Temporarily checking sound effects
- Background music playback
- Listening to audio with embedded jacket images
- Passing file paths to other applications
- Drafting and rearranging playlists
