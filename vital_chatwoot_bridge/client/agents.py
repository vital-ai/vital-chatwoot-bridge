"""
Agents mixin for the Chatwoot Bridge client.
"""

from vital_chatwoot_bridge.client.models import SingleResponse


class AgentsMixin:
    """Methods for /api/v1/chatwoot/agents endpoints."""

    async def list_agents(self) -> SingleResponse:
        """List all agents."""
        data = await self.get("/api/v1/chatwoot/agents")
        return SingleResponse(**data)
