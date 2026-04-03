"""ChromaDB vector store wrapper for the Nertia RAG layer."""

from pathlib import Path
import chromadb

_PERSIST_DIR = str(Path(__file__).parent.parent.parent / "data" / "chromadb")
_client = None
_collection = None


def get_client() -> chromadb.ClientAPI:
    global _client
    if _client is None:
        _client = chromadb.PersistentClient(path=_PERSIST_DIR)
    return _client


def get_collection(name: str = "knowledge") -> chromadb.Collection:
    global _collection
    if _collection is None:
        client = get_client()
        _collection = client.get_or_create_collection(
            name=name,
            metadata={"hnsw:space": "cosine"},
        )
    return _collection


def upsert_documents(
    ids: list[str],
    documents: list[str],
    metadatas: list[dict] | None = None,
):
    """Upsert documents into the knowledge collection."""
    col = get_collection()
    col.upsert(ids=ids, documents=documents, metadatas=metadatas)


def query(query_text: str, n_results: int = 5, where: dict | None = None) -> dict:
    """Query the knowledge collection by text similarity."""
    col = get_collection()
    kwargs = {"query_texts": [query_text], "n_results": n_results}
    if where:
        kwargs["where"] = where
    return col.query(**kwargs)


def count() -> int:
    return get_collection().count()
