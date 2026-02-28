# karaoke-pipeline

Automated karaoke video generator.  
**Black background · White bold text · Yellow wipe effect · Word-by-word sync**

Built on: Demucs (vocal separation) + whisper-timestamped (word timestamps) + PIL/ffmpeg (render).

---

## Pipeline

| Stage | Script | Where | What |
|-------|--------|-------|------|
| 1 | `01_demucs_separate.py` | Google Colab (GPU) | Vocal separation — htdemucs model, falls back to mdx_extra_q on OOM |
| 2 | `02_whisper_transcribe.py` | Google Colab (GPU) | Word-level timestamps via whisper-timestamped |
| 3 | `03_render_video.py` | Colab or local | PIL + ffmpeg video render with wipe effect |
| — | `04_full_pipeline_colab.py` | Google Colab | Convenience: pulls scripts from this repo and runs all 3 |

---

## Quick Start (Google Colab)

```python
# Cell 1: install deps
!apt-get install -y ffmpeg -q
!pip install demucs whisper-timestamped openai-whisper Pillow -q

# Cell 2: pull and run
!git clone https://github.com/zackrandall21-creator/karaoke-pipeline /content/kp

# Edit INPUT_FILE, SONG_ARTIST, SONG_TITLE at top of each script, then:
%run /content/kp/01_demucs_separate.py
%run /content/kp/02_whisper_transcribe.py
%run /content/kp/03_render_video.py
```

Or use the all-in-one convenience script: edit config in `04_full_pipeline_colab.py` and run.

---

## Whisper Params (tuned for karaoke)

```python
model                       = "medium"   # accuracy/speed balance
word_timestamps             = True
temperature                 = 0.2        # low randomness
best_of                     = 5          # 5 hypotheses -> picks best (conservative)
compression_ratio_threshold = 2.8
no_speech_threshold         = 1          # catches every word (very permissive)
condition_on_previous_text  = True
enable_vad                  = True       # Voice Activity Detection
```

> Technique sourced from [nomadkaraoke/python-lyrics-transcriber](https://github.com/nomadkaraoke/python-lyrics-transcriber).
> `best_of=5` + low temperature forces Whisper to be conservative, not creative.
> Add full lyrics as `LYRICS_PROMPT` in Stage 2 for ~90%+ accuracy vs ~60% blind.

---

## Video Spec

- **Resolution:** 1920x1080 @ 30fps
- **Background:** Black
- **Upcoming words:** White bold
- **Active word:** Yellow wipe (left-to-right over word duration)
- **Sung words:** RGB(80, 80, 80) dim grey
- **Layout:** 2 centered lines, intelligent line-breaking (adapted from [nomadkaraoke/segment_resizer.py](https://github.com/nomadkaraoke/python-lyrics-transcriber/blob/main/lyrics_transcriber/output/segment_resizer.py))

---

## Architecture

```
your_song.mp3
    ↓ Stage 1: demucs htdemucs
vocals.wav + no_vocals.wav
    ↓ Stage 2: whisper-timestamped (medium, best_of=5)
words.json  (word, start, end, conf)
    ↓ Stage 3: PIL frames -> ffmpeg pipe -> H.264
karaoke_video.mp4
```

---

## Notes

- Demucs `htdemucs` needs GPU; auto-falls back to `mdx_extra_q` on OOM
- All stages cache intermediate outputs; safe to re-run individual stages
- `LYRICS_PROMPT` in Stage 2 = forced alignment; leave empty for blind transcription
- Wipe effect currently uses 50% threshold; pixel-perfect wipe is a planned improvement
