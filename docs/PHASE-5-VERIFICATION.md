# Release verification

The Python suite and the live demo answer different questions. The suite checks
toolkit behavior, including simulated failures. The demo job establishes which
steps actually worked together on one fresh Linux runner.

## Evidence

| Revision | Exercise | Result |
|---|---|---|
| PR #6, head `aeb679b` | Hosted Python tests | The job succeeded. The owner confirmed 248 tests passed in normal and optimized Python. [Actions run](https://github.com/Kartik-Budhlakoti/service-deployment-toolkit/actions/runs/45128297299) |
| PR #6, Batch B | Python tests and Fresh demo | The owner confirmed both jobs passed. [Actions run](https://github.com/Kartik-Budhlakoti/service-deployment-toolkit/actions/runs/45130436650) |

## Recovery walkthrough

The [one-minute walkthrough](media/recovery-walkthrough.gif) follows a local
exercise on the dedicated demo. The captions summarize observations from the
[Phase 4 verification record](PHASE-4-VERIFICATION.md). The text below covers
the same incident at your own pace.

1. **Baseline.** The catalogue served `demo-v1` on both the direct API port
   (8089) and the NGINX port (8088).
2. **Default deployment.** A deliberately broken image exited before serving
   HTTP. The API stayed down until an explicit rollback restored v1.
3. **Opt-in deployment.** A separate deployment of that image requested
   `--auto-recover --schema catalogue-v1`. The toolkit verified the running
   baseline first. Candidate operation `458b0f10d49c4a51b3795bb8cba8dc84`
   failed verification.
4. **Two outcomes.** In the candidate report, `operation.outcome` was
   `failed` and `automatic_recovery.outcome` was `succeeded`. The deploy
   command returned **1**. A caller waiting for the new version still needed
   to know that its request failed.
5. **Restoration.** Recovery operation `b30ecc6853d44cf7a132cc2eabf04202`
   restored the original image in a new API container. Both catalogue routes
   worked again. PostgreSQL and NGINX retained their container IDs.
   Re-exporting by recovery ID reproduced the candidate report.

To repeat the exercise, start with the initialized v1 demo and keep other
Docker and toolkit operations idle. The exercise intentionally interrupts
the API, creates journal entries and a report, and retains a test image.
Run from the project root. Each run generates its own operation IDs.

```bash
python scripts/phase4-acceptance.py candidate
```

## Fresh demo on each PR and push to main

Open **Fresh demo** in the CI run. The first step after setup prints the
checked-out Git commit, host architecture, Python, Engine and Compose versions.
The job requires an empty project checkout state, free demo ports and no
pre-existing demo resources. It generates local credentials, follows the README
build and initialization sequence, checks both catalogue routes, runs all four
network diagnostics and records a verified v1 baseline.

This exercise uses a hosted image with system tools already installed. A
successful run establishes fresh project setup with those versions. First
installation of Docker on bare Linux and byte-identical builds are separate claims.

## Recovery before tagging

After the release PR merges, select **Actions → CI → Run workflow**, choose
the merged main branch, and start the workflow. Compare the checked-out SHA in
the job log with the intended release commit. Both jobs must succeed. Expand
**Exercise recovery on the selected revision** and confirm it actually ran.

The existing exercise builds a candidate that exits before serving HTTP.
It verifies the failed deployment and its separate recovery, validates the
candidate report, and rechecks the restored v1. A deploy exit of 1 is expected
inside this exercise. The driver exits 0 only when its assertions pass.

Use the run URL and full checked-out SHA in the release notes. A normal PR or
push run skips the recovery step. Preserve the first failing step if a run
fails.
