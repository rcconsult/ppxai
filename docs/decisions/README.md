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

Records are immutable once written. To change a decision, write a
new record that supersedes the old one and add a "Superseded by:"
header to the old record. Don't delete or rewrite history — the
decisions log is a record of *what we knew when we decided*, not
the current state of the world.
