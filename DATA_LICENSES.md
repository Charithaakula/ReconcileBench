# Data licenses

The code in this repository is MIT-licensed (see `LICENSE`). The task fixtures contain data
derived from two public sources, and those parts keep the licenses of their sources.

## VisText (GPL-3.0)

The VisText-General and VisText-Health workspaces use chart data and human-written captions from
VisText, which takes its charts from the Statista data released by Chart-to-Text. Both projects
are released under the GNU General Public License v3.0.

- VisText: Benny J. Tang, Angie Boggust and Arvind Satyanarayan. *VisText: A Benchmark for
  Semantically Rich Chart Captioning.* ACL 2023. <https://github.com/mitvis/vistext>
- Chart-to-Text: Shankar Kantharaj et al. *Chart-to-Text: A Large-Scale Benchmark for Chart
  Summarization.* ACL 2022. <https://github.com/vis-nlp/Chart-to-text>

The files derived from VisText are released under GPL-3.0:

- `tasks/general/`
- `tasks/general_propagation/`
- `tasks/general_criterion/`
- `tasks/general_noop/`
- `tasks/general_retraction/`
- `tasks/health/`

The VisText corpus itself is not included. The generators read it from
`sources/vistext/data_train.json`, or from the path in `RB_VISTEXT`
(download: <https://vis.csail.mit.edu/vistext/tabular.zip>).

## BixBench (Apache-2.0)

The BixBench-RNA workspaces are derived from one RNA-seq capsule
(`CapsuleData-15ff11e5-2db1-45b6-b3a3-46bc2a74b821`) in the BixBench dataset, released under the
Apache License 2.0.

- Ludovico Mitchener et al. *BixBench: A Comprehensive Benchmark for LLM-based Agents in
  Computational Biology.* arXiv:2503.00096, 2025.
  <https://huggingface.co/datasets/futurehouse/BixBench>

The files derived from the capsule are released under Apache-2.0:

- `tasks/rna_labels/`
- `tasks/rna_mixed/`
- `data/bixbench/`

## Paper

The paper in `paper/` is distributed under CC BY 4.0, as on OpenReview.
