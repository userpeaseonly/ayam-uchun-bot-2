# Versioned Rasch practice scoring

New assessments use `tests.scoring_method = rasch_v1`. Migration 7 preserves
**all existing active and finished assessments** as `legacy_tertile`; opening a
new session from an old template creates a new Rasch assessment. No previously
published score is converted. No additional environment variables or packages
are required. Deployment's usual pre-update SQLite backup remains necessary;
an old image cannot read a database migrated past its supported schema version.

## Statistical contract

- Dichotomous Rasch/1PL: `P(X_ni=1) = logistic(theta_n - b_i)`, discrimination 1,
  no guessing parameter or difficulty-dependent point weights.
- Complete, settled 0/1 answers only. Skipped answers, including timed expiry,
  are incorrect. AI grading is still a rubric-driven correctness decision, not
  the Rasch estimator. Teacher overrides must settle before finalization.
- Open answers and multipart parent questions are currently whole-item 0/1.
  `Question.points` is retained for document/legacy compatibility but is not a
  Rasch weight. There is **no partial-credit or essay model yet**. Do not claim
  that this implements the full Ona tili certificate, which includes a separate
  rubric-scored essay section. A future PCM/essay feature needs its own response
  schema, rubrics, validation and scoring version, not fractional binary inputs.
- Item difficulties: marginal maximum likelihood, EM with fixed standard-normal
  latent population. Integration uses nodes -7..7 at 0.125-logit increments,
  normalized normal weights. EM limit 400, tolerance 1e-7. Item Newton steps are
  bounded, with a numerical safety range of -12..12 logits. Nonconvergence
  suppresses scores; the algorithm does not substitute raw percentages.
- Everyone-correct/everyone-wrong items have no finite unregularized item
  estimate. They remain in correctness totals but are excluded from calibration
  and ability estimation. Their difficulty is NULL, never an invented logit.
- Persons: expected-a-posteriori estimate and posterior SD conditional on fitted
  item difficulties, using N(0,1). All-wrong and perfect-person estimates remain
  finite. This SD does not include item-calibration uncertainty.
- All students answer the same items, so equal raw totals yield equal abilities,
  T-scores and ranks, regardless of which questions were correct. Rankings use
  competition ties (1,2,2,4), not submission time or rounded displayed scores.
- Standardization: `T = 50 + 10*(theta - cohort_mean)/cohort_sd`; the mean and
  **population** SD of this session's EAP estimates are frozen at finalization.
  These are local group norms, **not** agency reference norms. T is not a
  percentage; values are not clipped to 0..75. There is no official certificate
  grade or pass/fail label.

## Reliability and limitations

All generated scores are labelled **Rash modeli asosidagi mashq natijasi** and
remain provisional. A cohort below 100 or fewer than 20 informative questions
gets a warning: these are product warning thresholds, not psychometric
guarantees. EAP reliability is a descriptive variance ratio
`var(EAP)/(var(EAP)+mean(posterior variance))`; values below .7 are flagged.
Item infit is a descriptive information-weighted residual statistic evaluated
at EAP estimates, not a Winsteps-equivalent inferential test; values above 1.5
are flagged for review. These checks do not establish unidimensionality, local
independence, absence of cheating or model fit.

Empty/one-person cohorts, cohorts with no variable items, identical total scores,
or failed estimation have NULL score and rank. Raw correctness remains visible.
The UI distinguishes this finished/unavailable state from waiting for grading.
An extreme person in an otherwise informative cohort can receive an EAP score;
an entire all-perfect/all-zero cohort cannot be standardized.

Small or self-selected groups can produce very different local T-scores for
similar performance. Do not compare across tests/sessions or present these as
official score predictions. Cross-session linking requires versioned common-item
anchors/reference norms, representative data and drift/fit checks. Stored item
parameters make that work possible later; automatic pooling of separate
cohorts is deliberately not implemented.

## Persistence and access

Finalization retains one consistent SQLite transaction and runs numerical work
in a worker thread. It rechecks owner, active timers, settled grading and complete
answer rows. The final response matrix is hashed and a calibration snapshot
stores estimator/version, UTC timestamp, settings, cohort counts, informative
items, item/person IDs and estimates, normalization, diagnostics and warnings.
`questions.difficulty_logit/infit`, `submissions.rasch_theta/rasch_se` and
`total_score/rank` are saved in batch. Per-answer `points_awarded` and Rasch
`assigned_points` are NULL because T is not additive.

Repeated finalization returns stored metadata without recalibrating, changing
ranks, or duplicating notifications. Students receive correctness immediately;
only after finalization do they receive their score/rank and an allowlisted
method/quality summary. Other students' abilities, item parameters and the full
snapshot stay out of student payloads. Teacher reports include logit analysis,
posterior SDs, limitations and the complete snapshot split into Excel-safe cells.

## Validation and sources

- The production estimator is tested against the five fixed-discrimination
  `ltm::rasch(LSAT, constraint=cbind(6,1))` item difficulties published by the
  package's author in [Rizopoulos (2006), JSS 17(5)](https://www.jstatsoft.org/article/view/v017i05).
  The 1,000-person, five-item LSAT response-frequency fixture reproduces all five
  published estimates within 0.00002 logits. No R runtime is needed in production.
- Tests cover equal-score sufficiency, item/person permutation, extreme persons
  and items, missing/nonbinary rejection, nonconvergence, immutable finalization,
  legacy migrations, privacy/reveal, exports and simultaneous submissions.
- [Official published assessment methodology](https://api-portal.gov.uz/uploads/165/2025/04/28/f53977fc-ca3e-a802-d526-5d8c56df946b_media_.pdf)
  specifies Rasch ability standardization followed by `T=50+10Z`, and separately
  describes the essay rubric/scale conversion and combining the sections. It
  does not establish that our calibration, reference population, estimation
  choices or local practice T-scores reproduce the agency's operational scores.
