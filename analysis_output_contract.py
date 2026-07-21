"""Version the generated symbol-output semantics independently from runtime plumbing."""

# Bump only when analyzer changes can alter generated YAML, dependency interpretation,
# or the set of executed analysis nodes. Runtime reliability fixes keep this unchanged.
ANALYSIS_OUTPUT_CONTRACT_VERSION = 1
ANALYSIS_OUTPUT_CONTRACT_MISMATCH_REASON = "analysis_output_contract_mismatch"
