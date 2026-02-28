// api/upload.js — Vercel serverless function
// Step 3: Receives an MP3, stores it in Vercel Blob, returns a jobId + blobUrl.
// Step 4 (next): Trigger Kaggle notebook with blobUrl.

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

  // TODO (step 4): Trigger Kaggle notebook with jobId + blobUrl

  return res.status(200).json({
    ok: true,
    jobId,
    blobUrl,
    filename: uploaded.originalFilename,
    sizeBytes: uploaded.size,
    status: 'uploaded',
    message: 'File stored. Processing will begin shortly.',
  });
}
