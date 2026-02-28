// api/upload.js — Vercel serverless function
// Receives MP3 via multipart/form-data, stores in Vercel Blob, triggers Kaggle.

export const config = {
  api: {
    bodyParser: false,
    sizeLimit: '100mb',
  },
};

import { put } from '@vercel/blob';
import { createId } from '@paralleldrive/cuid2';
import Busboy from 'busboy';

export default async function handler(req, res) {
  if (req.method !== 'POST') {
    return res.status(405).json({ error: 'Method not allowed' });
  }

  if (!process.env.BLOB_READ_WRITE_TOKEN) {
    console.error('[upload] BLOB_READ_WRITE_TOKEN not set');
    return res.status(500).json({ error: 'Storage not configured.' });
  }

  if (!process.env.KAGGLE_USERNAME || !process.env.KAGGLE_KEY) {
    console.error('[upload] Kaggle credentials not set');
    return res.status(500).json({ error: 'Processing not configured.' });
  }

  // Parse multipart with busboy
  const jobId = createId();
  let fileBuffer = null;
  let originalFilename = 'input.mp3';
  let mimeType = 'audio/mpeg';
  let fileSize = 0;

  try {
    await new Promise((resolve, reject) => {
      const busboy = Busboy({
        headers: req.headers,
        limits: { fileSize: 100 * 1024 * 1024 }, // 100 MB
      });

      busboy.on('file', (fieldname, file, info) => {
        const { filename, mimeType: mime } = info;
        originalFilename = filename || 'input.mp3';
        mimeType = mime || 'audio/mpeg';

        const chunks = [];
        file.on('data', (chunk) => chunks.push(chunk));
        file.on('end', () => {
          fileBuffer = Buffer.concat(chunks);
          fileSize = fileBuffer.length;
        });
        file.on('limit', () => reject(new Error('File too large (max 100 MB)')));
      });

      busboy.on('finish', resolve);
      busboy.on('error', reject);
      req.pipe(busboy);
    });
  } catch (err) {
    console.error('[upload] Parse error:', err.message);
    return res.status(400).json({ error: err.message || 'Failed to parse upload.' });
  }

  if (!fileBuffer || fileBuffer.length === 0) {
    return res.status(400).json({ error: 'No audio file received. Field name must be "audio".' });
  }

  // Basic MIME/extension check
  if (!mimeType.includes('audio') && !originalFilename.endsWith('.mp3')) {
    return res.status(400).json({ error: 'Only MP3 files are supported.' });
  }

  // Upload to Vercel Blob (public so Kaggle can wget it)
  let blobUrl;
  try {
    const blob = await put(`jobs/${jobId}/input.mp3`, fileBuffer, {
      access: 'public',
      contentType: 'audio/mpeg',
      token: process.env.BLOB_READ_WRITE_TOKEN,
    });
    blobUrl = blob.url;
  } catch (err) {
    console.error('[upload] Blob upload error:', err);
    return res.status(500).json({ error: 'Failed to store file. Please try again.' });
  }

  console.log(`[upload] Job ${jobId} — stored at ${blobUrl} (${(fileSize / 1024 / 1024).toFixed(1)} MB)`);

  // Trigger Kaggle kernel push
  const kaggleUsername = process.env.KAGGLE_USERNAME;
  const kaggleKey = process.env.KAGGLE_KEY;

  try {
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
      title: 'karaoke-pipeline-runner',
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

    if (!kaggleRes.ok) {
      throw new Error(kaggleData.message || kaggleData.error || `Kaggle API ${kaggleRes.status}`);
    }

    console.log(`[upload] Job ${jobId} — Kaggle kernel queued`);
  } catch (err) {
    console.error('[upload] Kaggle trigger error:', err.message);
    // Don't fail the request — upload succeeded, note the error in response
    return res.status(200).json({
      ok: true,
      jobId,
      blobUrl,
      filename: originalFilename,
      sizeBytes: fileSize,
      status: 'processing',
      kaggleError: err.message,
      message: 'File uploaded but Kaggle trigger failed: ' + err.message,
    });
  }

  return res.status(200).json({
    ok: true,
    jobId,
    blobUrl,
    filename: originalFilename,
    sizeBytes: fileSize,
    status: 'processing',
    message: 'File uploaded. Karaoke processing started (usually 5–10 min).',
  });
}

function generateKernelScript(jobId, blobUrl) {
  return `
import os, subprocess, sys, urllib.request, glob

JOB_ID   = "${jobId}"
BLOB_URL = "${blobUrl}"
CALLBACK = "https://karaoke-pipeline.vercel.app/api/callback"

print(f"[karaoke] Job {JOB_ID} starting")
print(f"[karaoke] Input: {BLOB_URL}")

# 1. Download MP3
print("[karaoke] Downloading MP3...")
urllib.request.urlretrieve(BLOB_URL, "/kaggle/working/input.mp3")
print("[karaoke] Download complete")

# 2. Install deps
print("[karaoke] Installing dependencies...")
subprocess.run([sys.executable, "-m", "pip", "install", "-q",
    "demucs", "openai-whisper", "whisper-timestamped",
    "ffmpeg-python", "Pillow", "numpy"], check=True)

# 3. Demucs — separate vocals
print("[karaoke] Running Demucs vocal separation...")
subprocess.run([
    sys.executable, "-m", "demucs",
    "--two-stems", "vocals",
    "-o", "/kaggle/working/demucs_out",
    "/kaggle/working/input.mp3"
], check=True)

vocal_files = glob.glob("/kaggle/working/demucs_out/**/vocals.wav", recursive=True)
if not vocal_files:
    raise FileNotFoundError("Demucs did not produce a vocals.wav")
vocal_path = vocal_files[0]
print(f"[karaoke] Vocal stem: {vocal_path}")

# 4. Whisper — transcribe with word timestamps
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

words = []
for seg in result["segments"]:
    for w in seg.get("words", []):
        words.append({"word": w["text"].strip(), "start": w["start"], "end": w["end"]})
print(f"[karaoke] Transcribed {len(words)} words")

# 5. Render karaoke video
print("[karaoke] Rendering video...")
from PIL import Image, ImageDraw, ImageFont
import numpy as np

WIDTH, HEIGHT, FPS = 1280, 720, 30
BG = (0, 0, 0)
ACTIVE = (255, 220, 0)
PAST   = (80, 80, 80)
FUTURE = (255, 255, 255)

result_dur = subprocess.run(
    ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
     "-of", "csv=p=0", "/kaggle/working/input.mp3"],
    capture_output=True, text=True
)
duration = float(result_dur.stdout.strip())
total_frames = int(duration * FPS)
print(f"[karaoke] Duration: {duration:.1f}s — {total_frames} frames")

LINE_WORDS = 8
chunks = [words[i:i+LINE_WORDS*2] for i in range(0, max(len(words), 1), LINE_WORDS*2)]

def get_chunk(t):
    for chunk in chunks:
        if chunk and chunk[0]["start"] <= t <= chunk[-1]["end"] + 2.0:
            return chunk
    return []

try:
    font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 52)
except:
    font = ImageFont.load_default()

def render_frame(t):
    img = Image.new("RGB", (WIDTH, HEIGHT), BG)
    draw = ImageDraw.Draw(img)
    chunk = get_chunk(t)
    if not chunk:
        return np.array(img)
    for line_idx, line_words in enumerate([chunk[:LINE_WORDS], chunk[LINE_WORDS:LINE_WORDS*2]]):
        if not line_words: continue
        line_text = " ".join(w["word"] for w in line_words)
        y = HEIGHT // 2 - 60 + line_idx * 90
        bbox = draw.textbbox((0, 0), line_text, font=font)
        x = (WIDTH - (bbox[2] - bbox[0])) // 2
        for w in line_words:
            word_text = w["word"] + " "
            if t > w["end"]:
                color = PAST
            elif w["start"] <= t <= w["end"]:
                color = ACTIVE
            else:
                color = FUTURE
            draw.text((x, y), word_text, font=font, fill=color)
            wb = draw.textbbox((x, y), word_text, font=font)
            x += wb[2] - wb[0]
    return np.array(img)

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
proc = subprocess.Popen(ffmpeg_cmd, stdin=subprocess.PIPE, stderr=subprocess.DEVNULL)
for frame_idx in range(total_frames):
    t = frame_idx / FPS
    frame = render_frame(t)
    proc.stdin.write(frame.tobytes())
    if frame_idx % (FPS * 30) == 0:
        print(f"[karaoke] {frame_idx}/{total_frames} frames ({frame_idx/total_frames*100:.0f}%)")
proc.stdin.close()
proc.wait()
print(f"[karaoke] Video written")

# 6. POST video back to Vercel callback
print("[karaoke] Uploading output video...")
with open(output_path, "rb") as f:
    video_data = f.read()

callback_url = f"{CALLBACK}?jobId={JOB_ID}"
req_obj = urllib.request.Request(
    callback_url,
    data=video_data,
    headers={"Content-Type": "video/mp4", "X-Job-Id": JOB_ID},
    method="POST"
)
try:
    with urllib.request.urlopen(req_obj, timeout=120) as resp:
        print(f"[karaoke] Callback: {resp.read().decode()}")
except Exception as e:
    print(f"[karaoke] Callback failed: {e}")

print(f"[karaoke] Job {JOB_ID} complete!")
`;
}
