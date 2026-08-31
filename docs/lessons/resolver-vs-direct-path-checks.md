# Calling a thing directly does not prove it is the thing that gets called

**Verifiable in 10 seconds:**

```bash
uv run python -c "from ppxai.engine.bootstrap import find_bootstrap_file, DEFAULT_BOOTSTRAP_FILES
from pathlib import Path
print(DEFAULT_BOOTSTRAP_FILES)          # ['AGENTS.md', 'CLAUDE.md', 'INSTRUCTIONS.md']
print(find_bootstrap_file(Path('.')))   # AGENTS.md  <- this repo HAS one
"
```

## The trap

`BootstrapContext.from_file(path)` parses whatever path you hand it.
`find_bootstrap_file(dir)` decides **which** path the app actually loads,
walking `DEFAULT_BOOTSTRAP_FILES` in order.

Handing the first function a path you chose yourself and reporting the
result as "verified" proves only that the file parses. It cannot tell you
whether that file is loaded, because you supplied the answer as the input.

This bit twice on 2026-08-30/31:

- An agent claimed "this repo has no `AGENTS.md`, so its `CLAUDE.md` is
  loaded as bootstrap context", having run
  `BootstrapContext.from_file(Path("CLAUDE.md"))` — a direct-path call.
  `git ls-files AGENTS.md` lists a tracked 49 KB file at the root. This
  repo loads **`AGENTS.md`**. The claim nearly became a rule in the
  governing doc.
- The same shape: `web_search_perplexity` built its own client and was
  described as "using the configured wire". It was hardcoded. The wire the
  resolver returns and the wire a function contacts are two different
  questions until one reads the other.

## The rule

When the question is *"which one does it pick?"*, **call the picker.**
`find_bootstrap_file`, `resolve_web_search_backend`,
`get_facts_for_model(...).wire_protocol` — these exist precisely because
selection is not obvious from the call site.

And "file X does not exist" is a claim needing `ls` or `git ls-files`, not
inference from not having seen it.

## Why this generalises

A resolver's whole purpose is that callers should not re-derive the choice.
That makes the resolver the only honest witness to what the choice *is* —
and makes any check that bypasses it a check of your own assumption.
