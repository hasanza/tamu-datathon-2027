# Deploying the Control Tower

One Docker image serves the API and the built UI on port 8080. Two environment variables:
`GEMINI_API_KEY` (the model) and `CT_ACCESS_PASSWORD` (the browser asks once for a password; the user name is ignored;
leave it unset and there is no gate). `/healthz` is always open.

## Run the image locally
```bash
docker build -t ct .
docker run -p 8080:8080 -e GEMINI_API_KEY=... -e CT_ACCESS_PASSWORD=demo ct
# open http://localhost:8080 , password: demo
```

## Fly.io (recommended: always on, keeps its disk)
Cost: one shared-cpu 1 GB machine is a few USD a month, plus a 1 GB volume (cents). Fly asks for a card.
1. Install flyctl: `brew install flyctl` (or https://fly.io/docs/flyctl/install/), then `fly auth login`.
2. `fly launch --no-deploy --copy-config` (keep the name in `fly.toml`, or pick another and edit it).
3. `fly volumes create ct_data --size 1 --region dfw`
4. `fly secrets set GEMINI_API_KEY=... CT_ACCESS_PASSWORD=...`
5. `fly deploy`

Or push to the `deploy` branch: `.github/workflows/deploy-fly.yml` deploys it once the repo has the secret
`FLY_API_TOKEN` (create one with `fly tokens create deploy`). If the repo also has the secrets `GEMINI_API_KEY` and
`CT_ACCESS_PASSWORD`, the workflow sets them on the app first.

Run results (traces, action log) live on the volume at `/app/data`, so they survive restarts and deploys.

## Render (free, simplest, weaker)
1. Render dashboard, New, Blueprint, connect this repo, branch `deploy` (it reads `render.yaml`).
2. Fill `GEMINI_API_KEY` and `CT_ACCESS_PASSWORD` when asked.

Cost: free plan. It sleeps after 15 minutes without traffic (the first request then takes about a minute), and the
disk is wiped on every restart or deploy, so run results vanish; start a run again after waking it. 512 MB of memory
may be tight during a parallel run.

## Notes
- "Run feed" starts the organizers' enterprise server and an MCP server as child processes inside the same container
  and calls Gemini (about 1 USD per full run). Use one run at a time.
- The entrypoint (`scripts/docker-entrypoint.sh`) links `runs/live` and `traces/live` to `RUN_DIR` / `TRACES_DIR`,
  because the API and pipeline write to those repo paths.
