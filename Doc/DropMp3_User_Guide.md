# DropMp3 User Guide

Created: 2026-05-31  
Target version: i18n / Splash / Extended One-Shot / Playlist I/O / Multi-Selection build

## 1. What is DropMp3?

DropMp3 is a compact Windows music player that plays audio files by drag-and-drop.

It supports album-art display, playlist editing, subtitles, one-shot playback, mini player mode, system tray minimization, random jacket display, ffprobe properties, Whisper subtitle generation, playlist import/export, and drag-and-drop cooperation with other applications.

---

## 2. Starting DropMp3

### EXE version

Double-click `DropMp3.exe`.

In the OneFile distribution build, an early PyInstaller Splash may appear immediately after launch.

After that, DropMp3 shows its own startup progress Splash and then opens the main window.

### Python version

Install the required libraries and run:

```powershell
python .\dropMp3.py
```

To force the UI language:

```powershell
$env:DROPMP3_UI_LANG="ja"
python .\dropMp3.py

$env:DROPMP3_UI_LANG="en"
python .\dropMp3.py
```

---

## 3. Playing music files

Drop audio files onto the window to play them immediately.

Dropping multiple files adds them to the playlist.

Dropping a folder scans it and loads supported audio files.

Dropping onto the left playlist inserts files at the dropped position.

Dropping onto the jacket image area usually adds files to the end of the playlist.

---

## 4. Main supported audio files

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

---

## 5. Basic controls

### Play / Pause

Press the center play button to play.

Press it again while playing to pause.

You can also click the jacket image to toggle play / pause.

### Previous / Next

Use the buttons beside the play button to move to the previous or next track.

### Seek bar

Drag the seek bar at the bottom to change the playback position.

The current time is shown on the left, and the total duration is shown on the right.

---

## 6. Volume control

The current volume is displayed on the left side of the playback controls.

Hover over the volume label and use the mouse wheel to change volume.

You can also use the mouse wheel over the jacket image.

---

## 7. Left drawer playlist

Press the hamburger button on the left edge to open or close the playlist drawer.

Playlist operations:

- Click a track to play it
- `Ctrl + Click` to select multiple individual tracks
- `Shift + Click` to select a range
- Press Delete to remove selected tracks
- Remove multiple selected tracks at once
- Drag-and-drop to reorder tracks
- Move multiple selected tracks as a group
- Shuffle the playlist
- Sort by folder / file order
- Toggle repeat mode: `Off / One track / All tracks`
- Use the right-click menu for properties, subtitle request, subtitle check, and subtitle delete

The currently playing track is shown in orange.

Tracks with found subtitle files are shown in blue.

The bottom of the drawer shows the current track number and total count, such as `10/500`.

---

## 8. Clear and save playlist

The playlist clear and playlist save icons are placed on the left side of the title row.

### Clear playlist

Press the clear icon to show a confirmation dialog.

The playlist is cleared only after confirmation.

### Save playlist

Press the save icon to open a save dialog.

The file extension determines the output format.

```text
playlist.m3u8 → M3U8 format
playlist.wpl  → WPL format
```

If no extension is specified, DropMp3 adds one based on the selected dialog filter.

---

## 9. Loading playlist files

You can drop the following playlist files:

```text
.m3u
.m3u8
.wpl
.pls
.txt
.list
.playlist
```

Dropping a playlist file onto the left playlist inserts its tracks at the dropped position.

Dropping a playlist file onto the jacket image or main body shows a confirmation dialog.

- Add / Insert
- Replace / Insert
- Cancel

`Add / Insert` adds the tracks to the current playlist.

`Replace / Insert` replaces the current playlist.

`Cancel` does nothing.

---

## 10. Loading full-path text lists

`.txt`, `.list`, and `.playlist` can be read as multiline full-path lists.

Example:

```text
D:\Music\song1.mp3
D:\Music\song2.flac
"D:\Music\song with space.m4a"
```

Blank lines and lines beginning with `#` or `;` are ignored.

If full-path text is dragged directly from an editor, DropMp3 also tries to read it as a playlist.

---

## 11. Drag tracks to external apps

Dragging tracks from the left playlist to Explorer passes them as real files so they can be copied.

Dragging tracks to a text editor passes their full paths as text.

When multiple tracks are selected, DropMp3 passes multiple files and newline-separated full paths.

---

## 12. Adjusting the splitter

A splitter is placed between the left playlist and the jacket image.

Drag the splitter to adjust the width of the playlist and jacket image areas.

Window position, size, and splitter position are saved and restored on the next launch.

---

## 13. One-shot playback

Press the target-like icon on the right side to toggle one-shot playback mode.

When one-shot mode is active, dropped files are played temporarily without being added to the playlist.

If normal playback was active before one-shot playback, DropMp3 resumes it after about 0.3 seconds when the one-shot track ends.

---

## 14. Direct drop onto the one-shot icon

Both the normal window and mini player have a one-shot icon.

Drop an audio file directly onto the one-shot icon to play it as a one-shot.

When a dragged audio file enters the icon area, the icon expands to make the target easier to hit.

Tooltip text:

```text
このアイコンに音楽ファイルをDropするとワンショットで再生されます
Drop an audio file on this icon to play it as a one-shot.
```

---

## 15. Subtitles

If an `.srt` file with the same base name as the audio file exists, DropMp3 displays subtitles synchronized to playback time.

Search locations:

```text
Same folder as the audio file
srt folder beside the audio file
SRT folder beside the audio file
srt folder beside the EXE
SRT folder beside the EXE
```

SRT files can be read as UTF-8 or Shift_JIS.

The current subtitle line is shown in green, and surrounding lines are shown in white.

Press the `×` button at the top-right of the subtitle panel to close subtitles.

After closing, use the subtitle icon at the bottom-right of the jacket image to show them again.

---

## 16. Request / Check / Delete subtitles

Right-click a track in the left playlist to open the track menu.

```text
Properties
----------
Request subtitles
Check subtitles
Delete subtitles
```

### Request subtitles

If Whisper is installed, DropMp3 starts SRT subtitle generation for the selected audio file in a separate process.

A progress window is shown during processing.

### Check subtitles

If the matching `.srt` file is found, DropMp3 opens it in Notepad.

### Delete subtitles

If the matching `.srt` file is found, DropMp3 deletes it after confirmation.

---

## 17. Icon mode / mini player

Double-click the jacket image to switch to the compact mini player.

The mini player provides jacket image display, track title, play / pause, next track, font icon, and one-shot icon.

Double-click the mini player jacket image again to return to the normal window.

DropMp3 suppresses accidental single-click pause after returning by double-click.

---

## 18. System tray minimization

Press the minimize button on the normal player to hide it into the system tray.

Double-click the DropMp3 tray icon to restore the normal player.

---

## 19. Random jacket display

Enable `Random` on the title row to display random album-art images.

DropMp3 first shows the original image embedded in the current track, then switches to images from the playlist.

When music is paused, random image switching also pauses.

---

## 20. Context menus

Right-click the main window to show a simple playlist and exit menu.

When the left drawer is open, the right-click playlist is suppressed to avoid duplication.

Right-click a track in the left playlist to show actions for that track.

---

## 21. Gear menu

Use the gear icon on the right side to open management actions.

Main actions:

- Create WPL playlist file
- Create M3U8 playlist file
- Clear playlist
- Show / hide log window
- Sort and repeat operations

---

## 22. Log window

Press `F12` to show or hide the log window.

The log records startup information, Qt Multimedia / FFmpeg information, playback state, subtitle search information, and errors.

---

## 23. External tools

### ffprobe

Used by the Properties action in the playlist context menu.

It can show details such as audio format, bit rate, duration, tags, and embedded images.

### Whisper

Used by the Request subtitles action in the playlist context menu.

Generated `.srt` files are automatically detected later if they are saved with the same base name as the audio file.

---

## 24. Exiting DropMp3

Choose `Exit` from the right-click menu to close the app.

Window position, size, splitter position, playlist, current track, playback position, and drawer state are saved.
