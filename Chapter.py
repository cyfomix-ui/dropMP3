import argparse
import subprocess
from pathlib import Path


DEFAULT_START_OFFSET_SECONDS = 0
DEFAULT_GAP_SECONDS = 0


def get_duration_seconds(file_path: str) -> float:
    cmd = [
        "ffprobe",
        "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        file_path,
    ]

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        check=True,
        encoding="utf-8",
        errors="replace",
    )

    return float(result.stdout.strip())


def format_time(seconds: float) -> str:
    total = int(seconds)
    h = total // 3600
    m = (total % 3600) // 60
    s = total % 60

    if h > 0:
        return f"{h}:{m:02d}:{s:02d}"

    return f"{m:02d}:{s:02d}"


def make_title(file_path: str) -> str:
    return Path(file_path).stem


def load_playlist(list_file: Path) -> list[str]:
    files = []

    for line in list_file.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()

        if not line:
            continue

        if line.startswith("#"):
            continue

        line = line.strip('"')
        files.append(line)

    return files


def make_chapters(list_file: Path, offset: float, gap: float) -> list[str]:
    files = load_playlist(list_file)

    current = float(offset)
    chapters = []

    for file_path in files:
        path = Path(file_path)

        if not path.exists():
            chapters.append(f"# NOT FOUND: {file_path}")
            continue

        title = make_title(file_path)
        chapters.append(f"{format_time(current)} {title}")

        duration = get_duration_seconds(str(path))
        current += duration + gap

    return chapters


def main():
    parser = argparse.ArgumentParser(
        description="フルパスが並んだリストファイルからYouTubeチャプターを作成します。"
    )

    parser.add_argument(
        "list_file",
        help="音楽ファイルのフルパスが1行ずつ並んだ .txt / .list / .playlist など",
    )

    parser.add_argument(
        "--offset",
        type=float,
        default=DEFAULT_START_OFFSET_SECONDS,
        help="開始オフセット秒。OBS録画開始から再生開始までのズレ補正用。",
    )

    parser.add_argument(
        "--gap",
        type=float,
        default=DEFAULT_GAP_SECONDS,
        help="曲間の空白秒数。",
    )

    args = parser.parse_args()

    list_file = Path(args.list_file)

    if not list_file.exists():
        raise FileNotFoundError(f"入力ファイルが見つかりません: {list_file}")

    output_file = list_file.with_suffix(".chp")

    chapters = make_chapters(
        list_file=list_file,
        offset=args.offset,
        gap=args.gap,
    )

    output_text = "\n".join(chapters)

    output_file.write_text(output_text, encoding="utf-8")

    print("===== YouTube Chapters =====")
    print(output_text)
    print("============================")
    print(f"出力しました: {output_file}")


if __name__ == "__main__":
    main()
