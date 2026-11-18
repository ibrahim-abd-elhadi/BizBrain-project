"""Proposals and their approval flow (feature 004).

The public entry point is `create_proposal` (contracts/create-proposal.md): the Risk and insights
action uses it, and feature 005's `propose_purchase_order` tool will call it. It only creates a
proposal awaiting approval; it never contacts the ERP or an LLM.
"""

from brain.proposals.service import ProposalRefused, create_proposal

__all__ = ["ProposalRefused", "create_proposal"]
