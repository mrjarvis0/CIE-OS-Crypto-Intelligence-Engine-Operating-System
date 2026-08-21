"""
CIE-OS
A01 Blockchain Intelligence Agent

Package:
    blockchain.security

On-chain security screening: measurements over captured chain data that a
higher layer turns into conclusions.

What is built
-------------
``exploit_detection``
    DET-EXPLOIT-02, anomalous outflow. Mechanism-agnostic; needs no bytecode
    analysis, which is why it is buildable today.
``approval_risk``
    ERC-20 / ERC-721 approval exposure, from decoded Approval and
    ApprovalForAll logs.

What is not, and why
--------------------
``contract_security``, ``rug_detection``, ``anomaly_detection`` and
``rpc_security`` remain empty. Each needs contract bytecode analysis, which
A01 does not have: ``contracts/`` decodes logs from their shape, and reading
what a contract *can* do requires disassembly and an ABI source neither of
which is ingested. A module that cannot do what its name claims is worse than
an absence, so they stay absent and say so.

Boundary
--------
Nothing in this package imports ``intelligence`` or ``decision``. These are
measurements: they report a number and the reasons it is or is not
trustworthy. Turning a number into a claim, at a confidence, under a maturity
ceiling, is the intelligence layer's job.
"""

__all__: list[str] = []
