ACCEPTED_OUTPUT_BRANCHES = (
    "gamesymbols/build/14168/29683665467-1",
    "gamesymbols/build/14168b/1-2",
)

REJECTED_OUTPUT_BRANCHES = (
    "gamesymbols/14168/build-29683665467-1",
    "gamesymbols/14168",
    "gamesymbols/build",
    "gamesymbols/build/14168",
    "gamesymbols/build/14168/build-29683665467-1",
    "gamesymbols/build/14168/29683665467",
    "gamesymbols/build/not-a-version/29683665467-1",
    "gamesymbols/build/14168/29683665467-1/extra",
)

CANONICAL_OUTPUT_BRANCH = ACCEPTED_OUTPUT_BRANCHES[0]
LEGACY_OUTPUT_BRANCH = REJECTED_OUTPUT_BRANCHES[0]
