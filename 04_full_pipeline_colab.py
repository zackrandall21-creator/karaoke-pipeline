#!/usr/bin/env python3
"""
Karaoke Pipeline - Full Pipeline (Convenience Script)
======================================================
Pulls all stage scripts from GitHub and runs them end-to-end.
Designed for single-cell execution in Google Colab.

Steps:
  1. Edit CONFIG block below
  2. Paste into a Colab cell and run

Requirements (Colab GPU runtime):
  - !apt-get install -y ffmpeg
  - !pip install demucs whisper-timestamped openai-whisper Pillow
"""

import subprocess, sys, os, json

# --- CONFIG -------------------------------------------------
INPUT_FILE    = "/content/your_song.mp3"   # <-- upload and set this
SONG_ARTIST   = "Artist Name"
SONG_TITLE    = "Song Title"
OUTPUT_DIR    = "/content/output"
LYRICS_PROMPT = ""   # Optional: paste full lyrics for best accuracy
# ------------------------------------------------------------

REPO_URL   = "https://github.com/zackrandall21-creator/karaoke-pipeline"
REPO_LOCAL = "/content/karaoke-pipeline"

# Pull latest scripts
if os.path.isdir(REPO_LOCAL):
    subprocess.run(["git", "-C", REPO_LOCAL, "pull", "--quiet"], check=True)
else:
    subprocess.run(["git", "clone", "--depth=1", REPO_URL, REPO_LOCAL], check=True)

sys.path.insert(0, REPO_LOCAL)
print(f"Pulled pipeline scripts from {REPO_URL}")

# Helper: exec a stage script with variable overrides
def run_stage(script_name, overrides=None):
    path = os.path.join(REPO_LOCAL, script_name)
    with open(path) as f:
        src = f.read()
    ns = dict(__name__="__main__")
    if overrides:
        ns.update(overrides)
    exec(compile(src, path, "exec"), ns)
    return ns

# Stage 1: Vocal Separation
print("\n" + "="*50)
print("STAGE 1: Vocal Separation")
print("="*50)
run_stage("01_demucs_separate.py", {
    "INPUT_FILE": INPUT_FILE,
    "OUTPUT_DIR": OUTPUT_DIR,
})

# Stage 2: Whisper Transcription
print("\n" + "="*50)
print("STAGE 2: Whisper Transcription")
print("="*50)
run_stage("02_whisper_transcribe.py", {
    "VOCALS_WAV":    os.path.join(OUTPUT_DIR, "vocals.wav"),
    "OUTPUT_DIR":    OUTPUT_DIR,
    "LYRICS_PROMPT": LYRICS_PROMPT,
})

# Stage 3: Render Video
print("\n" + "="*50)
print("STAGE 3: Video Render")
print("="*50)
run_stage("03_render_video.py", {
    "AUDIO_FILE":   os.path.join(OUTPUT_DIR, "no_vocals.wav"),
    "WORDS_JSON":   os.path.join(OUTPUT_DIR, "words.json"),
    "OUTPUT_DIR":   OUTPUT_DIR,
    "OUTPUT_VIDEO": os.path.join(OUTPUT_DIR, "karaoke_video.mp4"),
    "SONG_TITLE":   SONG_TITLE,
    "SONG_ARTIST":  SONG_ARTIST,
})

print("\nAll done! Download: /content/output/karaoke_video.mp4")
