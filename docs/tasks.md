# Tasks

## What an episode is

A **workspace** is one persistent project file tree. An **episode** is one agent run on a copy of
that workspace. The agent gets a short sequence of turns in one conversation. Early turns are
ordinary work on the project, such as reading the README or answering a question about a chart. One
turn announces an **authoritative transition**: a corrected source value, a revised analysis
rule, a withdrawn correction, or a correction that is already in place.

The agent never sees the corrected reference, the generator that built it, or a list of the
fields to fix. It has to work out which records the transition affects and whether each one must
change or stay as it is.

## Settings

| Folder | Setting (paper, Table 1) | Episodes | Ids |
|---|---|---:|---|
| `tasks/general_propagation` | VisText-General evidence correction and review-rule revision | 40 | `evidence-atlas-NN`, `policy-atlas-NN` |
| `tasks/health` | VisText-Health evidence correction | 14 | `h-NN` |
| `tasks/rna_labels` | BixBench-RNA condition-label correction | 6 | `b-0N` |
| `tasks/rna_mixed` | BixBench-RNA mixed evidence/policy | 6 | `m-0N` |
| `tasks/general` | VisText-General prose evidence correction | 20 | `atlas-NN` |
| `tasks/general_criterion` | VisText-General prose criterion revision | 20 | `atlas-NN-criterion` |
| `tasks/general_retraction` | Withdrawn correction after 2, 6 or 12 turns | 60 | `atlas-NN-revert-{2,6,12}` |
| `tasks/general_noop` | Correction already applied | 20 | `atlas-NN-noop` |

The 20 VisText-General workspaces in `tasks/general` are also the base of the other four
VisText-General folders. `harness/ids/<suite>.txt` lists each suite's ids; the suite names used by
the runner and the scorers are the folder names, except `prose_evidence` (`tasks/general`),
`prose_criterion` (`tasks/general_criterion`), `noop` and `retraction`.

## Task layout

Every task folder has the same shape:

```
<task-id>/
  task.json     turns, grading data
  workspace/    what the agent starts from
  gold/         the corrected reference; never shown to the agent
```

The runner copies only `workspace/` into the agent's environment. `gold/` and `task.json` stay
outside it. The typed General episodes (`tasks/general_propagation`) have no `gold/`: they are
scored on exact field values recorded in `task.json`.

Three folders reuse the base workspaces through relative links:

| Folder | `workspace` | `gold` |
|---|---|---|
| `tasks/general_noop/atlas-NN-noop` | `../../general/atlas-NN/gold` | `../../general/atlas-NN/gold` |
| `tasks/general_retraction/atlas-NN-revert-{2,6,12}` | `../../general/atlas-NN/workspace` | `../../general/atlas-NN/gold` |
| `tasks/general_criterion/atlas-NN-criterion` | `../../general/atlas-NN/workspace` | its own tree |

In the no-op tasks the workspace already equals gold, so the correct response is to edit
nothing. In the retraction tasks a correction is applied and later withdrawn after 2, 6 or 12
intervening turns; the agent must then restore the original workspace.

`task.json` always holds `id`, `turns` and `probe`, which tells the runner how to grade:

| `probe` | Graded | Grading data |
|---|---|---|
| `ATLAS` | in the run, by `reconcilebench/grade_vis_atlas.py` | `exp`: the graded sites, the files as shipped, the corrected sources and every expected value |
| `RNA_MIXED` | in the run, by `scorers/score_rna_mixed.py` | `fields`: each scored field's file, JSON pointer, starting value, reference value and operation |
| `TYPED` | afterwards, by `scorers/score_general_records.py` and `score_general_evidence.py` | `typed`: the expected criterion truth and review decision, and the held-fixed value |
| `NOOP`, `REVERT` | afterwards, by `scorers/score_noop.py` and `score_retraction.py` | the base episode's `exp` |

The criterion-revision tasks are ATLAS tasks with an extra `criterion` block that
`scorers/score_prose_criterion.py` reads.

## Scored layers

Each scored field has a semantic layer and a required operation.

| Layer | Δ: must change | K: must stay valid |
|---|---|---|
| Direct source or rule | Correct a chart row or RNA label; withdraw evidence; revise a threshold | Keep source data fixed during a rule change, or the rule fixed during a data correction |
| C1 computation | Recompute a mean, ratio, contrast quantity or support count | Keep the observed ratio during a rule change, or an unaffected count |
| C2 relation or representation | Repair a leader, rank, evidence join, test assertion, dashboard or SVG | Keep an unaffected relation or figure valid |
| C3 conclusion or action | Revise criterion truth, a review flag, a finding or an action | Keep a dated or still-supported conclusion valid |

The same record can need Δ under one transition and K under another. An observed ratio is C1-Δ
after a data correction and C1-K after a rule revision.

## Closure

An episode **closes** only when every applicable check passes in the same final workspace.

- **Propagation episodes (66):** the announced source or rule, every affected C1 and C2 record,
  and their preservation checks.
- **Conclusion-maintenance episodes (40):** the criterion claim and its dependent review flag,
  whether the transition calls for revision or preservation.
- **Restoration (60):** the evaluated files return to the earlier workspace.
- **Abstention (20):** the already-correct workspace is left unchanged.

Many correct local edits do not make up for one stale or wrongly changed record.

## Graders

- **Deterministic checks** (`reconcilebench/grade_vis_atlas.py` and the suite scorers) compare
  source rows, JSON values, ordered lists, painted SVG bar geometry with its leader label, and the
  workspace's test file, which must pass on the corrected data and fail on the stale data.
- **Prose checks** use GPT-5.6-SOL at low reasoning effort as a proposition judge, with one vote
  per site (`reconcilebench/judge_claim.py`, `reconcilebench/judge_compare.py`). The judge
  receives code-derived target propositions and the relevant file text, never the reference
  wording. Set `CLAIM_JUDGE_MODEL` to use another judge.

## VisText-General and VisText-Health

Each workspace is an atlas of 30 to 60 published VisText charts: source CSVs under `data/`, and
for every chart a ranked list, statistics, a profile, a narrative, relational notes and a figure,
plus atlas-wide dashboards, a revision log and a test suite. One authoritative transition
overwrites or deletes values in one chart.

`tasks/health` holds 14 of the 16 generated Health workspaces. `h-11` and `h-12` were left out
because their corrected reference captions are stale. The 14 cover six health and public-health
series; eight of their transitions overwrite a value, four delete an entity and two do both.

## BixBench-RNA condition-label correction

Six RNA-seq workspaces (`tasks/rna_labels/b-01` to `b-06`; paper, Figure 3). Each starts from one
BixBench capsule (`data/bixbench`): a count matrix of 63,677 genes and a 30-sample sheet with ten
conditions in triplicate. Each workspace records one sequenced library under the wrong
experimental condition. The correction changes no raw count; it changes group membership, and
through it the condition means, fold changes, ranked genes, figures, dashboard, tests, summaries
and review state.

## BixBench-RNA mixed evidence/policy

Six small RNA-seq projects (`tasks/rna_mixed/m-01` to `m-06`). Each connects sample metadata and
two independent lines of evidence to candidate findings and to the validation actions a written
support policy licenses. The single turn states the authoritative transition and asks for full
reconciliation; it names no downstream file and states no answer.

| Case | Transition | Correct response |
|---|---|---|
| `m-01` | Sample 6-3 is relabelled from `Cisplatin_IC50` to `Cisplatin_IC50_Serum_starvation_16h`; raw counts do not change | Recompute the contrast: its leader moves from NR4A3 (14.446-fold) to ENSG00000258486 (2.852-fold), which becomes the validation target |
| `m-02` | Evidence E1 is withdrawn after a QC failure for AHRR | Drop E1 from current support (two supports to one) but keep `SUPPORTED` and `RUN_VALIDATION`: E2 still qualifies |
| `m-03` | The same withdrawal, for CYP1A1 | Its only support lapses: the finding becomes `NOT_ESTABLISHED` and the action `HOLD` |
| `m-04` | Policy P1 raises the required independent supports from two to three; evidence is fixed | AHRR becomes `NOT_ESTABLISHED`, action `HOLD`; the dated P0 decision stays as it was |
| `m-05` | Policy P1 lowers the required supports from three to two | AHRR becomes `SUPPORTED`, action `RUN_VALIDATION`; evidence and the dated P0 state stay |
| `m-06` | All three kinds of transition in one project | Worked out jointly through the shared policy, not by adding up the standalone answers |

`m-02` and `m-03` make the same withdrawal call for opposite conclusion operations (paper,
Figure 4): losing a support is not evidence for the negation, and keeping every finding after a
withdrawal is also wrong.

The rules the agent can see, in `standards/candidate-policy.md` and
`standards/candidate-policy.json`:

1. `qualifies` records numerical qualification only: the gene is in the contrast's top ten and its
   fold change is at least 2.0. Withdrawing the evidence does not change it.
2. Evidence status is `CURRENT` or `WITHDRAWN_QC`; only `CURRENT` evidence that qualifies is
   active support.
3. Two supports are independent when their condition-specific sample sets are disjoint.
4. A finding is `SUPPORTED` when its active independent supports reach the effective policy's
   `minimum_supports`, otherwise `NOT_ESTABLISHED`.
5. `SUPPORTED` licenses `RUN_VALIDATION`; `NOT_ESTABLISHED` licenses `HOLD`.
6. After a sample-label correction, the current top-ranked contrast gene with fold change at
   least 2.0 is `SUPPORTED`, is the validation target and licenses `RUN_VALIDATION`.
7. Dated decisions keep the policy version in force when they were made.

The two lines of evidence, computed from the capsule:

| Evidence | Contrast | Gene | Rank | Fold change | Qualifies |
|---|---|---|---:|---:|---|
| E1 | `CBD_IC50_vs_Cisplatin_IC50` | AHRR | 1 | 3.360 | yes |
| E2 | `CBD_IC50_Serum_starvation_16h_vs_Cisplatin_IC50_Serum_starvation_16h` | AHRR | 8 | 3.522 | yes |
| E1 | `CBD_IC50_vs_Cisplatin_IC50` | CYP1A1 | 2 | 3.039 | yes |
| E2 | `CBD_IC50_Serum_starvation_16h_vs_Cisplatin_IC50_Serum_starvation_16h` | CYP1A1 | outside the top ten | -- | no |

Each standalone case scores 12 fields: one direct field (the sample label, evidence status or
policy), three C1 computations, three C2 relations or representations (including the figure), two
C3 records (the complete current finding and the licensed action) and three protected fields (the
dated finding and action, and an unaffected control), which must not change. A field's operation,
change or preserve, follows from comparing its starting and reference values, so a C1-C3 field
can be a required preservation, as in `m-02`. The compound case scores 20 fields, with shared
descendants counted once.

## Provenance and rebuilding

The fixtures are the versions used in the paper. Most rebuild from the code in this repository:

| Fixtures | Rebuild | Status |
|---|---|---|
| `tasks/general_noop` | `generators/make_noop.py` | Identical |
| `tasks/general_retraction` | `generators/make_retraction.py` | Identical |
| `tasks/general_criterion` | `generators/make_criterion.py` | Identical |
| `tasks/general_propagation` | `generators/make_general_propagation.py` | Identical; `check_general_propagation.py` audits it |
| `tasks/rna_labels` | `generators/make_rna_labels.py` | Identical, rebuilt from each `task.json` and the capsule |
| `tasks/rna_mixed` | `generators/select_rna_mixed.py`, then `make_rna_mixed.py` | Identical; `check_rna_mixed.py` runs 425 construction checks |
| `tasks/general`, `tasks/health` | `generators/make_general.py`, `generators/build_health.sh` | Frozen; the current generator does not rebuild them byte for byte |

The original workspace and gold trees of the six RNA condition-label tasks were not kept. The
trees in `tasks/rna_labels` were rebuilt from the `task.json` records (which hold the text of
every graded file) and the capsule; the rebuild reproduces every graded text file, the figures
and the corrected sample sheets those records give.

`generators/make_general.py` builds one workspace from one window of the chart pool and exits
non-zero when that window yields no workspace that satisfies its construction checks; viable
windows are uncommon, so try other `--seed` or `--offset` values. `generators/build_health.sh`
searches seeds for each Health workspace in the same way.

The VisText generators need the VisText corpus
(<https://vis.csail.mit.edu/vistext/tabular.zip>). Put `data_train.json` at
`sources/vistext/data_train.json` or point `RB_VISTEXT` at it. Rendering the figures byte for
byte needs matplotlib 3.10.7; `RB_RENDER_PYTHON` selects the interpreter that renders them.
