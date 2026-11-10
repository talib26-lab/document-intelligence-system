"""Semantic (meaning-based) search endpoint.

Documents are embedded lazily: any extracted document without an embedding is
embedded at search time and stored, so later searches are instant.
"""

from fastapi import APIRouter, HTTPException, Query

from backend.app.db import embedding_repository
from backend.app.services import semantic

router = APIRouter()


@router.get("/search/semantic")
def semantic_search(q: str = Query(..., min_length=1), limit: int = Query(10, ge=1, le=50)):
    try:
        missing = embedding_repository.documents_missing_embedding()
        if missing:
            vectors = semantic.embed_texts([text for _, text in missing])
            for (doc_id, _), vector in zip(missing, vectors):
                embedding_repository.save_embedding(doc_id, vector)

        query_vector = semantic.embed_texts([q])[0]
        stored = embedding_repository.get_all_embeddings()
    except semantic.EmbeddingError as exc:
        raise HTTPException(status_code=503, detail=f"Semantic search unavailable: {exc}")

    ranked = semantic.rank_by_similarity(query_vector, stored, limit=limit)
    return {
        "query": q,
        "results": [{"document_id": doc_id, "score": round(score, 4)} for doc_id, score in ranked],
    }