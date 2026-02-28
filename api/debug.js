// api/debug.js - credential + Kaggle kernel push test
export default async function handler(req, res) {
  const KAGGLE_USERNAME = process.env.KAGGLE_USERNAME;
  const KAGGLE_KEY = process.env.KAGGLE_KEY;
  const BLOB_TOKEN = process.env.BLOB_READ_WRITE_TOKEN;

  // Test blob
  let blobResult = { ok: false };
  try {
    const { list } = await import("@vercel/blob");
    const blobs = await list({ prefix: "jobs/", limit: 2, token: BLOB_TOKEN });
    blobResult = { ok: true, recentJobs: blobs.blobs.map(b => b.pathname) };
  } catch (e) {
    blobResult = { ok: false, error: e.message };
  }

  // Test real Kaggle kernel push with minimal script
  let kaggleResult = {};
  try {
    const body = {
      username: KAGGLE_USERNAME,
      slug: "karaoke-pipeline-runner",
      language: "python",
      kernel_type: "script",
      is_private: true,
      enable_gpu: true,
      enable_internet: true,
      dataset_data_sources: [],
      competition_data_sources: [],
      kernel_data_sources: [],
      title: "karaoke-pipeline-runner",
      source_code: "print(\"debug test\")",
    };
    const auth = Buffer.from(`${KAGGLE_USERNAME}:${KAGGLE_KEY}`).toString("base64");
    const resp = await fetch("https://www.kaggle.com/api/v1/kernels/push", {
      method: "POST",
      headers: { "Content-Type": "application/json", "Authorization": `Basic ${auth}` },
      body: JSON.stringify(body),
    });
    const data = await resp.json();
    kaggleResult = { status: resp.status, ok: resp.ok, response: data };
  } catch (e) {
    kaggleResult = { ok: false, error: e.message };
  }

  return res.status(200).json({
    env: {
      BLOB_READ_WRITE_TOKEN: !!BLOB_TOKEN,
      KAGGLE_USERNAME,
      KAGGLE_KEY: KAGGLE_KEY ? `(set, ${KAGGLE_KEY.length} chars)` : "(not set)",
    },
    blob: blobResult,
    kaggle: kaggleResult,
  });
}
