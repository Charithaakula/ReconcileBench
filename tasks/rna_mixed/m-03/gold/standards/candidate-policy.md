# Candidate policy

- The `qualifies` field records only numerical qualification: the candidate is in the contrast's
  top ten and its fold change is at least 2.0. Withdrawing evidence does not change its recorded
  rank, fold change, or numerical `qualifies` value.
- Evidence status uses the complete vocabulary `CURRENT` and `WITHDRAWN_QC`. Evidence withdrawn
  after a quality-control failure must be recorded as `WITHDRAWN_QC`.
- Active support requires both `status == CURRENT` and `qualifies == true`.
- Supports are independent only when their condition-specific sample sets are disjoint.
- The effective policy's `minimum_supports` determines `SUPPORTED` versus `NOT_ESTABLISHED`.
- `SUPPORTED` licenses `RUN_VALIDATION`; `NOT_ESTABLISHED` licenses `HOLD`.
- After a sample-label correction, the current top-ranked contrast gene with fold change at least
  2.0 has current finding `SUPPORTED`, is the validation target, and licenses `RUN_VALIDATION`.
- Dated decisions retain the policy version effective when they were made.
