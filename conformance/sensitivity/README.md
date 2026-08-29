# Sensitivity Propagation Vectors

Language-neutral fixtures for the publish-time check in Form IR §10 and
encryption envelope §5.2: **a field that reads a sensitive field must itself be
sensitive**, or the derived value discloses the input that `field_level`
encryption exists to protect.

Both implementations must produce the same violations, in the same order:

- Python: `check_sensitivity_propagation` in `backend/app/modules/crypto/envelope.py`,
  runner `backend/tests/test_sensitivity_conformance.py`
- Kotlin: `checkSensitivityPropagation` in `shared/form-engine` (`Sensitivity.kt`),
  runner `shared/form-engine/src/jvmTest/kotlin/com/dcp/form/SensitivityConformanceTest.kt`

A form that publishes on one and is refused on the other is a release blocker,
not a platform difference — a form author would meet a refusal that their
builder told them was not there.

## Written, not generated

Unlike `conformance/crypto`, these expectations are written by hand rather than
generated from the Python reference. There are no bytes to reproduce here, only
a rule; blessing one implementation's output would make the vectors agree with
whatever that implementation currently does, including its mistakes. Both sides
are checked against the rule as stated.

`expectedViolations` is the exact message list, in order: by field in document
order, then by source field id. Message text is part of the contract because a
form author reads it.
