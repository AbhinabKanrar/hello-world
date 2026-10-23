import asyncio

import numpy as np

from society.config import Settings
from society.llm.factory import create_client


async def main() -> None:
    settings = Settings()
    if settings.provider != "openrouter":
        raise SystemExit("Set SOCIETY_PROVIDER=openrouter.")

    client = create_client(settings)
    try:
        texts = [
            "A working parent wants to reduce dinner preparation time.",
            "A household wants more affordable weekly meals.",
        ]
        first = await client.embed(texts)
        second = await client.embed(texts)

        if first.shape[0] != len(texts) or first.shape[1] == 0:
            raise RuntimeError("Unexpected embedding shape.")
        if not np.isfinite(first).all():
            raise RuntimeError("Non-finite embeddings.")
        if not np.array_equal(first, second):
            raise RuntimeError("Cached embeddings differ.")

        print(f"Embedding smoke check passed: shape={first.shape}")
    finally:
        await client.aclose()


if __name__ == "__main__":
    asyncio.run(main())