# ETL contract version 1

The audited snapshot is locked by `data/processed/daily_aqi_latest.lock.json`.
It binds the prepared daily CSV, its full source/quality manifest and compressed
hourly snapshot by SHA-256. `etl_contract.validate()` verifies those files and the
AQI, all four sub-index formulas, completeness, category, date bounds and
availability invariants before modelling. Failures raise explicit exceptions,
including when Python runs with optimization (`python -O`); validation does not
depend on removable `assert` statements.
The fixed source precedence, quarantine, units, timezone, coverage and no-target-
imputation rules remain in [extended_data.md](extended_data.md).

Locking freezes this reviewed data version and its definition; it does not claim
that provisional observations are finalized or that live data can never change.
A source refresh is explicit:

```bash
python extend_data.py --refresh
# Review coverage, conflicts, source changes and the new manifest first.
python etl_contract.py --lock
python workflow.py
python scripts/execute_notebook.py
```

The modelling workflow never rewrites the data. It rejects a changed snapshot or
mismatched report lock. Historical NAPS bytes must match their frozen source records;
changed archive versions require a separate review rather than silent substitution.
Changes to transformation rules require a reviewed contract-version change and new
snapshot. Routine observation updates require an explicit new snapshot lock and
report regeneration. Scheduled production refreshes stage new candidates under
the same contract and validate them without overwriting this frozen release lock;
see [operations](operations.md).
