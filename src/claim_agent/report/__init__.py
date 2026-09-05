"""Layer 2 — the report a representative decides from, and the two things they may do to it.

Everything before this stage establishes facts. This stage hands them to a person: it writes what
an investigation found into a report, keeps it so it can be fetched back, and records what the
representative then decided (FR-2.1 to FR-2.10, FR-C.1).

**The report is a written document.** The AI already answers in fixed fields, and a plain function
turns those into the words a representative reads. That is a deliberate choice with a cost — the
requirement asking for structured data rather than prose is knowingly not met — and it is written
up in DESIGN.md rather than left for a reader to notice.

**Nothing here decides anything and nothing here sends anything.** A report is a proposal, an
approval is a record that a person accepted one, and the stage that would act on that acceptance
lives in `claim_agent.execution` and does not exist yet (FR-3.1).

**Why this is its own package rather than part of `domain`.** Writing a report means reading what
the quick checks established and what the investigation concluded, so the writer and the builder
have to sit above both of those packages. The report itself has no such need — it borrows only
from `domain` — but splitting one feature across two packages to make that point would cost more
than it explains.
"""
