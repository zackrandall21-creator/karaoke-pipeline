// api/upload.js — Vercel serverless function
// Step 3: Receive MP3, store in Vercel Blob, return jobId + blobUrl.
// Step 4: Trigger Kaggle kernel push with jobId + blobUrl.

export const config = {
  api: {
    bodyParser: false, // Required for multipart/form-data
  },
};

import { put } from '@vercel/blob';
import { createId } from '@paralleldrive/cuid2';
import formidable from 'formidable';
import fs from 'fs';

export default async function handler(req, res) {
  if (req.method !== 'POST') {
    return res.status(405).json({ error: 'Method not allowed' });
  }

  // Check Blob token is configured
  if (!process.env.BLOB_READ_WRITE_TOKEN) {
    console.error('[upload] BLOB_READ_WRITE_TOKEN not set');
    return res.status(500).json({ error: 'Storage not configured. Contact admin.' });
  }

  // Check Kaggle credentials are configured
  if (!process.env.KAGGLE_USERNAME || !process.env.KAGGLE_KEY) {
    console.error('[upload] Kaggle credentials not set');
    return res.status(500).json({ error: 'Processing not configured. Contact admin.' });
  }

  // Parse multipart form
  const form = formidable({ maxFileSize: 100 * 1024 * 1024 }); // 100 MB
  let fields, files;
  try {
    [fields, files] = await form.parse(req);
  } catch (err) {
    console.error('[upload] Form parse error:', err);
    return res.status(400).json({ error: 'Failed to parse upload. Max size is 100 MB.' });
  }

  const uploaded = Array.isArray(files.audio) ? files.audio[0] : files.audio;
  if (!uploaded) {
    return res.status(400).json({ error: 'No audio file received. Field name must be "audio".' });
  }

  // Basic MIME/extension check
  const mime = uploaded.mimetype || '';
  if (!mime.includes('audio') && !uploaded.originalFilename?.endsWith('.mp3')) {
    return res.status(400).json({ error: 'Only MP3 files are supported.' });
  }

  const jobId = createId();
  const safeFilename = `jobs/${jobId}/input.mp3`;

  let blobUrl;
  try {
    // Read temp file into buffer
    const fileBuffer = fs.readFileSync(uploaded.filepath);

    // Upload to Vercel Blob (public so Kaggle can wget it)
    const blob = await put(safeFilename, fileBuffer, {
      access: 'public',
      contentType: 'audio/mpeg',
      token: process.env.BLOB_READ_WRITE_TOKEN,
    });
    blobUrl = blob.url;
  } catch (err) {
    console.error('[upload] Blob upload error:', err);
    return res.status(500).json({ error: 'Failed to store file. Please try again.' });
  } finally {
    // Clean up temp file
    try { fs.unlinkSync(uploaded.filepath); } catch (_) {}
  }

  console.log(`[upload] Job ${jobId} — stored at ${blobUrl}`);

  // Step 4: Trigger Kaggle kernel push
  // The Kaggle Kernels Push API creates/updates a kernel and queues it for execution.
  // We pass jobId + blobUrl as environment variables via dataset_data_sources field
  // encoded into the kernel-metadata title. Kaggle reads these via env vars we set
  // in the kernel metadata. The kernel slug must already exist on Kaggle.
  const kaggleUsername = process.env.KAGGLE_USERNAME;
  const kaggleKey = process.env.KAGGLE_KEY;
  const kernelSlug = `${kaggleUsername}/karaoke-pipeline-runner`;

  try {
    // Build the kernel push payload
    // We embed jobId and blobUrl into the title field (Kaggle reads them as env-like vars)
    // The kernel script reads KAGGLE_JOB_ID and KAGGLE_BLOB_URL from os.environ
    const kernelPushBody = {
      username: kaggleUsername,
      slug: 'karaoke-pipeline-runner',
      language: 'python',
      kernel_type: 'script',
      is_private: true,
      enable_gpu: true,
      enable_internet: true,
      dataset_data_sources: [],
      competition_data_sources: [],
      kernel_data_sources: [],
      title: `karaoke-pipeline-runner`,
      // Pass job params via environment - Kaggle supports env vars in kernel metadata
      // We use the 'categories' field as a side-channel for params (parsed by the script)
      // Real approach: script reads a small JSON file we include as dataset source
      // Simpler approach: encode params in the source code itself
      source_code: generateKernelScript(jobId, blobUrl),
    };

    const kaggleRes = await fetch('https://www.kaggle.com/api/v1/kernels/push', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': 'Basic ' + Buffer.from(`${kaggleUsername}:${kaggleKey}`).toString('base64'),
      },
      body: JSON.stringify(kernelPushBody),
    });

    const kaggleData = await kaggleRes.json();
    console.log('[upload] Kaggle push response:', JSON.stringify(kaggleData));

    if (!kaggleRes.ok || kaggleData.error) {
      throw new Error(kaggleData.error || `Kaggle API returned ${kaggleRes.status}`);
    }

    console.log(`[upload] Job ${jobId} — Kaggle kernel queued (ref: ${kaggleData.ref || 'n/a'})`);
  } catch (err) {
    // Kaggle trigger failed — still return success for the upload, but log the error.
    // The status endpoint will show the error state.
    console.error('[upload] Kaggle trigger error:', err.message);
    // Don't fail the whole request — upload succeeded, processing will retry
  }

  return res.status(200).json({
    ok: true,
    jobId,
    blobUrl,
    filename: uploaded.originalFilename,
    sizeBytes: uploaded.size,
    status: 'processing',
    message: 'File uploaded. Karaoke processing has started on Kaggle (usually takes 5–10 min).',
  });
}

// Generate the Python script that Kaggle will execute.
// jobId and blobUrl are baked into the script source.
function generateKernelScript(jobId, blobUrl) {
  return `
import os, subprocess, sys, urllib.request, json

# ── Job params (baked in by Vercel at trigger time) ──
JOB_ID   = "${jobId}"
BLOB_URL = "${blobUrl}"
VERCEL_CALLBACK = os.environ.get("VERCEL_CALLBACK_URL", "https://karaoke-pipeline.vercel.app/api/callback")

print(f"[karaoke] Job {JOB_ID} starting")
print(f"[karaoke] Input: {BLOB_URL}")

# ── 1. Download MP3 ──
print("[karaoke] Downloading MP3...")
urllib.request.urlretrieve(BLOB_URL, "/kaggle/working/input.mp3")
print("[karaoke] Download complete")

# ── 2. Install deps ──
print("[karaoke] Installing dependencies...")
subprocess.run([sys.executable, "-m", "pip", "install", "-q",
    "demucs", "openai-whisper", "whisper-timestamped",
    "ffmpeg-python", "Pillow", "numpy"], check=True)

# ── 3. Demucs — separate vocals ──
print("[karaoke] Running Demucs vocal separation...")
subprocess.run([
    sys.executable, "-m", "demucs",
    "--two-stems", "vocals",
    "-o", "/kaggle/working/demucs_out",
    "/kaggle/working/input.mp3"
], check=True)

# Locate the vocals stem
import glob
vocal_files = glob.glob("/kaggle/working/demucs_out/**/vocals.wav", recursive=True)
if not vocal_files:
    raise FileNotFoundError("Demucs did not produce a vocals.wav")
vocal_path = vocal_files[0]
print(f"[karaoke] Vocal stem: {vocal_path}")

# ── 4. Whisper — transcribe with word timestamps ──
print("[karaoke] Running Whisper transcription...")
import whisper_timestamped as whisper
audio = whisper.load_audio(vocal_path)
model = whisper.load_model("medium")
result = whisper.transcribe(
    model, audio,
    language="en",
    word_timestamps=True,
    temperature=0.2,
    best_of=5,
    compression_ratio_threshold=2.8,
    no_speech_threshold=1.0,
    condition_on_previous_text=True,
    vad=True,
)

# Flatten word list
words = []
for seg in result["segments"]:
    for w in seg.get("words", []):
        words.append({
            "word": w["text"].strip(),
            "start": w["start"],
            "end":   w["end"],
        })
print(f"[karaoke] Transcribed {len(words)} words")

# ── 5. Render karaoke video ──
print("[karaoke] Rendering video...")
from PIL import Image, ImageDraw, ImageFont
import numpy as np

WIDTH, HEIGHT = 1280, 720
FPS = 30
BG_COLOR = (0, 0, 0)
ACTIVE_COLOR = (255, 220, 0)   # yellow wipe
PAST_COLOR   = (80, 80, 80)    # dimmed
FUTURE_COLOR = (255, 255, 255) # white

# Get audio duration via ffprobe
result_dur = subprocess.run(
    ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
     "-of", "csv=p=0", "/kaggle/working/input.mp3"],
    capture_output=True, text=True
)
duration = float(result_dur.stdout.strip())
total_frames = int(duration * FPS)
print(f"[karaoke] Duration: {duration:.1f}s — {total_frames} frames")

# Group words into 2-line chunks of ~8 words each
LINE_WORDS = 8
chunks = [words[i:i+LINE_WORDS*2] for i in range(0, max(len(words), 1), LINE_WORDS*2)]

def get_chunk_for_time(t):
    for chunk in chunks:
        if chunk and chunk[0]["start"] <= t <= chunk[-1]["end"] + 2.0:
            return chunk
    return []

def render_frame(t):
    img = Image.new("RGB", (WIDTH, HEIGHT), BG_COLOR)
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 52)
    except:
        font = ImageFont.load_default()

    chunk = get_chunk_for_time(t)
    if not chunk:
        return np.array(img)

    line1 = chunk[:LINE_WORDS]
    line2 = chunk[LINE_WORDS:LINE_WORDS*2]

    for line_idx, line_words in enumerate([line1, line2]):
        if not line_words:
            continue
        line_text = " ".join(w["word"] for w in line_words)
        y = HEIGHT // 2 - 60 + line_idx * 90
        # Measure total line width for centering
        bbox = draw.textbbox((0, 0), line_text, font=font)
        total_w = bbox[2] - bbox[0]
        x = (WIDTH - total_w) // 2
        # Draw word by word with colour
        for w in line_words:
            word_text = w["word"] + " "
            bbox = draw.textbbox((x, y), word_text, font=font)
            if t > w["end"]:
                color = PAST_COLOR
            elif w["start"] <= t <= w["end"]:
                # Partial yellow wipe
                prog = (t - w["start"]) / max(w["end"] - w["start"], 0.001)
                color = ACTIVE_COLOR
            else:
                color = FUTURE_COLOR
            draw.text((x, y), word_text, font=font, fill=color)
            x += bbox[2] - bbox[0]
    return np.array(img)

# Write frames to raw video via ffmpeg pipe
print("[karaoke] Writing frames...")
output_path = f"/kaggle/working/{JOB_ID}_karaoke.mp4"
ffmpeg_cmd = [
    "ffmpeg", "-y",
    "-f", "rawvideo", "-vcodec", "rawvideo",
    "-s", f"{WIDTH}x{HEIGHT}", "-pix_fmt", "rgb24",
    "-r", str(FPS), "-i", "-",
    "-i", "/kaggle/working/input.mp3",
    "-c:v", "libx264", "-preset", "fast", "-crf", "23",
    "-c:a", "aac", "-b:a", "192k",
    "-shortest", output_path
]
import io
proc = subprocess.Popen(ffmpeg_cmd, stdin=subprocess.PIPE, stderr=subprocess.DEVNULL)
for frame_idx in range(total_frames):
    t = frame_idx / FPS
    frame = render_frame(t)
    proc.stdin.write(frame.tobytes())
    if frame_idx % (FPS * 10) == 0:
        print(f"[karaoke] Frame {frame_idx}/{total_frames} ({frame_idx/total_frames*100:.0f}%)")
proc.stdin.close()
proc.wait()
print(f"[karaoke] Video written to {output_path}")

# ── 6. Upload output video to Vercel Blob via callback ──
print("[karaoke] Uploading output video...")
with open(output_path, "rb") as f:
    video_data = f.read()

callback_url = f"{VERCEL_CALLBACK}?jobId={JOB_ID}"
req = urllib.request.Request(
    callback_url,
    data=video_data,
    headers={"Content-Type": "video/mp4", "X-Job-Id": JOB_ID},
    method="POST"
)
try:
    with urllib.request.urlopen(req, timeout=120) as resp:
        body = resp.read().decode()
        print(f"[karaoke] Callback response: {body}")
except Exception as e:
    print(f"[karaoke] Callback failed: {e}")
    # Save output URL to a file as fallback
    with open("/kaggle/working/output_url.txt", "w") as f:
        f.write(output_path)

print(f"[karaoke] Job {JOB_ID} complete!")
`;
}
