"""Semantic (meaning-based) search helpers.

Text is turned into a list of numbers (an embedding). Texts with similar meaning
have similar embeddings, so we can rank documents by closeness to the query.
The real Gemini call is isolated in embed_texts(), so tests can use a fake one.
"""

import math
import os

from dotenv import load_dotenv

load_dotenv()

EMBEDDING_MODEL = "gemini-embedding-001"  # pinned so results are reproducible
MAX_CHARS = 8000  # cut very long documents before embedding


class EmbeddingError(Exception):
    """Raised when embeddings could not be created."""


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Ask Gemini for one embedding per text (the only network call in this module)."""
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise EmbeddingError("GEMINI_API_KEY is missing. Check your .env file.")
    try:
        from google import genai

        client = genai.Client(api_key=api_key)
        result = client.models.embed_content(
            model=EMBEDDING_MODEL,
            contents=[t[:MAX_CHARS] for t in texts],
        )
        return [list(e.values) for e in result.embeddings]
    except Exception as error:  # network, quota, invalid reply
        raise EmbeddingError(f"Embedding failed: {error}") from error


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """1.0 = same direction (very similar meaning), 0.0 = unrelated."""
    if len(a) != len(b) or not a:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def rank_by_similarity(
    query_vector: list[float],
    items: list[tuple[int, list[float]]],
    limit: int = 10,
    min_score: float = 0.0,
) -> list[tuple[int, float]]:
    """items = (document_id, vector). Returns [(document_id, score)] best first."""
    scored = [(doc_id, cosine_similarity(query_vector, vec)) for doc_id, vec in items]
    scored = [pair for pair in scored if pair[1] >= min_score]
    scored.sort(key=lambda pair: pair[1], reverse=True)
    return scored[:limit]