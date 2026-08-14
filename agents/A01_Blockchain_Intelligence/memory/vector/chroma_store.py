"""
Chroma Store

Chroma-compatible vector store adapter. When the optional ``chromadb``
package is available it can wrap a real Chroma collection; otherwise a
pure-Python in-memory fallback (``_InMemoryVectorStore``) provides the
same upsert / query / namespace contract so nothing depends on third
parties for local development and tests.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

from memory.vector.embeddings import LocalHashEmbedder
from memory.vector.similarity import cosine_similarity

try:  # pragma: no cover - exercised only when chromadb is installed
    import chromadb  # type: ignore

    _HAS_CHROMADB = True
except Exception:
    _HAS_CHROMADB = False


@dataclass(slots=True)
class ChromaDocument:
    """
    A single stored document with its embedding and metadata.
    """

    id: str
    text: str
    vector: list[float]
    metadata: dict[str, Any] = field(default_factory=dict)
    namespace: str = "default"
    collection: str = "default"


class VectorStoreError(Exception):
    pass


class VectorStoreNotFoundError(VectorStoreError):
    pass


class _InMemoryVectorStore:
    """
    Zero-dependency in-memory vector store mirroring Chroma's core API.
    """

    def __init__(self) -> None:
        self._documents: dict[str, ChromaDocument] = {}
        self._collections: set[str] = set()

    def upsert(
        self,
        ids: Iterable[str],
        documents: Iterable[str],
        embeddings: Iterable[list[float]],
        metadatas: Iterable[dict[str, Any]],
        *,
        collection: str = "default",
        namespace: str = "default",
    ) -> None:
        self._collections.add(collection)
        for doc_id, text, vector, metadata in zip(
            ids, documents, embeddings, metadatas
        ):
            self._documents[doc_id] = ChromaDocument(
                id=doc_id,
                text=text,
                vector=vector,
                metadata=dict(metadata),
                namespace=namespace,
                collection=collection,
            )

    def query(
        self,
        query_embedding: list[float],
        *,
        n_results: int = 10,
        collection: str = "default",
        namespace: str = "default",
        where: dict[str, Any] | None = None,
    ) -> list[tuple[str, float, str]]:
        scored: list[tuple[float, str, str]] = []
        for doc in self._documents.values():
            if doc.collection != collection:
                continue
            if doc.namespace != namespace:
                continue
            if where and not _matches_where(doc.metadata, where):
                continue
            score = cosine_similarity(query_embedding, doc.vector)
            scored.append((score, doc.id, doc.text))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [(doc_id, score, text) for score, doc_id, text in scored[:n_results]]

    def get(
        self,
        doc_id: str,
    ) -> ChromaDocument | None:
        return self._documents.get(doc_id)

    def delete(self, doc_id: str) -> bool:
        return self._documents.pop(doc_id, None) is not None

    def count(self) -> int:
        return len(self._documents)

    def list_collections(self) -> list[str]:
        return sorted(self._collections)

    def clear(self) -> None:
        self._documents.clear()
        self._collections.clear()


def _matches_where(metadata: dict[str, Any], where: dict[str, Any]) -> bool:
    for key, value in where.items():
        if metadata.get(key) != value:
            return False
    return True


class ChromaStore:
    """
    Vector store adapter for Chroma-compatible storage.

    Responsibilities:
        * Upsert documents with embeddings and metadata
        * Query by embedding similarity with filtering
        * Manage namespaces and collections
        * Fall back to an in-memory store when chromadb is absent
    """

    def __init__(
        self,
        *,
        embedder: Any | None = None,
        client: Any | None = None,
        collection_name: str = "memory",
    ) -> None:
        self._embedder = embedder or LocalHashEmbedder()
        self._client = client
        self._collection_name = collection_name
        self._memory = _InMemoryVectorStore()
        self._chroma_collection: Any | None = None
        if _HAS_CHROMADB and client is not None:
            self._chroma_collection = client.get_or_create_collection(
                collection_name,
                metadata={"hnsw:space": "cosine"},
            )

    @property
    def embedder(self) -> Any:
        return self._embedder

    @property
    def collection_name(self) -> str:
        return self._collection_name

    @property
    def available(self) -> bool:
        return self._chroma_collection is not None

    def upsert(
        self,
        ids: list[str],
        documents: list[str],
        *,
        metadatas: list[dict[str, Any]] | None = None,
        embeddings: list[list[float]] | None = None,
        collection: str | None = None,
        namespace: str = "default",
    ) -> None:
        vectors = embeddings or [
            self._embedder.embed(text) for text in documents
        ]
        metas = metadatas or [{} for _ in documents]
        if self._chroma_collection is not None:
            col_metas = [dict(m) | {"namespace": namespace} for m in metas]
            self._chroma_collection.upsert(
                ids=ids,
                documents=documents,
                embeddings=vectors,
                metadatas=col_metas,
            )
            return
        self._memory.upsert(
            ids,
            documents,
            vectors,
            metas,
            collection=collection or self._collection_name,
            namespace=namespace,
        )

    def query(
        self,
        query_text: str,
        *,
        n_results: int = 10,
        collection: str | None = None,
        namespace: str = "default",
        where: dict[str, Any] | None = None,
    ) -> list[tuple[str, float, str]]:
        query_vec = self._embedder.embed(query_text)
        if self._chroma_collection is not None:
            qwhere: dict[str, Any] = {"namespace": namespace}
            if where:
                qwhere.update(where)
            result = self._chroma_collection.query(
                query_embeddings=[query_vec],
                n_results=n_results,
                where=qwhere,
            )
            ids = result.get("ids", [[]])[0]
            distances = result.get("distances", [[]])[0]
            documents = result.get("documents", [[]])[0]
            scores = [max(0.0, 1.0 - d) for d in distances]
            return list(zip(ids, scores, documents))
        return self._memory.query(
            query_vec,
            n_results=n_results,
            collection=collection or self._collection_name,
            namespace=namespace,
            where=where,
        )

    def get(self, doc_id: str) -> ChromaDocument | None:
        if self._chroma_collection is not None:
            result = self._chroma_collection.get(ids=[doc_id])
            if not result.get("ids"):
                return None
            metadata = (result.get("metadatas") or [{}])[0]
            return ChromaDocument(
                id=doc_id,
                text=(result.get("documents") or [""])[0],
                vector=(result.get("embeddings") or [[0.0]])[0],
                metadata=metadata,
                collection=metadata.get("collection"),
            )
        return self._memory.get(doc_id)

    def delete(self, doc_id: str) -> bool:
        if self._chroma_collection is not None:
            self._chroma_collection.delete(ids=[doc_id])
            return True
        return self._memory.delete(doc_id)

    def count(self) -> int:
        if self._chroma_collection is not None:
            return int(self._chroma_collection.count())
        return self._memory.count()

    def list_collections(self) -> list[str]:
        if self._chroma_collection is not None:
            return [self._collection_name]
        return self._memory.list_collections()

    def clear(self) -> None:
        if self._chroma_collection is not None:
            self._chroma_collection.delete(where={})
            return
        self._memory.clear()
