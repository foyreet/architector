"""Shared byte budgets for tabular data and the isolated Python protocol."""
MIB = 1024 * 1024
JSON_DATA_BYTES = 16 * MIB
PYTHON_MESSAGE_BYTES = 32 * MIB
# Leave room for the artifact envelope and for both inputs/outputs in a step.
ARTIFACT_BYTES = 32 * MIB
STEP_RECORD_BYTES = 64 * MIB

