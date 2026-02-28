#!/usr/bin/env python3
"""
Karaoke Pipeline - Stage 1: Vocal Separation
=============================================
Run in Google Colab (free GPU tier).
Separates vocals from instrumental using Demucs htdemucs model.

Usage:
    1. Upload your audio file to /content/
    2. Set INPUT_FILE below
    3. Runtime > Run All

Output:
    /content/output/vocals.wav       - Clean vocal stem
    /content/output/no_vocals.wav    - Instrumental stem (karaoke backing track)
"""

import os
import subprocess
import sys

# --- CONFIG -------------------------------------------------
INPUT_FILE = "/content/your_song.mp3"   # <-- change this
OUTPUT_DIR = "/content/output"
MODEL      = "htdemucs"                  # best quality; falls back to mdx_extra_q if OOM
# ------------------------------------------------------------

def install_deps():
    print("Installing demucs...")
    subprocess.run([sys.executable, "-m", "pip", "install", "demucs", "-q"], check=True)

def separate(input_file, output_dir, model=MODEL):
    os.makedirs(output_dir, exist_ok=True)
    print(f"Separating: {input_file} -> {output_dir} using {model}")
    result = subprocess.run(
        ["python3", "-m", "demucs",
         "--two-stems", "vocals",
         "-n", model,
         "-o", output_dir,
         input_file],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        print("STDERR:", result.stderr[-2000:])
        if model == "htdemucs":
            print("WARNING: htdemucs OOM -- retrying with mdx_extra_q (CPU-safe)")
            return separate(input_file, output_dir, model="mdx_extra_q")
        raise RuntimeError(f"Demucs failed: {result.stderr[-500:]}")
    print("Separation complete")
    return result

def find_stems(output_dir, model):
    import glob
    base = os.path.splitext(os.path.basename(INPUT_FILE))[0]
    pattern = os.path.join(output_dir, model, base, "*.wav")
    stems = glob.glob(pattern)
    return {os.path.splitext(os.path.basename(s))[0]: s for s in stems}

def flatten_outputs(output_dir, model):
    stems = find_stems(output_dir, model)
    import shutil
    for name, path in stems.items():
        dest = os.path.join(output_dir, f"{name}.wav")
        shutil.copy(path, dest)
        print(f"  {name}.wav -> {dest}")
    return stems

if __name__ == "__main__":
    install_deps()
    if not os.path.isfile(INPUT_FILE):
        raise FileNotFoundError(f"Input not found: {INPUT_FILE}")
    separate(INPUT_FILE, OUTPUT_DIR)
    stems = flatten_outputs(OUTPUT_DIR, MODEL)
    print("\nStems available:")
    for k, v in stems.items():
        print(f"  {k}: {v}")
    print("\nStage 1 complete. Run Stage 2 next.")
