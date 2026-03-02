#!/usr/bin/env python3
"""
Karaoke Pipeline - Stage 3: Video Render (v5)
=============================================
v5 changes:
  - Audio track: uses the FULL MIX (vocals + instruments) so you can hear the voice
    to verify sync accuracy. Use no_vocals.wav for the final karaoke version.
  - Full-page layout: words fill the entire screen in large text
  - "Coming up" line: the NEXT line is shown dimmed below current, so you always
    know what words are coming
  - Silence detection: during vocal pauses > 1.5s, shows the next line preview
    with a subtle countdown indicator (e.g., "... 3s") so you know when vocals resume
  - Progressive left-to-right fill bar retained (from v4)
  - Bigger font (96pt vs 72pt) for full-page readability

Paths fixed for Kaggle (/kaggle/working/ instead of /content/).

Usage:
    1. Set SONG_TITLE, SONG_ARTIST below
    2. Run after Stage 2 (needs /kaggle/working/output/words.json)
    3. Runtime > Run All

Output:
    /kaggle/working/output/karaoke_video.mp4  (with vocals for sync check)
    /kaggle/working/output/karaoke_final.mp4  (instrumental only - real karaoke)
"""

import os
import json
import subprocess
import sys

# --- CONFIG -----------------------------------------------------------------------
AUDIO_WITH_VOCALS  = "/kaggle/working/song.mp3"                    # full mix (sync check)
AUDIO_INSTRUMENTAL = "/kaggle/working/output/no_vocals.wav"        # instrumental only
WORDS_JSON   = "/kaggle/working/output/words.json"
OUTPUT_DIR   = "/kaggle/working/output"
OUTPUT_VIDEO = "/kaggle/working/output/karaoke_video.mp4"           # with vocals (test)
OUTPUT_FINAL = "/kaggle/working/output/karaoke_final.mp4"           # instrumental (karaoke)
SONG_TITLE   = "Somedays"
SONG_ARTIST  = "Artist"

WIDTH, HEIGHT = 1920, 1080
FPS           = 30
FONT_SIZE     = 96     # bigger for full-page layout
LINE_SPACING  = 140    # vertical gap between lines
MAX_LINES     = 4      # max lines visible at once (full-page layout)
SILENCE_GAP   = 1.5    # seconds gap = show "coming up" countdown

# Colors (RGB)
COLOR_INACTIVE = (255, 255, 255)   # white -- upcoming
COLOR_ACTIVE   = (255, 220, 0)     # yellow -- currently sung (wipe)
COLOR_SUNG     = (80, 80, 80)      # dim grey -- already done
COLOR_UPCOMING = (160, 160, 180)   # blue-grey -- next line preview
COLOR_BG       = (0, 0, 0)        # black background
COLOR_PAUSE    = (120, 180, 255)   # light blue -- pause countdown
# ----------------------------------------------------------------------------------


def install_deps():
    subprocess.run([sys.executable, "-m", "pip", "install", "Pillow", "-q"], check=True)


def load_words(path):
    with open(path) as f:
        return json.load(f)


def segment_lines(words, max_chars=32, max_words=6):
    """
    Group words into display lines.
    Smaller max_chars/max_words than before since font is bigger.
    """
    lines, current, chars = [], [], 0
    for word in words:
        wt = word["word"].strip()
        if not wt:
            continue
        projected = chars + len(wt) + (1 if current else 0)
        if current and (projected > max_chars or len(current) >= max_words):
            lines.append(current)
            current, chars = [word], len(wt)
        else:
            current.append(word)
            chars = projected
    if current:
        lines.append(current)
    return lines


def get_audio_duration(audio_file):
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", audio_file],
        capture_output=True, text=True
    )
    return float(r.stdout.strip())


def measure_line_width(draw, line, font):
    """Return total pixel width of a line of words."""
    total = 0
    for w in line:
        txt = w["word"].strip() + " "
        bbox = draw.textbbox((0, 0), txt, font=font)
        total += bbox[2] - bbox[0]
    return total


def render_frame(draw, img_w, img_h, lines, active_line_idx, t, font, font_small):
    """
    Render one frame with full-page layout:
    - Up to MAX_LINES lines visible
    - Active line highlighted with progressive fill
    - Next line shown in upcoming color below
    - Already-sung lines shown in dim grey
    """
    # Center the visible block vertically
    num_visible = min(MAX_LINES, len(lines))
    total_block_h = num_visible * LINE_SPACING
    y_start = (img_h - total_block_h) // 2

    # Determine which lines to show: center active line in view
    if active_line_idx is None:
        # No active line (silence) - show upcoming lines preview
        start_idx = 0
        show_lines = lines[:num_visible]
    else:
        # Try to center active line
        half = num_visible // 2
        start_idx = max(0, active_line_idx - half)
        end_idx = start_idx + num_visible
        if end_idx > len(lines):
            end_idx = len(lines)
            start_idx = max(0, end_idx - num_visible)
        show_lines = lines[start_idx:end_idx]

    for li, line in enumerate(show_lines):
        line_idx = start_idx + li
        y = y_start + li * LINE_SPACING

        # Measure line for centering
        total_w = 0
        word_widths = []
        for w in line:
            txt = w["word"].strip() + " "
            bbox = draw.textbbox((0, 0), txt, font=font)
            pw = bbox[2] - bbox[0]
            word_widths.append((w, txt, pw))
            total_w += pw
        x = (img_w - total_w) // 2

        for w, txt, pw in word_widths:
            if active_line_idx is None:
                # Silence period — show all as upcoming
                color = COLOR_UPCOMING
                draw.text((x, y), txt, font=font, fill=color)
            elif line_idx < active_line_idx:
                # Already sung line
                draw.text((x, y), txt, font=font, fill=COLOR_SUNG)
            elif line_idx > active_line_idx:
                # Upcoming line
                draw.text((x, y), txt, font=font, fill=COLOR_UPCOMING)
            else:
                # Active line — word-by-word progressive fill
                if w["end"] <= t:
                    color = COLOR_SUNG
                    draw.text((x, y), txt, font=font, fill=color)
                elif w["start"] <= t < w["end"]:
                    # Progressive yellow fill left-to-right
                    frac = (t - w["start"]) / max(w["end"] - w["start"], 0.01)
                    frac = min(1.0, frac)
                    fill_px = int(pw * frac)

                    # Draw white base (full word)
                    draw.text((x, y), txt, font=font, fill=COLOR_INACTIVE)
                    # Clip yellow fill over it using a temporary image
                    # We use a simple approach: draw yellow on a separate pass
                    # by rendering the text twice and masking — but PIL doesn't support
                    # proper clipping, so we use a character-width approximation:
                    # Render each character progressively
                    cx = x
                    for ch in txt:
                        ch_bbox = draw.textbbox((0, 0), ch, font=font)
                        ch_w = ch_bbox[2] - ch_bbox[0]
                        if cx + ch_w // 2 <= x + fill_px:
                            draw.text((cx, y), ch, font=font, fill=COLOR_ACTIVE)
                        else:
                            draw.text((cx, y), ch, font=font, fill=COLOR_INACTIVE)
                        cx += ch_w
                else:
                    draw.text((x, y), txt, font=font, fill=COLOR_INACTIVE)
            x += pw


def get_active_line_for_time(lines, t):
    """Return (line_idx, is_silence, seconds_to_next) for time t."""
    for li, line in enumerate(lines):
        flat_start = line[0]["start"]
        flat_end = line[-1]["end"]
        if flat_start <= t <= flat_end + 0.1:
            return li, False, 0
    # In a gap — find next line
    for li, line in enumerate(lines):
        if line[0]["start"] > t:
            return None, True, line[0]["start"] - t
    return None, True, 0


def render_video(words, audio_file, output_video):
    from PIL import Image, ImageDraw, ImageFont

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    duration = get_audio_duration(audio_file)
    total_frames = int(duration * FPS)
    print(f"Duration: {duration:.1f}s -> {total_frames} frames")

    # Load fonts
    font = None
    font_small = None
    for fp in [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
    ]:
        if os.path.isfile(fp):
            font = ImageFont.truetype(fp, FONT_SIZE)
            font_small = ImageFont.truetype(fp, 36)
            print(f"Font: {fp}")
            break
    if not font:
        print("WARNING: No bold TTF font found, using PIL default")
        font = ImageFont.load_default()
        font_small = font

    lines = segment_lines(words)
    print(f"{len(words)} words -> {len(lines)} lines")

    # Pipe raw frames into ffmpeg
    cmd = [
        "ffmpeg", "-y",
        "-f", "rawvideo", "-vcodec", "rawvideo",
        "-s", f"{WIDTH}x{HEIGHT}", "-pix_fmt", "rgb24", "-r", str(FPS),
        "-i", "pipe:0",
        "-i", audio_file,
        "-c:v", "libx264", "-preset", "fast", "-crf", "18",
        "-c:a", "aac", "-b:a", "192k", "-shortest",
        output_video
    ]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)

    for fn in range(total_frames):
        t = fn / FPS
        img = Image.new("RGB", (WIDTH, HEIGHT), COLOR_BG)
        draw = ImageDraw.Draw(img)

        line_idx, is_silence, time_to_next = get_active_line_for_time(lines, t)

        if is_silence and time_to_next > 0:
            # Show next-up line preview + countdown
            render_frame(draw, WIDTH, HEIGHT, lines, None, t, font, font_small)
            # Countdown
            if time_to_next > 0.3:
                countdown_txt = f"vocals in {time_to_next:.1f}s" if time_to_next > 2 else "..."
                bbox = draw.textbbox((0, 0), countdown_txt, font=font_small)
                cx = (WIDTH - (bbox[2] - bbox[0])) // 2
                draw.text((cx, HEIGHT - 80), countdown_txt, font=font_small, fill=COLOR_PAUSE)
        elif line_idx is not None:
            render_frame(draw, WIDTH, HEIGHT, lines, line_idx, t, font, font_small)
        else:
            # Before first word or after last word
            draw.text((WIDTH//2 - 300, HEIGHT//2 - FONT_SIZE//2),
                      f"{SONG_ARTIST} -- {SONG_TITLE}", font=font, fill=COLOR_INACTIVE)

        proc.stdin.write(img.tobytes())
        if fn % (FPS * 15) == 0:
            print(f"  {fn/total_frames*100:.0f}%  t={t:.0f}s")

    proc.stdin.close()
    proc.wait()
    if proc.returncode != 0:
        raise RuntimeError("ffmpeg render failed")

    mb = os.path.getsize(output_video) / 1e6
    print(f"\nVideo done: {output_video} ({mb:.1f} MB)")


if __name__ == "__main__":
    install_deps()
    if not os.path.isfile(WORDS_JSON):
        raise FileNotFoundError(f"words.json missing: {WORDS_JSON} -- run Stage 2 first")

    words = load_words(WORDS_JSON)

    # Render WITH vocals (for sync verification)
    audio_src = AUDIO_WITH_VOCALS if os.path.isfile(AUDIO_WITH_VOCALS) else AUDIO_INSTRUMENTAL
    print(f"Rendering with audio: {audio_src}")
    render_video(words, audio_src, OUTPUT_VIDEO)

    # Also render instrumental-only version (real karaoke)
    if os.path.isfile(AUDIO_INSTRUMENTAL) and audio_src != AUDIO_INSTRUMENTAL:
        print("\nAlso rendering instrumental-only version...")
        render_video(words, AUDIO_INSTRUMENTAL, OUTPUT_FINAL)

    print("\nStage 3 complete.")
    print(f"  Sync check (with vocals): {OUTPUT_VIDEO}")
    print(f"  Karaoke (instrumental):   {OUTPUT_FINAL}")
