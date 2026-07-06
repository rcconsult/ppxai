---
tools: [read_file]
provider: nvidia
model: qwen
---
This skill INTENTIONALLY ships a scripts/ directory. In the in-process tier a
/task run has no shell grant, so scripts/ can never execute — the server refuses
this skill up front (400) unless the operator sets
`tools.agent.sandbox.allow_skill_scripts: true` to acknowledge the scripts stay
inert. Use it to confirm the scripts-gate works.
