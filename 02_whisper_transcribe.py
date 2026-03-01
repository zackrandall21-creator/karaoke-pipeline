#!/usr/bin/env python3
"""
Karaoke Pipeline - Stage 2: Transcription + Forced Alignment (UPGRADED)
========================================================================
Run in Kaggle Notebook after Stage 1.

Upgraded pipeline:
  1. whisper-large-v3 for best lyrics transcription accuracy
     - Significant improvement over 'medium' on sung vocals
     - ~10GB VRAM while loaded (T4 fits; unloaded before aligner)
  2. ctc-forced-aligner (MMS-300M) for precise word boundary timing
     - Replaces Whisper's internal word_timestamps for alignment
     - Forces Whisper's text onto the clean vocal stem waveform
     - Achieves ~10-50ms word boundary accuracy vs ~100-300ms from Whisper alone
     - Uses Meta's MMS-300M model (HuggingFace: MahmoudAshraf/mms-300m-1130-forced-aligner)
     - Only ~2GB VRAM — loaded AFTER Whisper is unloaded

Whisper params tuned for karaoke accuracy (nomadkaraoke research):
  - model=large-v3: best transcription for singing
  - best_of=5: 5 hypotheses, picks best (conservative, not creative)
  - temperature=0.2: low randomness
  - no_speech_threshold=1: very permissive, catches every word
  - enable_vad=True: Voice Activity Detection filters silence
  - condition_on_previous_text=True: context-aware

Usage:
    1. Set VOCALS_WAV and optionally LYRICS_PROMPT below
    2. Run after Stage 1 (needs vocals.wav)
    3. Runtime > Run All

Output:
    /kaggle/working/output/transcription.json   - Full Whisper output
    /kaggle/working/output/words.json            - Flat word list with ALIGNED timestamps
    /kaggle/working/output/transcription.txt     - Human-readable preview
    /kaggle/working/output/alignment_method.txt  - Which method was used
"""

import os
import json
import subprocess
import sys
import gc

# --- CONFIG -------------------------------------------------------------------
VOCALS_WAV    = "/kaggle/working/output/vocals.wav"
OUTPUT_DIR    = "/kaggle/working/output"
LYRICS_PROMPT = ""   # Optional: paste known lyrics here for better accuracy
                      # Example: "I was born a coal miners daughter..."
                      # Leave empty for blind transcription
# ------------------------------------------------------------------------------

# Whisper params tuned for karaoke (source: nomadkaraoke/python-lyrics-transcriber)
WHISPER_PARAMS = {
    "model":                       "large-v3",  # UPGRADED from medium
    "word_timestamps":              True,
    "temperature":                  0.2,
    "best_of":                      5,
    "compression_ratio_threshold":  2.8,
    "no_speech_threshold":          1,          # Very permissive -- catches every word
    "condition_on_previous_text":   True,
    "enable_vad":                   True,
}


def install_deps():
    print("Installing whisper-timestamped + ctc-forced-aligner...")
    subprocess.run(
        [sys.executable, "-m", "pip", "install",
         "whisper-timestamped", "openai-whisper",
         "ctc-forced-aligner", "transformers", "torch",
         "-q"],
        check=True
    )


def transcribe_whisper(vocals_wav, prompt=""):
    """
    Step 1: Transcribe with whisper-large-v3.
    Returns (words_list, raw_text) — timestamps are from Whisper internal
    alignment and will be replaced by ctc-forced-aligner in step 2.
    """
    import whisper_timestamped as whisper

    print(f"Loading Whisper {WHISPER_PARAMS['model']}...")
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

    # Extract flat word list
    words = []
    for seg in result.get("segments", []):
        for w in seg.get("words", []):
            words.append({
                "word":  w["text"].strip(),
                "start": round(w["start"], 3),
                "end":   round(w["end"], 3),
                "conf":  round(w.get("confidence", 1.0), 3),
            })

    # Build plain text transcript for aligner
    raw_text = " ".join(w["word"] for w in words)

    print(f"  Transcribed {len(words)} words")

    # CRITICAL: Unload model to free ~10GB VRAM before running aligner
    del model
    del audio
    gc.collect()
    try:
        import torch
        torch.cuda.empty_cache()
        print("  Whisper model unloaded, VRAM freed for aligner")
    except Exception:
        pass

    return words, raw_text, result


def align_with_ctc(vocals_wav, transcript_text, whisper_words):
    """
    Step 2: Re-align Whisper's transcript to the audio waveform using
    ctc-forced-aligner (MMS-300M). Replaces Whisper word timestamps
    with acoustically-grounded boundaries — especially important for
    sung/held vowels which Whisper often timestamps too early/late.

    Returns aligned word list with corrected start/end times.
    """
    try:
        import torch
        from ctc_forced_aligner import (
            load_audio, load_alignment_model,
            generate_emissions, get_alignments,
            get_spans, postprocess_results,
        )

        print("Running ctc-forced-aligner (MMS-300M)...")
        device = "cuda" if torch.cuda.is_available() else "cpu"
        print(f"  Device: {device}")

        # Load aligner model (~2GB VRAM)
        alignment_model, alignment_tokenizer = load_alignment_model(
            device,
            dtype=torch.float16 if device == "cuda" else torch.float32,
        )

        audio_waveform = load_audio(vocals_wav, alignment_model.dtype, device)
        emissions, stride = generate_emissions(
            alignment_model, audio_waveform, batch_size=8
        )

        del alignment_model  # free VRAM after emissions
        gc.collect()
        if device == "cuda":
            torch.cuda.empty_cache()

        # Tokenize at word level
        tokens_starred, text_starred = (
            alignment_tokenizer(transcript_text, return_tensors="pt", padding=True)
        )

        segments, scores, blank_token = get_alignments(
            emissions,
            tokens_starred,
            alignment_tokenizer,
        )
        spans = get_spans(tokens_starred, segments, blank_token)
        word_timestamps = postprocess_results(text_starred, spans, stride, scores)

        # Build corrected word list
        aligned_words = []
        for item in word_timestamps:
            aligned_words.append({
                "word":  item["label"],
                "start": round(item["start"], 3),
                "end":   round(item["end"], 3),
                "conf":  round(item.get("score", 1.0), 3),
                "source": "ctc_forced_aligner",
            })

        print(f"  Aligned {len(aligned_words)} words with ctc-forced-aligner")
        return aligned_words, "ctc_forced_aligner"

    except Exception as e:
        print(f"WARNING: ctc-forced-aligner failed ({e})")
        print("  Falling back to Whisper internal word_timestamps (still good quality)")
        # Mark source on existing words
        for w in whisper_words:
            w["source"] = "whisper_word_timestamps"
        return whisper_words, "whisper_word_timestamps"


def save_outputs(output_dir, whisper_result, aligned_words, alignment_method):
    os.makedirs(output_dir, exist_ok=True)

    # Full Whisper JSON
    json_path = os.path.join(output_dir, "transcription.json")
    with open(json_path, "w") as f:
        json.dump(whisper_result, f, indent=2)
    print(f"  Full JSON: {json_path}")

    # Aligned word list (used by Stage 3)
    words_path = os.path.join(output_dir, "words.json")
    with open(words_path, "w") as f:
        json.dump(aligned_words, f, indent=2)
    print(f"  Words JSON: {words_path} ({len(aligned_words)} words)")

    # Human-readable preview
    txt_path = os.path.join(output_dir, "transcription.txt")
    with open(txt_path, "w") as f:
        for w in aligned_words:
            f.write(f"{w['start']:6.2f}s  {w['word']}\n")
    print(f"  Preview: {txt_path}")

    # Record which alignment method was used
    method_path = os.path.join(output_dir, "alignment_method.txt")
    with open(method_path, "w") as f:
        f.write(alignment_method + "\n")
    print(f"  Alignment method: {alignment_method}")


if __name__ == "__main__":
    install_deps()

    if not os.path.isfile(VOCALS_WAV):
        raise FileNotFoundError(f"Vocals not found: {VOCALS_WAV} -- run Stage 1 first")

    # Step 1: Transcribe with Whisper large-v3
    whisper_words, raw_text, full_result = transcribe_whisper(VOCALS_WAV, prompt=LYRICS_PROMPT)

    # Step 2: Refine word boundaries with ctc-forced-aligner
    aligned_words, alignment_method = align_with_ctc(VOCALS_WAV, raw_text, whisper_words)

    # Save all outputs
    save_outputs(OUTPUT_DIR, full_result, aligned_words, alignment_method)

    print(f"\nFirst 10 words ({alignment_method}):")
    for w in aligned_words[:10]:
        print(f"  {w['start']:5.2f}s -> {w['end']:5.2f}s  \"{w['word']}\"  ({w['conf']:.2f})")
    print("\nStage 2 complete. Run Stage 3 next.")
