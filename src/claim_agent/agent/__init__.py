"""Layers 1a, 1b and R — the LangGraph agent (FR-1.*, FR-1a.*, FR-1b.*, FR-R.*).

Read and reasoning tools only. Sending email and submitting reimbursements are
absent from this package's tool surface by construction, not by instruction
(FR-1.2) — they live in `claim_agent.execution`, behind rep approval.
"""
