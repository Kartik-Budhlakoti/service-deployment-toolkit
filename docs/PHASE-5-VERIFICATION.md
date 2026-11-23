# Release verification

The Python suite and the live demo answer different questions. The suite checks
toolkit behavior, including simulated failures. The demo job establishes which
steps actually worked together on one fresh Linux runner.

## Evidence

| Revision | Exercise | Result |
|---|---|---|
| PR #6, head `aeb679b` | Hosted Python tests | The job succeeded. The owner confirmed 248 tests passed in normal and optimized Python. [Actions run](https://github.com/Kartik-Budhlakoti/service-deployment-toolkit/actions/runs/45128297299) |

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
fails. The first hosted fresh-demo verdict and the final release verdict
should be recorded from their respective runs.
