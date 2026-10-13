# ReconcileBench

**Benchmarking state reconciliation in persistent scientific agents**

Sai Charitha Akula, Chanukya Vardhan Gujjula

NeurIPS 2026 Workshop on Agentic AI for Biological Discovery (AgenticLS) · **Oral**

[Paper (PDF)](paper/reconcilebench_agenticls2026.pdf) · [OpenReview](https://openreview.net/forum?id=4xdgvEUHI3)

---

Persistent scientific agents reuse their own outputs across rounds of work. When the evidence or
the analysis policy changes, that record can quietly become invalid. Some files must be updated,
others must stay as they are, and the effects cross structured data, computations, prose,
figures, tests and decisions.

ReconcileBench tests whether an agent can bring a scientific workspace back to a valid state
after an authoritative change. The agent receives the existing workspace and the change notice.
It does not receive the corrected reference or a list of the fields to fix.

The benchmark has three kinds of workspace:

- **VisText-General**: controlled analytical repositories built from published chart data, in
  which every dependency can be inspected.
- **VisText-Health**: the same construction on health and public-health series.
- **BixBench-RNA**: executable RNA-seq projects derived from a published computational-biology
  capsule, where sample metadata and evidence feed contrasts, findings and validation decisions.

## Episodes

Each model configuration runs 106 main episodes, plus 80 episodes that test restoration and
abstention.

| Group | Setting | Episodes | Tasks |
|---|---|---:|---|
| Propagation | VisText-General evidence correction | 20 | `tasks/general_propagation/evidence-atlas-NN` |
| | VisText-General review-rule revision | 20 | `tasks/general_propagation/policy-atlas-NN` |
| | VisText-Health evidence correction | 14 | `tasks/health/h-NN` |
| | BixBench-RNA condition-label correction | 6 | `tasks/rna_labels/b-0N` |
| | BixBench-RNA mixed evidence/policy | 6 | `tasks/rna_mixed/m-0N` |
| Conclusion maintenance | VisText-General prose evidence correction | 20 | `tasks/general/atlas-NN` |
| | VisText-General prose criterion revision | 20 | `tasks/general_criterion/atlas-NN-criterion` |
| Restoration | Withdrawn correction after 2, 6 or 12 turns | 60 | `tasks/general_retraction/atlas-NN-revert-{2,6,12}` |
| Abstention | Correction already applied | 20 | `tasks/general_noop/atlas-NN-noop` |

`harness/ids/` lists the task ids for each suite. [docs/tasks.md](docs/tasks.md) describes the
task format, the scored layers, the closure rule and each setting.

## Results

Episode closure for the 106 main episodes in mini-SWE-agent (paper, Table 5). An episode closes
only when every applicable check passes in the same final workspace.

| Agent | Propagation | Conclusion | Overall |
|---|---:|---:|---:|
| GPT-5.6-LUNA (low reasoning) | 18/66 | 4/40 | 22/106 (20.8%) |
| GPT-5.6-TERRA (low reasoning) | 23/66 | 17/40 | 40/106 (37.7%) |
| GPT-5.6-SOL (low reasoning) | 39/66 | 23/40 | 62/106 (58.5%) |
| Claude Haiku 4.5 (no thinking) | 8/66 | 2/40 | 10/106 (9.4%) |
| Claude Sonnet 5 (low effort) | 11/66 | 12/40 | 23/106 (21.7%) |
| Claude Opus 5 (low effort) | 25/66 | 22/40 | 47/106 (44.3%) |

The same models in their native harnesses (paper, Table 7):

| Agent | Harness | Main episodes | Already applied | Retraction |
|---|---|---:|---:|---:|
| GPT-5.6-SOL | mini-SWE-agent | 62/106 | 10/20 | 0/60 |
| GPT-5.6-SOL | Codex CLI | 66/106 | 4/20 | 0/60 |
| Claude Opus 5 | mini-SWE-agent | 47/106 | 13/20 | 2/60 |
| Claude Opus 5 | Claude Code | 67/106 | 8/20 | 2/60 |

This repository releases the benchmark: tasks, generators, graders and the agent harnesses.
Per-episode model outputs are not included.

## Repository layout

| Path | Contents |
|---|---|
| `tasks/` | The 186 episodes, one folder per setting |
| `reconcilebench/` | Shared library: workspace generators, deterministic grader, prose judge |
| `generators/` | Scripts that build and check every task folder |
| `harness/` | mini-SWE-agent runner, model configs and task id lists; Codex CLI and Claude Code wrappers |
| `scorers/` | Per-setting scoring scripts and the drivers that score a full run |
| `data/bixbench/` | The BixBench capsule files the RNA tasks are built from |
| `docs/` | Task format, and how to run, score and rebuild |
| `paper/` | Paper PDF |

## Quick start

Requires Python 3.13 and, for the native harnesses, Docker.

```bash
git clone https://github.com/Charithaakula/ReconcileBench.git
cd ReconcileBench
python3.13 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
```

Check the grader without any API key. The gold workspace should pass every site and the
starting workspace should fail them all:

```bash
python - <<'EOF'
import json, shutil, sys, tempfile
sys.path.insert(0, 'reconcilebench')
import grade_vis_atlas as G
task = json.load(open('tasks/general/atlas-01/task.json'))
for tree in ('gold', 'workspace'):
    root = tempfile.mkdtemp() + '/w'
    shutil.copytree(f'tasks/general/atlas-01/{tree}', root)
    print(tree, G.grade(root, task['exp'])['rr'])
EOF
# gold 27/27
# workspace 0/27
```

On macOS the grader runs model-written tests and SVG under `sandbox-exec`. Build the virtual
environment from a Homebrew, python.org or uv-managed Python; a Python installed inside your home
folder, such as pyenv, can fail to start inside the sandbox. On Linux, see
[docs/running.md](docs/running.md#grading).

Run one episode with GPT-5.6-SOL in mini-SWE-agent:

```bash
export OPENAI_API_KEY=...
harness/run_suite.sh prose_evidence gpt-5.6-sol atlas-01 1
```

Run and score the full protocol for one model:

```bash
harness/run_model_full.sh gpt-5.6-sol
scorers/score_mini_run.sh gpt-5.6-sol
```

[docs/running.md](docs/running.md) covers the harness settings, isolation, the Codex CLI and
Claude Code runs, and scoring.

## Data and licenses

The code is released under the [MIT License](LICENSE). Task fixtures derived from VisText are
released under GPL-3.0, and the BixBench capsule files under Apache-2.0. See
[DATA_LICENSES.md](DATA_LICENSES.md).

## Citation

```bibtex
@inproceedings{akula2026reconcilebench,
  title     = {{ReconcileBench}: Benchmarking State Reconciliation in Persistent Scientific Agents},
  author    = {Akula, Sai Charitha and Gujjula, Chanukya Vardhan},
  booktitle = {NeurIPS 2026 Workshop on Agentic AI for Biological Discovery},
  year      = {2026},
  url       = {https://openreview.net/forum?id=4xdgvEUHI3}
}
```
