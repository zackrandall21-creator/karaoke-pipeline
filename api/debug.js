// api/debug.js — credential + connectivity test endpoint
export default async function handler(req, res) {
  const results = {};

  // Check env vars (presence only, never expose values)
  results.env = {
    BLOB_READ_WRITE_TOKEN: !!process.env.BLOB_READ_WRITE_TOKEN,
    KAGGLE_USERNAME: process.env.KAGGLE_USERNAME || '(not set)',
    KAGGLE_KEY: process.env.KAGGLE_KEY ? `(set, ${process.env.KAGGLE_KEY.length} chars)` : '(not set)',
  };

  // Test Vercel Blob connectivity
  try {
    const { list } = await import('@vercel/blob');
    const { blobs } = await list({ prefix: 'jobs/', limit: 1, token: process.env.BLOB_READ_WRITE_TOKEN });
    results.blob = { ok: true, recentJobCount: blobs.length };
  } catch (err) {
    results.blob = { ok: false, error: err.message };
  }

  // Test Kaggle auth
  try {
    const username = process.env.KAGGLE_USERNAME;
    const key = process.env.KAGGLE_KEY;
    const authHeader = 'Basic ' + Buffer.from(`${username}:${key}`).toString('base64');

    const kaggleRes = await fetch('https://www.kaggle.com/api/v1/kernels?userAuthenticationRequired=true&pageSize=1', {
      headers: { 'Authorization': authHeader },
    });

    const text = await kaggleRes.text();
    let parsed;
    try { parsed = JSON.parse(text); } catch { parsed = text.slice(0, 200); }

    results.kaggle = {
      status: kaggleRes.status,
      ok: kaggleRes.ok,
      response: parsed,
    };
  } catch (err) {
    results.kaggle = { ok: false, error: err.message };
  }

  return res.status(200).json(results);
}
