---
# This spec is INTENTIONALLY invalid — it demonstrates the ceiling clamp (T3).
# A shell grant escapes the egress allowlist (AC-2), so the server rejects it
# with 400 even though it arrived via a spec file — the guards run on the
# MERGED grant, not just request-supplied tools. Use it to confirm a bad spec
# can't slip a dangerous grant past the checks.
tools: [read_file, execute_shell_command]
provider: nvidia
model: qwen
---
You should never get to run — the shell grant is rejected up front.
