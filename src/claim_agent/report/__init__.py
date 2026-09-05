"""Layer 2 — the report a representative decides from, and the three things they may do to it.

Everything before this stage establishes facts. This stage hands them to a person: it writes what
an investigation found into a report, keeps it so it can be fetched back, and records what the
representative then decided (FR-2.1 to FR-2.10, FR-C.1).

**The report is structured data.** The AI answers in fixed fields and those fields are what a
report holds, so a screen lays them out rather than reading wording back into data (FR-2.10).

**A report can go round again.** A representative who finds a fault sends it back in their own
words, the same agent reworks it, and the result is filed as the next version with the whole
conversation attached (FR-R.1 to FR-R.13). The reworking itself lives in `claim_agent.agent`,
because it is the investigation's agent doing the investigation's job with one more input; this
package turns what it produced into the next version of a report.

**Nothing here decides anything and nothing here sends anything.** A report is a proposal, an
approval is a record that a person accepted one, and the stage that would act on that acceptance
lives in `claim_agent.execution` and does not exist yet (FR-3.1).

**Why this is its own package rather than part of `domain`.** Writing a report means reading what
the quick checks established and what the investigation concluded, so the writer and the builder
have to sit above both of those packages. The report itself has no such need — it borrows only
from `domain` — but splitting one feature across two packages to make that point would cost more
than it explains.
"""
