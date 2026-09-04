"""The admin panel's side of the claim policy.

One job: turn the thresholds in `claim_agent.policy` into something a screen can
draw a form from, and turn what comes back off that form into a policy the
service will judge claims by (FR-0.7, NFR-7).

Nothing in here judges a claim, and nothing in here decides what a threshold
should be. It describes the values that exist and checks the ones submitted.
"""
