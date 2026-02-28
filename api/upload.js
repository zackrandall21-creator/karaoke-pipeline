// api/upload.js — Vercel serverless function
// Receives an MP3 upload, validates it, and returns a job ID.
// Next step: store the file (Vercel Blob) and trigger Kaggle.

export const config = {
  api: {
    bodyParser: false, // Required for multipart/form-data (file uploads)
  },
};

import { createId } from '@paralleldrive/cuid2';
import formidable from 'formidable';
import fs from 'fs';

export default async function handler(req, res) {
  // Only accept POST
  if (req.method !== 'POST') {
    return res.status(405).json({ error: 'Method not allowed' });
  }

  // Parse multipart form
  const form = formidable({ maxFileSize: 100 * 1024 * 1024 }); // 100 MB limit

  let fields, files;
  try {
    [fields, files] = await form.parse(req);
  } catch (err) {
    console.error('Form parse error:', err);
    return res.status(400).json({ error: 'Failed to parse upload. Max size is 100 MB.' });
  }

  const uploaded = Array.isArray(files.audio) ? files.audio[0] : files.audio;
  if (!uploaded) {
    return res.status(400).json({ error: 'No audio file received. Field name must be "audio".' });
  }

  // Basic MIME check
  const mime = uploaded.mimetype || '';
  if (!mime.includes('audio') && !uploaded.originalFilename?.endsWith('.mp3')) {
    return res.status(400).json({ error: 'Only MP3 files are supported.' });
  }

  // Generate a unique job ID
  const jobId = createId();

  // TODO (step 3): Upload file to Vercel Blob storage
  // TODO (step 4): Trigger Kaggle notebook with jobId + blob URL

  console.log(`[upload] New job ${jobId} — file: ${uploaded.originalFilename} (${uploaded.size} bytes)`);

  // Clean up temp file
  try { fs.unlinkSync(uploaded.filepath); } catch (_) {}

  return res.status(200).json({
    ok: true,
    jobId,
    filename: uploaded.originalFilename,
    sizeBytes: uploaded.size,
    message: 'File received. Processing will begin shortly.',
  });
}
