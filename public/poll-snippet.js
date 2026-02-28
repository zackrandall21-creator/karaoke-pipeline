    function startPolling(jobId) {
      let attempts = 0;
      const MAX_ATTEMPTS = 360; // 30 min @ 5s intervals

      pollInterval = setInterval(async () => {
        attempts++;
        if (attempts > MAX_ATTEMPTS) {
          clearInterval(pollInterval);
          showStatus('error', 'Timed out — processing took too long. Please try again or check back later.');
          submitBtn.disabled = false;
          return;
        }

        // Update status with elapsed time every 30s
        if (attempts % 6 === 0) {
          const elapsed = Math.round(attempts * 5 / 60);
          showStatus('polling', `⏳ Processing… ${elapsed} min elapsed (usually 15–25 min total)`);
        }

        try {
          const res = await fetch('/api/status?jobId=' + jobId);
          const job = await res.json();

          const pct = 50 + Math.min(attempts / MAX_ATTEMPTS * 48, 48);
          progressBar.style.width = pct + '%';

          if (job.status === 'done' && job.outputUrl) {
            clearInterval(pollInterval);
            progressBar.style.width = '100%';
            showStatus('done', '🎉 Your karaoke video is ready!');
            downloadLink.href = job.outputUrl;
            downloadLink.classList.add('visible');
            submitBtn.disabled = false;
          } else if (job.status === 'error') {
            clearInterval(pollInterval);
            showStatus('error', 'Processing failed: ' + (job.message || 'unknown error'));
            submitBtn.disabled = false;
          }
        } catch (err) {
          // ignore transient polling errors
        }
      }, 5000);
    }