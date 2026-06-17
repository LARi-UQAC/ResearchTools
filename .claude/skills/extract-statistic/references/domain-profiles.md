# Domain profiles

The domain-specific checks for Step 6 of [statistical-audit-protocol.md](statistical-audit-protocol.md).
Two profiles ship: `engineering` (default, the lab's scope) and `cosmetic` (preserved from the
original downloaded agent). A profile's flags fire only when its study type is detected in the
manuscript.

## Profile selection

1. Explicit `--profile engineering` or `--profile cosmetic` wins.
2. Otherwise auto-detect from the manuscript text:
   - `engineering` signals: named algorithm or model (CNN, transformer, Kalman filter, PID, MPC, RL,
     SVM), hardware/system terms (FPGA, actuator, sensor, controller, robot, exoskeleton),
     dataset/benchmark names, ML metrics (accuracy, F1, AUC, RMSE, mAP, IoU), "train/test split",
     "cross-validation", "seed".
   - `cosmetic` signals: SPF, photoprotection, sunscreen, UVA/UVB, microbiome, 16S, dermatology,
     formulation, sensory panel, in vitro skin substrate.
3. No clear signal: default to `engineering`. If both are present, run `engineering` and note the
   cosmetic signals in the report so the user can re-run with `--profile cosmetic`.

## Profile: engineering (default)

The lab works in control theory, industrial automation, robotics, path planning, GEMMA, AMDEC,
diagnosis, deep learning, LLM/VLM. The recurring statistical failures in this scope are
machine-learning evaluation errors and under-reported variability.

**Machine learning / deep learning evaluation:**
- `[STATS DATA LEAKAGE RISK]` if preprocessing, feature selection, or normalization is described as
  fit on the full dataset before the train/test split, or if no split protocol is stated.
- `[STATS SPLIT UNREPORTED]` if results are reported without naming the train/validation/test split or
  the cross-validation scheme (k-fold, leave-one-subject-out, temporal split).
- `[STATS NO VARIANCE OVER RUNS]` if a single point metric is reported for a stochastic model (random
  init, SGD) without standard deviation or CI over multiple seeds/runs.
- `[STATS IMBALANCE METRIC MISUSE]` if accuracy is the headline metric on an imbalanced dataset without
  a balanced metric (F1, balanced accuracy, MCC, AUC-PR).
- `[STATS NO SIGNIFICANCE ON DELTA]` if a model is claimed better than a baseline on a benchmark delta
  without a paired significance test or overlapping-CI check across runs.
- `[STATS EFFECT SIZE MISSING]` (benchmark variant) if a "+X%" improvement is reported with no absolute
  numbers, no variance, and no effect size, so its practical relevance cannot be judged.
- `[STATS OPTIMISTIC TUNING]` if hyperparameters or model selection were tuned on the test set, or the
  same test set is reused across many reported configurations without correction.

**Control / signal processing:**
- `[STATS REPEATABILITY UNREPORTED]` if a controller/estimator performance figure (settling time,
  overshoot, tracking error) is given without repetition count or run-to-run variability.
- `[STATS SNR UNREPORTED]` if a signal-processing result depends on noise level but no SNR or noise
  model is stated.

**Robotics / experimental systems:**
- `[STATS TRIAL COUNT LOW]` if a success rate is reported from too few trials to support it (state the
  number of trials; a rate from < 10 trials needs a CI and a caveat).
- `[STATS SUCCESS RATE NO CI]` if a success/failure proportion is reported without a confidence
  interval (Wilson or Clopper-Pearson for small n).

## Profile: cosmetic

Preserved from the original statistics agent for formulation, SPF, microbiome, and dermatology work.

**SPF and photoprotection:**
- `[STATS ISO PROTOCOL UNSTATED]` if SPF values are reported without the measurement standard (ISO
  24444, COLIPA, FDA).
- `[STATS SUBSTRATE UNREPORTED]` if in vitro SPF is reported without the substrate (PMMA, Vitro-Skin)
  and roughness value.
- `[STATS REPLICATE COUNT LOW]` if n < 6 for in vitro SPF (ISO 24444 minimum).
- `[STATS INTER-INSTRUMENT VARIABILITY IGNORED]` if multiple instruments or labs are used without an
  inter-assay CV%.

**Microbiome:**
- `[STATS ALPHA DIVERSITY INCOMPLETE]` if only one alpha-diversity metric is reported (pair richness
  with evenness, e.g. Chao1 + Shannon).
- `[STATS RAREFACTION UNMENTIONED]` if sequencing-depth normalization is not addressed.
- `[STATS MULTIPLE TESTING MICROBIOME]` if differential abundance is tested without FDR correction
  (Benjamini-Hochberg minimum).

**Sensory and clinical evaluation:**
- `[STATS ORDINAL DATA PARAMETRIC]` if parametric tests are run on Likert or visual-analogue-scale data
  without justification.
- `[STATS BLINDING UNSTATED]` if clinical assessments are reported without stating whether evaluators
  were blinded.

**Scopus validation:** for each `[STATS ISO PROTOCOL UNSTATED]`, confirm the cited or recommended
standard exists with `scopus_api.py cite "<ISO standard DOI>"`; if confirmed, add the full
Scopus-validated reference as a `> Suggested citation:` line. Flag `[UNVERIFIED]` on network error.

## Use in `mine` mode

When the skill mines a corpus (scopus-researcher), the same profile drives what counts as a
statistical-improvement opportunity. For `engineering`, the opportunity list is built from the gaps the
profile flags reveal across papers, for example: "no paper reports variance over seeds", "all report
accuracy on imbalanced data", "no significance test on model-vs-model deltas", "no effect size on
benchmark gains". These feed scopus-researcher Step 9b (gap map), Step 9d (Pareto contribution
columns), and Step 10 (hypotheses).
