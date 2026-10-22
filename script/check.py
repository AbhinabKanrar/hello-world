"""One paid structured-output request, followed by a local cache lookup."""

from __future__ import annotations

import asyncio

from society.config import Settings
from society.llm.factory import create_client
from society.sim.schemas import Reaction


async def main() -> None:
    settings = Settings()
    if settings.provider != "openrouter":
        raise SystemExit("Set SOCIETY_PROVIDER=openrouter first.")

    client = create_client(settings)
    try:
        system = "Return JSON only, matching the supplied schema."
        user = (
            "A cautious parent considers a dinner-planning app costing $15/month. "
            "Give interest, purchase_intent, max_price, top_objection, would_share, "
            "share_message, stance, and reasoning. Use an empty share_message "
            "when would_share is false."
        )

        first = await client.complete_json(
            system=system,
            user=user,
            schema=Reaction,
            temperature=0.7,
            seed=42,
        )
        hits_before = client.usage.cache_hits

        second = await client.complete_json(
            system=system,
            user=user,
            schema=Reaction,
            temperature=0.7,
            seed=42,
        )

        if first != second or client.usage.cache_hits != hits_before + 1:
            raise RuntimeError("Cache smoke check failed.")

        print(first.model_dump_json(indent=2))
        print(
            f"requests={client.usage.requests}, "
            f"cache_hits={client.usage.cache_hits}, "
            f"input_tokens={client.usage.prompt_tokens}, "
            f"output_tokens={client.usage.completion_tokens}"
        )
    finally:
        await client.aclose()


if __name__ == "__main__":
    asyncio.run(main())