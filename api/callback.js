// api/callback.js — Receives the finished video from Kaggle and stores it in Vercel Blob.
// Kaggle POSTs the raw MP4 bytes here when processing is complete.
// The frontend polls /api/status?jobId=<id> for the outputUrl.

import { put, list } from '@vercel/blob';

export const config = {
  api: {
    bodyParser: {
      sizeLimit: '500mb',
    },
  },
};

export default async function handler(req, res) {
  if (req.method !== 'POST') {
    return res.status(405).json({ error: 'Method not allowed' });
  }

  const { jobId } = req.query;
  if (!jobId) {
    return res.status(400).json({ error: 'Missing jobId' });
  }

  if (!process.env.BLOB_READ_WRITE_TOKEN) {
    return res.status(500).json({ error: 'Storage not configured' });
  }

  // Collect raw body (video bytes)
  const chunks = [];
  for await (const chunk of req) {
    chunks.push(chunk);
  }
  const videoBuffer = Buffer.concat(chunks);

  if (videoBuffer.length === 0) {
    return res.status(400).json({ error: 'Empty video body' });
  }

  console.log(`[callback] Job ${jobId} — received ${(videoBuffer.length / 1024 / 1024).toFixed(1)} MB`);

  // Store video in Vercel Blob
  let outputUrl;
  try {
    const blob = await put(`jobs/${jobId}/output.mp4`, videoBuffer, {
      access: 'public',
      contentType: 'video/mp4',
      token: process.env.BLOB_READ_WRITE_TOKEN,
    });
    outputUrl = blob.url;
  } catch (err) {
    console.error('[callback] Blob upload error:', err);
    return res.status(500).json({ error: 'Failed to store video' });
  }

  console.log(`[callback] Job ${jobId} — output stored at ${outputUrl}`);

  return res.status(200).json({
    ok: true,
    jobId,
    outputUrl,
    message: 'Video stored successfully',
  });
}
