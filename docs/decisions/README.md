# Architecture Decision Records (ADRs)

Short, dated records of architecture decisions where the chosen
option is non-obvious or where we deliberately deferred a "proper"
solution. Each record names:

- **Context** — what problem are we solving, what constraints apply
- **Decision** — what we chose
- **Why this and not the alternatives** — the trade-off we accepted
- **Future / proper solution** — what we'd do if/when constraints change
- **Triggers to revisit** — concrete signals that should prompt a re-evaluation

Format: `NNNN-short-slug.md`, lowercase, kebab-case. Numbering is
strictly sequential — never re-number, never re-use.

Records are immutable **once Accepted**. An Accepted record captures
*what we knew when we decided*; to change an Accepted decision, write a
new record that supersedes the old one and add a "Superseded by:"
header to the old record. Don't delete or rewrite the history of an
Accepted decision.

While a record is **Status: Proposed** (or otherwise not yet Accepted)
it is a living draft and **may be revised in place** as the design is
refined — note the revision in the `Date:` line (e.g.
`2026-05-03 (revised 2026-06-15 — MVP design resolved)`). Immutability
binds at acceptance, not at first write: a Proposed ADR hasn't decided
anything yet, so in-place iteration is how a design converges before it
is locked. (This matches established practice — e.g. ADR 0003 and ADR
0006 were both revised in place while not-yet-final.)
