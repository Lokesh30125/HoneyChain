"""Blockchain traceability: the client, the event vocabulary and the outbox service.

Imported by the workflow services that record supply-chain events and by the
routes that read them back::

    from app.services.blockchain import BlockchainService

Nothing outside this package talks to the blockchain service directly.
"""

from app.services.blockchain.client import (
    BlockchainClient,
    BlockchainError,
    BlockchainMisconfigured,
    BlockchainRejected,
    BlockchainUnavailable,
    Transaction,
    blockchain_client,
)
from app.services.blockchain.service import BlockchainService

__all__ = [
    "BlockchainClient",
    "BlockchainError",
    "BlockchainMisconfigured",
    "BlockchainRejected",
    "BlockchainService",
    "BlockchainUnavailable",
    "Transaction",
    "blockchain_client",
]
