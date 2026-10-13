# Chart atlas — working notes

## What is here

`data/charts.csv` lists every chart in this atlas. For each, `data/<id>/values.csv` is the
**source of record**. Nothing else in this workspace is authoritative; everything else is
derived from those files.

## How the pieces depend on each other

Derived files are named by workstream codename, not by chart id. `analysis/INDEX.md` maps
one to the other. The layout is flat.

    data/<id>/values.csv ──> analysis/<code>-review.md      harvested prose
                         ──> analysis/<code>-ranking.md     its entries, ranked
                         ──> analysis/<code>-stats.json     leader, mean, above-mean,
                         |                                  share, verdict
                         ──> analysis/<code>-segment.md     leader against runner-up
                         ──> analysis/<code>-profile.md     in-chart sweeps
                         ──> analysis/<code>-narrative.md   commentary
                         ──> analysis/<code>-relations.md   rank, ratios, thresholds
                         ──> analysis/<code>-editorial.md   editorial characterisation
                         ──> figs/<id>.png                  built by scripts/render_charts.py
                         ──> figs/<id>.svg                  maintained by hand
                         ──> tests/test_atlas.py            asserts the leader and value

    every analysis/<code>-stats.json ──> docs/dashboard.md  built by scripts/build_dashboard.py
    every data/<id>/values.csv       ──> analysis/overview.md      highest single value
                                     ──> analysis/atlas-stats.md   atlas-wide aggregates
                                     ──> analysis/leader-index.md  mean of chart leaders
                                     ──> analysis/portfolio-brief.md  count above a threshold
                                     ──> analysis/record-holder.md    who holds the record

## Consistency requirement

**Every derived file in this workspace must agree with the sources of record at all
times** — everything under `analysis/` and `docs/`, the figures under `figs/` (both the
rendered `.png` and the hand-maintained `.svg`), and the assertions in `tests/`. A derived
file that contradicts a source of record is a defect, and fixing it is part of whatever
work uncovered it — it does not need to be requested separately.

`analysis/revision-log.md` is the exception: it records what was believed on a given date
and must never be rewritten to match today's data.

`notes/methodology.md` describes collection procedure only and depends on no value.

## Where the contrast tables come from

`data/counts_raw_unfiltered.csv` and `data/sample_layout.csv` are the sources of record for this
experiment; `data/ensg_to_gene_name.tsv` maps gene identifiers to symbols. Every
`data/<contrast>/values.csv` is **derived** from those three by `scripts/derive_contrasts.py`,
under the parameters fixed in `notes/analysis-plan.md`.

The sample sheet is upstream of everything: it decides which replicates form each condition, so
it determines every group mean, every fold change and every ranked list in this workspace.
