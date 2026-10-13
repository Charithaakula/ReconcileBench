# Analysis plan

These parameters were fixed when the analysis was designed. They are not re-tuned when the data
changes.

- Counts are normalised to **counts per million** by library size before any filtering.
- A gene is **expressed** when it exceeds **1.0 CPM in at least 3 samples**;
  genes below that are excluded from every contrast.
- A contrast reports **fold change**, computed as `(mean CPM in A + 1) / (mean CPM in B + 1)`.
  The pseudocount of 1 is part of the definition and keeps a gene absent from both arms at 1.0
  rather than dividing by zero.
- Each contrast's ranked list carries its **18** most responsive genes.
- Group means are taken over the replicates the sample sheet assigns to each condition. The
  sample sheet is therefore upstream of every figure in this workspace.
