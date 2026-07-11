---
name: vtable-fixer
description: "Deprecated: use the project-level fix-cppheaders SKILL"
model: sonnet
color: purple
---

This agent profile no longer repairs C++ headers. Invoke the project-level `fix-cppheaders` SKILL so it can run
`run_cpp_tests.py`, obtain fresh layout differences, edit only configured `hl2sdk_cs2` headers, and verify the result.
