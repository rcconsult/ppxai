# CI triage checklist

This file is mounted into the run's read-scope by `--skill ci-triage`. The
agent can read it; it cannot read files outside the skill directory (unless the
operator configured a wider read-scope).

1. **Identify the failing step.** Grep the job log for the first `error`,
   `FAILED`, `Traceback`, or non-zero exit marker — the *first* failure, not
   downstream noise.
2. **Classify.** Is it a test failure, a build/compile error, a dependency
   resolution error, a timeout, or an infra/runner error?
3. **Localize.** For a test failure, find the test name + the asserted vs actual
   values. For a build error, find the file:line the compiler names.
4. **Correlate with source.** Read the named file around that line to confirm the
   cause (don't guess from the log alone).
5. **Report.** One paragraph: what failed, why, and the single file:line most
   worth opening. Note anything you could not confirm from the read-scope.
