#!/usr/bin/env python3
"""
Karaoke Pipeline - Stage 1: Vocal Separation (UPGRADED)
========================================================
Run in Kaggle Notebook (free GPU tier: T4 or P100).
Separates vocals from instrumental using BS-Roformer (MDX-Net) via
python-audio-separator — the current benchmark leader for vocal extraction
(SDR ~12.9dB), using only ~2-4GB VRAM vs ~7GB for htdemucs.

Upgrade rationale (2025):
  - BS-Roformer ViperX 1296 outperforms htdemucs on vocal isolation
  - Smaller model files (21-65MB vs 84-870MB for Demucs)
  - Leaves more VRAM for whisper-large-v3 in Stage 2
  - Falls back to htdemucs if audio-separator unavailable

Usage:
    1. Upload your audio file to /kaggle/working/ (or set INPUT_FILE)
    2. Runtime > Run All

Output:
    /kaggle/working/output/vocals.wav        - Clean vocal stem
    /kaggle/working/output/no_vocals.wav     - Instrumental stem (karaoke backing track)
"""

import os
import subprocess
import sys

# --- CONFIG -------------------------------------------------------------------
INPUT_FILE  = "/kaggle/working/song.mp3"   # <- change this
OUTPUT_DIR  = "/kaggle/working/output"
# ------------------------------------------------------------------------------


def install_deps():
    print("Installing python-audio-separator...")
    subprocess.run(
        [sys.executable, "-m", "pip", "install", "audio-separator[gpu]", "-q"],
        check=False  # gpu extras may warn; non-fatal
    )
    # Ensure ffmpeg available
    subprocess.run(["apt-get", "install", "-y", "-q", "ffmpeg"], check=False)


def separate_bs_roformer(input_file, output_dir):
    """
    Separate vocals using BS-Roformer ViperX 1296 (MDX-Net architecture).
    Best vocal SDR benchmark as of 2025. ~2-4GB VRAM on T4/P100.
    """
    from audio_separator.separator import Separator

    os.makedirs(output_dir, exist_ok=True)
    print(f"Separating: {input_file} -> {output_dir} using BS-Roformer ViperX 1296")

    sep = Separator(
        output_dir=output_dir,
        output_format="WAV",
        normalization_threshold=0.9,
        output_single_stem=None,   # output both stems
    )

    # Load best-in-class vocal model
    sep.load_model(model_filename="model_bs_roformer_ep_317_sdr_12.9755.ckpt")
    output_files = sep.separate(input_file)

    print(f"Separation complete: {output_files}")
    return output_files


def rename_stems(output_files, output_dir, input_file):
    """
    Normalize output filenames to vocals.wav / no_vocals.wav
    for compatibility with Stage 2.
    """
    import shutil

    vocals_dest = os.path.join(output_dir, "vocals.wav")
    instrumental_dest = os.path.join(output_dir, "no_vocals.wav")

    for f in output_files:
        fname = os.path.basename(f).lower()
        if "vocal" in fname and "instrument" not in fname and "no_vocal" not in fname:
            shutil.copy(f, vocals_dest)
            print(f"  vocals.wav <- {f}")
        elif "instrument" in fname or "no_vocal" in fname or "(instrumental)" in fname:
            shutil.copy(f, instrumental_dest)
            print(f"  no_vocals.wav <- {f}")

    return vocals_dest, instrumental_dest


def separate_fallback_demucs(input_file, output_dir):
    """
    Fallback: htdemucs if audio-separator unavailable.
    ~7GB VRAM — may OOM on T4; falls back to mdx_extra_q (CPU-safe) if needed.
    """
    import glob, shutil

    os.makedirs(output_dir, exist_ok=True)
    subprocess.run([sys.executable, "-m", "pip", "install", "demucs", "-q"], check=True)
    print(f"Fallback: Demucs htdemucs on {input_file}")

    result = subprocess.run(
        ["python3", "-m", "demucs", "--two-stems", "vocals", "-n", "htdemucs",
         "-o", output_dir, input_file],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        print("WARNING: htdemucs OOM -- retrying with mdx_extra_q")
        subprocess.run(
            ["python3", "-m", "demucs", "--two-stems", "vocals", "-n", "mdx_extra_q",
             "-o", output_dir, input_file],
            check=True
        )
        model_used = "mdx_extra_q"
    else:
        model_used = "htdemucs"

    base = os.path.splitext(os.path.basename(input_file))[0]
    pattern = os.path.join(output_dir, model_used, base, "*.wav")
    stems = glob.glob(pattern)

    import shutil
    for s in stems:
        name = os.path.splitext(os.path.basename(s))[0]
        dest = os.path.join(output_dir, f"{name}.wav")
        shutil.copy(s, dest)
        print(f"  {name}.wav -> {dest}")


if __name__ == "__main__":
    install_deps()

    if not os.path.isfile(INPUT_FILE):
        raise FileNotFoundError(f"Input not found: {INPUT_FILE}")

    try:
        output_files = separate_bs_roformer(INPUT_FILE, OUTPUT_DIR)
        vocals_path, instr_path = rename_stems(output_files, OUTPUT_DIR, INPUT_FILE)
    except Exception as e:
        print(f"WARNING: BS-Roformer failed ({e}), falling back to Demucs...")
        separate_fallback_demucs(INPUT_FILE, OUTPUT_DIR)

    # Verify outputs exist
    vocals = os.path.join(OUTPUT_DIR, "vocals.wav")
    no_vocals = os.path.join(OUTPUT_DIR, "no_vocals.wav")
    assert os.path.isfile(vocals), f"vocals.wav not found at {vocals}"
    assert os.path.isfile(no_vocals), f"no_vocals.wav not found at {no_vocals}"

    print(f"\nStage 1 complete.")
    print(f"  vocals.wav     -> {vocals}")
    print(f"  no_vocals.wav  -> {no_vocals}")
    print("\nRun Stage 2 next.")
