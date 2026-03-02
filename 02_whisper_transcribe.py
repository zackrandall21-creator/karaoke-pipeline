#!/usr/bin/env python3
"""
Karaoke Pipeline - Stage 2: Transcription + Forced Alignment (v5)
================================================================
Run in Kaggle Notebook after Stage 1.

v5 changes:
  - condition_on_previous_text=False: prevents hallucination loops on quiet passages
  - no_speech_threshold=0.6: balanced sensitivity (was 1.0, too permissive)
  - Transcribe from the FULL MIX (vocals + instruments) for better temporal grounding
    but run ctc-forced-aligner on the clean VOCAL STEM for precise boundary alignment
  - Vocal-only track kept for ctc alignment (cleaner signal for boundary detection)

Alignment pipeline:
  1. whisper-large-v3 on full mix → gets accurate lyrics text + rough timestamps
  2. ctc-forced-aligner on clean vocal stem → replaces timestamps with precise boundaries
     - ~10-50ms word boundary accuracy vs ~100-300ms from Whisper alone
     - Especially important for held vowels (sustain notes)

Outputs:
    /kaggle/working/output/transcription.json   - Full Whisper output
    /kaggle/working/output/words.json           - Flat word list with ALIGNED timestamps
    /kaggle/working/output/transcription.txt    - Human-readable preview
    /kaggle/working/output/alignment_method.txt - Which method was used
"""

import os
import json
import subprocess
import sys
import gc

# --- CONFIG -------------------------------------------------------------------------
VOCALS_WAV    = "/kaggle/working/output/vocals.wav"   # clean vocal stem (for CTC alignment)
FULL_MIX_WAV  = "/kaggle/working/song.mp3"            # full mix (for Whisper transcription)
OUTPUT_DIR    = "/kaggle/working/output"
LYRICS_PROMPT = ""   # Optional: paste known lyrics here for better accuracy
                     # Example: "I was born a coal miners daughter..."
                     # Leave empty for blind transcription
# ------------------------------------------------------------------------------------

# Whisper params tuned for karaoke (v5: hallucination-safe)
WHISPER_PARAMS = {
    "model":                        "large-v3",  # UPGRADED from medium
    "word_timestamps":               True,
    "temperature":                   0.2,
    "best_of":                       5,
    "compression_ratio_threshold":   2.8,
    "no_speech_threshold":           0.6,        # v5: was 1.0, lowered to avoid false positives
    "condition_on_previous_text":    False,       # v5: CRITICAL - prevents hallucination loops
    "enable_vad":                    True,
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


def transcribe_whisper(audio_file, prompt=""):
    """
    Step 1: Transcribe with whisper-large-v3.
    Uses the full mix (or vocals WAV if mix not available) for temporal grounding.
    Returns (words_list, raw_text) — timestamps are from Whisper internal
    alignment and will be replaced by ctc-forced-aligner in step 2.
    """
    import whisper_timestamped as whisper

    print(f"Loading Whisper {WHISPER_PARAMS['model']}...")
    model = whisper.load_model(WHISPER_PARAMS["model"])

    print(f"Transcribing: {audio_file}")
    if prompt:
        print(f"  Using lyrics prompt ({len(prompt)} chars)")

    audio = whisper.load_audio(audio_file)
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

    Uses CLEAN VOCAL STEM (not full mix) for best alignment accuracy.

    Returns aligned word list with corrected start/end times.
    """
    try:
        import torch
        from ctc_forced_aligner import (
            load_audio, load_alignment_model,
            generate_emissions, get_alignments,
            get_spans, postprocess_results,
        )

        print("Running ctc-forced-aligner (MMS-300M) on clean vocal stem...")
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

    # Use full mix for transcription if available, fall back to vocals-only
    transcription_source = FULL_MIX_WAV if os.path.isfile(FULL_MIX_WAV) else VOCALS_WAV
    print(f"Transcription source: {transcription_source}")
    print(f"Alignment source:     {VOCALS_WAV} (clean vocals only)")

    # Step 1: Transcribe with Whisper large-v3
    whisper_words, raw_text, full_result = transcribe_whisper(transcription_source, prompt=LYRICS_PROMPT)

    # Step 2: Refine word boundaries with ctc-forced-aligner (on clean vocals)
    aligned_words, alignment_method = align_with_ctc(VOCALS_WAV, raw_text, whisper_words)

    # Save all outputs
    save_outputs(OUTPUT_DIR, full_result, aligned_words, alignment_method)

    print(f"\nFirst 10 words ({alignment_method}):")
    for w in aligned_words[:10]:
        print(f"  {w['start']:5.2f}s -> {w['end']:5.2f}s  \"{w['word']}\"  ({w['conf']:.2f})")
    print("\nStage 2 complete. Run Stage 3 next.")
