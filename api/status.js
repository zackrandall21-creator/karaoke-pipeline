// api/status.js — Job status polling endpoint
// GET /api/status?jobId=<id>
// Returns current status of a karaoke job.
// Step 4 will update this to check actual Kaggle run state.

export default async function handler(req, res) {
  if (req.method !== 'GET') {
    return res.status(405).json({ error: 'Method not allowed' });
  }

  const { jobId } = req.query;
  if (!jobId) {
    return res.status(400).json({ error: 'Missing jobId query param' });
  }

  // TODO (step 4): Look up actual job state from KV/DB
  // For now, return a placeholder so the frontend polling loop works end-to-end
  return res.status(200).json({
    jobId,
    status: 'processing', // will be: 'uploaded' | 'processing' | 'done' | 'failed'
    outputUrl: null,      // will be filled when Kaggle finishes
    message: 'Processing in progress…',
  });
}
