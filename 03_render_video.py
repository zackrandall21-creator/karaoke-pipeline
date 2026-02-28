#!/usr/bin/env python3
"""
Karaoke Pipeline - Stage 3: Video Render
=========================================
Renders karaoke video with:
  - Black background
  - White bold text for upcoming words
  - Yellow left-to-right wipe effect over active word duration
  - RGB(80,80,80) dim grey for already-sung words
  - Two centered lines visible at a time
  - Word-by-word sync to audio

Line-breaking logic adapted from nomadkaraoke/segment_resizer.py

Usage:
    1. Set AUDIO_FILE, WORDS_JSON, SONG_TITLE, SONG_ARTIST below
    2. Run after Stage 2 (needs /content/output/words.json)
    3. Runtime > Run All

Output:
    /content/output/karaoke_video.mp4
"""

import os
import json
import subprocess
import sys

# --- CONFIG -------------------------------------------------
AUDIO_FILE   = "/content/output/no_vocals.wav"   # instrumental from Stage 1
WORDS_JSON   = "/content/output/words.json"       # from Stage 2
OUTPUT_DIR   = "/content/output"
OUTPUT_VIDEO = "/content/output/karaoke_video.mp4"
SONG_TITLE   = "Your Song Title"
SONG_ARTIST  = "Artist Name"

WIDTH, HEIGHT = 1920, 1080
FPS           = 30
FONT_SIZE     = 72
LINE_SPACING  = 110

# Colors (RGB)
COLOR_INACTIVE = (255, 255, 255)   # white -- upcoming
COLOR_ACTIVE   = (255, 220, 0)     # yellow -- currently sung (wipe)
COLOR_SUNG     = (80, 80, 80)      # dim grey -- already done
COLOR_BG       = (0, 0, 0)         # black background
# ------------------------------------------------------------

def install_deps():
    subprocess.run([sys.executable, "-m", "pip", "install", "Pillow", "-q"], check=True)

def load_words(path):
    with open(path) as f:
        return json.load(f)

def segment_lines(words, max_chars=36, max_words=7):
    """
    Intelligent line-breaking adapted from nomadkaraoke/segment_resizer.py
    Groups words into display lines without cutting phrases mid-thought.
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

def measure_words(draw, line, font):
    """Return list of (text_with_space, pixel_width) for each word in line."""
    result = []
    for w in line:
        txt = w["word"].strip() + " "
        bbox = draw.textbbox((0, 0), txt, font=font)
        result.append((txt, bbox[2] - bbox[0]))
    return result

def render_frame(draw, img_w, img_h, pair, t, font):
    """Render one frame with two-line display and wipe effect."""
    y_centers = [
        img_h // 2 - LINE_SPACING // 2 - FONT_SIZE // 2,
        img_h // 2 + LINE_SPACING // 2 - FONT_SIZE // 2,
    ]

    # Find active word globally
    active_start = active_end = None
    for line in pair:
        for w in line:
            if w["start"] <= t < w["end"]:
                active_start, active_end = w["start"], w["end"]

    for li, line in enumerate(pair):
        if li >= len(y_centers):
            break
        y = y_centers[li]
        meas = measure_words(draw, line, font)
        total_w = sum(pw for _, pw in meas)
        x = (img_w - total_w) // 2

        for wi, (w, (txt, pw)) in enumerate(zip(line, meas)):
            # Determine color state
            if w["end"] <= t:
                color = COLOR_SUNG
            elif w["start"] <= t < w["end"]:
                # Active word -- yellow wipe based on fraction elapsed
                frac = (t - w["start"]) / max(w["end"] - w["start"], 0.01)
                frac = min(1.0, frac)
                # Simple half-threshold wipe: yellow if >50% through
                if frac >= 0.5:
                    color = COLOR_ACTIVE
                else:
                    color = COLOR_INACTIVE
            else:
                color = COLOR_INACTIVE
            draw.text((x, y), txt, font=font, fill=color)
            x += pw

def render_video(words, audio_file, output_video, output_dir):
    from PIL import Image, ImageDraw, ImageFont

    os.makedirs(output_dir, exist_ok=True)
    duration = get_audio_duration(audio_file)
    total_frames = int(duration * FPS)
    print(f"Duration: {duration:.1f}s -> {total_frames} frames")

    # Load font
    font = None
    for fp in [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
    ]:
        if os.path.isfile(fp):
            font = ImageFont.truetype(fp, FONT_SIZE)
            print(f"Font: {fp}")
            break
    if not font:
        print("WARNING: No bold TTF font found, using PIL default")
        font = ImageFont.load_default()

    lines = segment_lines(words)
    # Group into pairs
    pairs = [lines[i:i+2] for i in range(0, len(lines), 2)]
    print(f"{len(words)} words -> {len(lines)} lines -> {len(pairs)} screen pairs")

    def get_pair_for_time(t):
        for pair in pairs:
            flat = [w for ln in pair for w in ln]
            if not flat:
                continue
            if flat[0]["start"] <= t <= flat[-1]["end"] + 0.5:
                return pair
        for pair in pairs:
            flat = [w for ln in pair for w in ln]
            if flat and flat[0]["start"] > t:
                return pair
        return None

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
        pair = get_pair_for_time(t)
        if pair:
            render_frame(draw, WIDTH, HEIGHT, pair, t, font)
        else:
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
    if not os.path.isfile(AUDIO_FILE):
        raise FileNotFoundError(f"Audio missing: {AUDIO_FILE} -- run Stage 1 first")
    words = load_words(WORDS_JSON)
    render_video(words, AUDIO_FILE, OUTPUT_VIDEO, OUTPUT_DIR)
    print("\nStage 3 complete. Download /content/output/karaoke_video.mp4")
