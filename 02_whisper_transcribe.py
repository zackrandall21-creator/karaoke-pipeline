#!/usr/bin/env python3
"""
Karaoke Pipeline - Stage 2: Whisper Transcription
==================================================
Run in Google Colab (free GPU tier) after Stage 1.
Transcribes clean vocal stem with word-level timestamps.

Whisper params tuned for maximum karaoke accuracy (from nomadkaraoke research):
  - model=medium: good balance of accuracy vs speed
  - best_of=5: runs 5 hypotheses, picks best (conservative, not creative)
  - temperature=0.2: low randomness
  - no_speech_threshold=1: catches every word (very permissive)
  - enable_vad=True: Voice Activity Detection filters silence
  - condition_on_previous_text=True: context-aware

Usage:
    1. Set VOCALS_WAV and optionally LYRICS_PROMPT below
    2. Run after Stage 1 (needs /content/output/vocals.wav)
    3. Runtime > Run All

Output:
    /content/output/transcription.json   - Full Whisper output
    /content/output/words.json           - Flat word list with timestamps
    /content/output/transcription.txt    - Human-readable preview
"""

import os
import json
import subprocess
import sys

# --- CONFIG -------------------------------------------------
VOCALS_WAV    = "/content/output/vocals.wav"
OUTPUT_DIR    = "/content/output"
LYRICS_PROMPT = ""   # Optional: paste known lyrics here for forced alignment
                     # Example: "I was born a coal miners daughter..."
                     # Leave empty for blind transcription
# ------------------------------------------------------------

# Optimal Whisper params for karaoke transcription
# Source: nomadkaraoke/python-lyrics-transcriber whisper.py
WHISPER_PARAMS = {
    "model":                       "medium",
    "word_timestamps":             True,
    "temperature":                 0.2,
    "best_of":                     5,      # 5 hypotheses -> picks best
    "compression_ratio_threshold": 2.8,
    "no_speech_threshold":         1,      # Very permissive -- catches every word
    "condition_on_previous_text":  True,
    "enable_vad":                  True,
}

def install_deps():
    print("Installing whisper-timestamped...")
    subprocess.run([sys.executable, "-m", "pip", "install",
                    "whisper-timestamped", "openai-whisper", "-q"], check=True)

def transcribe(vocals_wav, output_dir, prompt=""):
    import whisper_timestamped as whisper

    os.makedirs(output_dir, exist_ok=True)

    print(f"Loading Whisper model: {WHISPER_PARAMS['model']}...")
    model = whisper.load_model(WHISPER_PARAMS["model"])

    print(f"Transcribing: {vocals_wav}")
    if prompt:
        print(f"  Using lyrics prompt ({len(prompt)} chars)")

    audio = whisper.load_audio(vocals_wav)
    result = whisper.transcribe(
        model,
        audio,
        language="en",
        initial_prompt=prompt if prompt else None,
        word_timestamps=WHISPER_PARAMS["word_timestamps"],
        temperature=WHISPER_PARAMS["temperature"],
        best_of=WHISPER_PARAMS["best_of"],
        compression_ratio_threshold=WHISPER_PARAMS["compression_ratio_threshold"],
        no_speech_threshold=WHISPER_PARAMS["no_speech_threshold"],
        condition_on_previous_text=WHISPER_PARAMS["condition_on_previous_text"],
        vad=WHISPER_PARAMS["enable_vad"],
    )

    # Save full JSON
    json_path = os.path.join(output_dir, "transcription.json")
    with open(json_path, "w") as f:
        json.dump(result, f, indent=2)
    print(f"  JSON saved: {json_path}")

    # Save flat word list
    words = []
    for seg in result.get("segments", []):
        for w in seg.get("words", []):
            words.append({
                "word":  w["text"].strip(),
                "start": round(w["start"], 3),
                "end":   round(w["end"], 3),
                "conf":  round(w.get("confidence", 1.0), 3),
            })

    words_path = os.path.join(output_dir, "words.json")
    with open(words_path, "w") as f:
        json.dump(words, f, indent=2)
    print(f"  Words saved: {words_path} ({len(words)} words)")

    # Plain text preview
    txt_path = os.path.join(output_dir, "transcription.txt")
    with open(txt_path, "w") as f:
        for w in words:
            f.write(f"{w['start']:6.2f}s  {w['word']}\n")
    print(f"  Preview saved: {txt_path}")

    return words

if __name__ == "__main__":
    install_deps()
    if not os.path.isfile(VOCALS_WAV):
        raise FileNotFoundError(f"Vocals not found: {VOCALS_WAV} -- run Stage 1 first")
    words = transcribe(VOCALS_WAV, OUTPUT_DIR, prompt=LYRICS_PROMPT)
    print(f"\nFirst 10 words:")
    for w in words[:10]:
        print(f"  {w['start']:5.2f}s -> {w['end']:5.2f}s  \"{w['word']}\"  ({w['conf']:.2f})")
    print("\nStage 2 complete. Run Stage 3 next.")
