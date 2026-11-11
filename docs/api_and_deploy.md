# Part 5: API, Docker, AWS Learner Lab, CI/CD

Everything here is built from the code in this repo. What was tested without the real models: the scoring,
the timing rule, the artifact builder and the API logic (with made-up data). Not tested before you run it:
the FastAPI app, Docker, AWS and the GitHub workflows (no internet in the build sandbox).

## What was added

| File | What it does |
| --- | --- |
| `src/taxi/drive.py` | Road km between hexagons = straight line x detour factor measured on our trips |
| `src/taxi/recommend.py` | Candidates (D <= 15 min), Model B curves, score `D + area under curve to 60 - D`, coverage, top 3 |
| `scripts/make_artifacts.py` | Builds the small `artifacts/` folder (run once where `pipeline_output/` exists) |
| `app/main.py`, `app/static/index.html` | FastAPI service and the map demo page |
| `Dockerfile`, `.dockerignore`, `requirements-api.txt` | The container |
| `.github/workflows/ci.yml`, `deploy.yml` | Tests on pull requests; build, push and deploy on merge |
| `tests/test_recommend.py`, `tests/test_api.py`, `tests/fake_artifacts.py` | Tests with made-up artifacts |
| `scripts/measure_latency.py` | Response time and coverage numbers for the report |

## 1. Build the artifacts (once)

The frozen models and the feature tables are not in git, so this runs on the machine that has `pipeline_output/`:

```
python scripts/make_artifacts.py --day 20251105
```

`--day` must be a validation day (16 Sep to 9 Nov); the script refuses anything else, so the demo never
touches the test period. It writes `artifacts/` (a few MB): model, historical curves, features of every
hexagon for each hour of that day, the drive table, demo moments (no vehicle IDs), manifest, library versions.
Then check git will keep the files: `git check-ignore -v artifacts/model_b.joblib` should print nothing.

### 1b. Windows PowerShell, without touching the team's `pipeline_output/`

The demo needs tables for only 32 days (6 Oct to 6 Nov 2025). Build them into a separate folder:

```
$env:TAXI_OUT_DIR = "$PWD\pipeline_mine"
python scripts/build_days.py --start 20251006 --end 20251106
python scripts/build_hexhour.py --start 20251007 --end 20251106
python scripts/make_artifacts.py --day 20251105 --models-dir "$PWD\pipeline_output\models"
Remove-Item Env:TAXI_OUT_DIR
```
`--models-dir` only reads the existing models. Nothing in `pipeline_output/` is written.

## 2. Run locally

```
pip install -r requirements-api.txt -c artifacts/versions.txt
python tests/test_recommend.py
uvicorn app.main:app --reload          # http://localhost:8000  (map demo)  and  /docs  (API)
curl -X POST localhost:8000/recommend -H "Content-Type: application/json" \
  -d '{"hex": "<an h3 id from /demo/moments>", "time": "2025-11-05T14:20", "minutes_empty": 22}'
python scripts/measure_latency.py http://localhost:8000
```

## 3. Docker

```
docker build -t taxi-api .
docker run --rm -p 8000:8000 taxi-api
```

If `artifacts/manifest.json` says `"python": "3.11.x"`, change the first line of the Dockerfile to
`python:3.11-slim` (saved models are only safe to load with the library versions that made them).

## 4. AWS Learner Lab (one EC2 instance)

Check each screen against what your lab shows; Learner Lab limits some services.
1. Start Lab, wait for the green dot, open the AWS console.
2. EC2 > Launch instance: Ubuntu 24.04, `t3.medium`, 20 GB disk. Create a key pair and download the `.pem`.
3. Security group: port 80 from anywhere; port 22 from anywhere (needed for GitHub Actions; login is by key only).
4. EC2 > Elastic IPs > Allocate > Associate with the instance (the address then survives stop and start).
5. `chmod 400 key.pem && ssh -i key.pem ubuntu@<elastic-ip>`, then
   `sudo apt update && sudo apt install -y docker.io && sudo usermod -aG docker ubuntu`, log out and in.
6. Make the image public in GitHub (Packages > your image > Package settings > Public). It holds no raw
   tracks, only aggregated features, models and the drive table.
7. First run by hand: `docker run -d --name taxi --restart unless-stopped -p 80:8000 ghcr.io/<github-owner>/ml-project:latest`
   then open `http://<elastic-ip>/health`.
8. Stop the instance when you are not using it; the lab credit is limited and a session can end the instance.

## 5. GitHub Actions

1. Merge the files into the repo (or into your own fork if you are not an admin of the team repo; the workflow uses whatever repository it runs in). Repo owner: Settings > Secrets and variables > Actions > add
   `EC2_HOST` (the Elastic IP) and `EC2_SSH_KEY` (the full contents of the `.pem`). Settings > Actions > General:
   workflow permissions = read and write.
2. Open a pull request: `ci.yml` runs the existing tests, the new tests and a Docker build.
3. Merge to `master`: `deploy.yml` builds, pushes to GitHub Container Registry, SSHes into the instance and restarts the container.
4. No AWS keys are stored in GitHub (Learner Lab keys change every session).

## 6. Decisions to confirm with the team (the code uses these defaults)

- **Coverage rule.** Confidence is `high / medium / low` from two checks: at least 300 training snapshots in the
  candidate's ~2.8 km cell, 3-hour band and minutes-empty band (the historical baseline's own group), and 5+ completed
  waits nearby in the last 3 hours. Thin areas are kept with confidence `low`; candidates with under half of their
  features are dropped; if none are left the answer is "not enough data here". The historical curves in this repo
  fall back to city-wide groups, so they are not used as a candidate-level fallback. Knobs: `MIN_FEATURES_OK` in `recommend.py`.
- **Drive time** = road km / median speed of moving taxis around the driver (`speed_nbr_1h`, clipped to 8 to 45 km/h).
- **Features at arrival.** Features are read for the hour of the decision (no future data); only `minutes_empty` grows by D.
- **Demo day** is a validation day. Use a test-period day only after the one-time test run.
