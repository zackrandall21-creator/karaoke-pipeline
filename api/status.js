// api/status.js — Job status polling endpoint
// GET /api/status?jobId=<id>
// Checks if the output video exists in Vercel Blob yet.
// Returns: { jobId, status: 'processing'|'done'|'failed', outputUrl }

import { list } from '@vercel/blob';

export default async function handler(req, res) {
  if (req.method !== 'GET') {
    return res.status(405).json({ error: 'Method not allowed' });
  }

  const { jobId } = req.query;
  if (!jobId) {
    return res.status(400).json({ error: 'Missing jobId query param' });
  }

  if (!process.env.BLOB_READ_WRITE_TOKEN) {
    return res.status(500).json({ error: 'Storage not configured' });
  }

  // Check if output video has been uploaded to Blob
  try {
    const { blobs } = await list({
      prefix: `jobs/${jobId}/output.mp4`,
      token: process.env.BLOB_READ_WRITE_TOKEN,
    });

    if (blobs.length > 0) {
      const outputUrl = blobs[0].url;
      console.log(`[status] Job ${jobId} — done, output at ${outputUrl}`);
      return res.status(200).json({
        jobId,
        status: 'done',
        outputUrl,
        message: 'Your karaoke video is ready!',
      });
    }
  } catch (err) {
    console.error('[status] Blob list error:', err);
  }

  // Output not found yet — still processing
  return res.status(200).json({
    jobId,
    status: 'processing',
    outputUrl: null,
    message: 'Processing in progress… (usually 5–10 min)',
  });
}
