# Running and scoring

All commands run from the repository root.

## Setup

```bash
python3.13 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
```

`harness/requirements.lock.txt` pins the runner's complete dependency tree.

API keys come from the environment, or from a git-ignored `.env` file at the repository root that
the scripts load:

```
OPENAI_API_KEY=...       # GPT-5.6 agents and the prose judge
ANTHROPIC_API_KEY=...    # Claude agents
```

Run outputs go to `runs/`, `results/`, `traces/` and `logs/` at the repository root. All four
are git-ignored.

## mini-SWE-agent

`harness/run_tasks.py` drives upstream mini-SWE-agent (commit `04d809ce`, version 2.4.6). It
delivers the task's turns in one conversation and copies only `workspace/` into the agent's
environment.

| Setting | Value |
|---|---|
| Steps per turn | 12 |
| Steps per episode | 60 (400 for retraction episodes) |
| Response length | 4,096 tokens |
| Wall-clock limit | 1 hour per episode |

Model configurations live in `harness/models/`:

| File | Model |
|---|---|
| `gpt-5.6-luna.yaml`, `gpt-5.6-terra.yaml`, `gpt-5.6-sol.yaml` | GPT-5.6 at low reasoning, merged over `harness/config.yaml` |
| `claude-haiku-4-5.yaml` | Claude Haiku 4.5 without extended thinking |
| `claude-sonnet-5.yaml`, `claude-opus-5.yaml` | Claude Sonnet 5 and Opus 5 at low effort |
| `<model>-retraction.yaml` | The same models with the 400-step budget for retraction |

The Claude files are complete configs. `harness/run_suite.sh` detects which kind it has been given.

One suite:

```bash
harness/run_suite.sh <suite> <model> <ids-or-@file> [shards]
harness/run_suite.sh health claude-opus-5 @harness/ids/health.txt 3
```

The suites are `general_propagation`, `health`, `rna_labels`, `rna_mixed`, `prose_evidence`,
`prose_criterion`, `noop` and `retraction` ([tasks.md](tasks.md#settings) maps them to task
folders).

The full protocol for one model (106 main episodes, 20 no-op, 60 retraction):

```bash
harness/run_model_full.sh gpt-5.6-sol
harness/run_model_full.sh claude-opus-5
```

### Isolation

`RB_ENV` selects the environment (default `local`).

- **`local`** (macOS) runs each command under `sandbox-exec`. The profile denies reads and writes
  to this repository, which holds gold, and to every other episode's workspace. It also denies
  the mini-SWE-agent credential folder, outbound network, and writes to the user's Python package
  folders. API keys are removed from the agent's shell environment. List any other folder that
  holds gold or earlier runs in `RB_EXTRA_DENY`, separated by `:`. The paper's mini-SWE-agent
  runs used this mode. Agents had the host's Python 3.9 with matplotlib 3.9.4 and Pillow 11.3.0.
- **`docker`** runs each episode in `python:3.13-slim` with `--network=none` and only the
  workspace mounted. That image has no matplotlib, so agents there cannot re-render the PNG
  figures.

## Codex CLI

```bash
docker build -t reconcilebench-codex:0.157.1 harness/codex
# put a Codex login at harness/codex/auth/auth.json (git-ignored)
harness/codex/run_full.sh
```

`harness/codex/run_full.sh` runs the full protocol for GPT-5.6-SOL at low reasoning, one Docker
container per episode, sequentially. One suite:

```bash
cd harness/codex
python3 run_codex.py --suite noop --tasks-dir ../../tasks/general_noop --ids atlas-01-noop
```

Add `--dry-run` to replace Codex with a stub that makes no model calls. Each episode gets a fresh
container and a fresh `CODEX_HOME` built from `harness/codex/home_template/config.toml`:
GPT-5.6-SOL at low reasoning, workspace-write sandbox, no network, approval policy `never`, and
web search, plugins, browser and computer-use features off. The config is validated with
`--strict-config` on every turn. The turns are delivered with `codex exec` and then
`codex exec resume`. A failed or timed-out turn marks the episode invalid; invalid episodes are
not scored. Login tokens are removed from the saved event logs.

## Claude Code

```bash
docker build -t reconcilebench-claude-code:2.1.289 harness/claude_code
docker build -t reconcilebench-claude-code:2.1.289-mpl3.9.4 \
  -f harness/claude_code/Dockerfile.mpl harness/claude_code
export ANTHROPIC_API_KEY=...
harness/claude_code/run_full.sh
```

Each episode gets a fresh container and HOME. The settings file turns on Claude Code's command
sandbox with no network and denies WebFetch and WebSearch. The `mpl` image adds matplotlib 3.9.4,
Pillow 11.3.0 and zlib-ng, so charts the agent re-renders are byte-identical to the shipped ones.
The containers run with relaxed seccomp and `/proc` masking so that Claude Code's bubblewrap
sandbox can start.

Both wrappers write the mini-SWE-agent layout: final workspaces under
`runs/<suite>/<label>_0/<id>_<model>/`, event logs and session transcripts under
`traces/<suite>/`, and one record per episode in `results/<suite>/res_<label>_0.jsonl`.

## Scoring

```bash
# mini-SWE-agent runs
scorers/score_mini_run.sh gpt-5.6-sol
scorers/score_mini_run.sh claude-opus-5

# Codex CLI and Claude Code runs: <label> <workspace-suffix>
scorers/score_harness_run.sh codex-gpt-5.6-sol gpt-5.6-sol
scorers/score_harness_run.sh claude-code-opus-5 claude-opus-5-cc
```

The workspace suffix is the last part of each run folder name, for example
`runs/general_propagation/claude-code-opus-5_0/evidence-atlas-01_claude-opus-5-cc`.

The scorers write `results/<suite>/scored_<model>.json` for each setting (VisText-General's
evidence and rule rows go to `results/general_evidence/` and `results/general_rule/`). These
files give per-episode outcomes and the summary rows of the paper's tables. Prose sites call the
GPT-5.6-SOL judge, so scoring needs `OPENAI_API_KEY`; judge verdicts are cached under `results/`.

### Grading

The deterministic grader runs two kinds of model-written code: the workspace's test file and its
SVG figure. On macOS it runs both under `sandbox-exec`, with this repository and the home folder
blocked, so the code cannot read gold. The sandbox re-opens only the interpreter's own folders:
the virtual environment, and the base Python if it lives outside your home folder (Homebrew,
python.org) or is uv-managed (`~/.local/share/uv`). A base Python elsewhere in your home folder,
such as pyenv, can fail to start inside the sandbox; use one of the others and pass it to the
scorers as `GRADE_PYTHON` if it is not the active one.

Without `sandbox-exec` (for example on Linux) the grader refuses to run that code unless you set
`RB_ALLOW_UNSANDBOXED_TESTS=1` and `RB_ALLOW_UNSANDBOXED_RENDER=1`. Do that only inside a
container that cannot see gold.

## Rebuilding fixtures

The fixtures are frozen. See [tasks.md](tasks.md#provenance-and-rebuilding) for which ones
rebuild byte for byte.

```bash
python generators/make_noop.py $(seq -f 'atlas-%02g' 1 20)
python generators/make_retraction.py $(seq -f 'atlas-%02g' 1 20)
python generators/make_criterion.py $(seq -f 'atlas-%02g' 1 20)
python generators/make_general_propagation.py && python generators/check_general_propagation.py
python generators/make_rna_labels.py
python generators/select_rna_mixed.py && python generators/make_rna_mixed.py
python generators/check_rna_mixed.py
```

These commands rewrite the fixtures in place. `git status` shows any difference from the
released versions.
