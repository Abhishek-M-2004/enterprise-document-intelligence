"""Qdrant client configuration, collection management, and vector operations."""

import time
from typing import Any, Dict, List, Optional, Tuple, Union
import uuid
from qdrant_client import AsyncQdrantClient, QdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    FilterSelector,
    MatchValue,
    PayloadSchemaType,
    PointStruct,
    VectorParams,
)

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


def get_qdrant_client() -> AsyncQdrantClient:
    """Create an asynchronous Qdrant client instance."""
    return AsyncQdrantClient(
        url=settings.QDRANT_URL,
        api_key=settings.QDRANT_API_KEY,
        prefer_grpc=settings.QDRANT_PREFER_GRPC,
        timeout=10.0,
        check_compatibility=False,
    )


def get_sync_qdrant_client() -> QdrantClient:
    """Create a synchronous Qdrant client instance for Celery background tasks."""
    return QdrantClient(
        url=settings.QDRANT_URL,
        api_key=settings.QDRANT_API_KEY,
        prefer_grpc=settings.QDRANT_PREFER_GRPC,
        timeout=10.0,
        check_compatibility=False,
    )


async def check_qdrant_connectivity() -> Tuple[bool, float, Optional[str]]:
    """Verify connectivity to Qdrant vector database."""
    start_time = time.perf_counter()
    client = None
    try:
        client = get_qdrant_client()
        await client.get_collections()
        latency = (time.perf_counter() - start_time) * 1000
        return True, round(latency, 2), None
    except Exception as exc:
        latency = (time.perf_counter() - start_time) * 1000
        return False, round(latency, 2), str(exc)
    finally:
        if client:
            await client.close()


class QdrantService:
    """High-level service managing collections and chunk vector storage."""

    @staticmethod
    def ensure_chunks_collection_sync(client: Optional[QdrantClient] = None) -> None:
        """Create the chunks collection with payload indexes synchronously if it doesn't exist."""
        own_client = False
        if client is None:
            client = get_sync_qdrant_client()
            own_client = True

        try:
            collection_name = settings.QDRANT_COLLECTION_CHUNKS
            collections = [c.name for c in client.get_collections().collections]

            if collection_name not in collections:
                logger.info(f"Creating Qdrant collection: {collection_name}")
                client.create_collection(
                    collection_name=collection_name,
                    vectors_config=VectorParams(
                        size=settings.EMBEDDING_DIMENSION,
                        distance=Distance.COSINE,
                    ),
                )
                # Create keyword indexes for fast multi-tenant filtering
                client.create_payload_index(
                    collection_name=collection_name,
                    field_name="tenant_id",
                    field_schema=PayloadSchemaType.KEYWORD,
                )
                client.create_payload_index(
                    collection_name=collection_name,
                    field_name="document_id",
                    field_schema=PayloadSchemaType.KEYWORD,
                )
                logger.info(f"Created collection and payload indexes for: {collection_name}")
        finally:
            if own_client:
                client.close()

    @staticmethod
    async def ensure_chunks_collection_async(client: Optional[AsyncQdrantClient] = None) -> None:
        """Create the chunks collection with payload indexes asynchronously if it doesn't exist."""
        own_client = False
        if client is None:
            client = get_qdrant_client()
            own_client = True

        try:
            collection_name = settings.QDRANT_COLLECTION_CHUNKS
            resp = await client.get_collections()
            collections = [c.name for c in resp.collections]

            if collection_name not in collections:
                logger.info(f"Creating Qdrant collection (async): {collection_name}")
                await client.create_collection(
                    collection_name=collection_name,
                    vectors_config=VectorParams(
                        size=settings.EMBEDDING_DIMENSION,
                        distance=Distance.COSINE,
                    ),
                )
                await client.create_payload_index(
                    collection_name=collection_name,
                    field_name="tenant_id",
                    field_schema=PayloadSchemaType.KEYWORD,
                )
                await client.create_payload_index(
                    collection_name=collection_name,
                    field_name="document_id",
                    field_schema=PayloadSchemaType.KEYWORD,
                )
        finally:
            if own_client:
                await client.close()

    @staticmethod
    def upsert_chunks_sync(
        points: List[PointStruct],
        client: Optional[QdrantClient] = None,
    ) -> None:
        """Upsert chunk vector points synchronously."""
        if not points:
            return

        own_client = False
        if client is None:
            client = get_sync_qdrant_client()
            own_client = True

        try:
            QdrantService.ensure_chunks_collection_sync(client)
            client.upsert(
                collection_name=settings.QDRANT_COLLECTION_CHUNKS,
                points=points,
                wait=True,
            )
            logger.info(f"Successfully upserted {len(points)} vector points to Qdrant.")
        finally:
            if own_client:
                client.close()

    @staticmethod
    async def upsert_chunks_async(
        points: List[PointStruct],
        client: Optional[AsyncQdrantClient] = None,
    ) -> None:
        """Upsert chunk vector points asynchronously."""
        if not points:
            return

        own_client = False
        if client is None:
            client = get_qdrant_client()
            own_client = True

        try:
            await QdrantService.ensure_chunks_collection_async(client)
            await client.upsert(
                collection_name=settings.QDRANT_COLLECTION_CHUNKS,
                points=points,
                wait=True,
            )
        finally:
            if own_client:
                await client.close()

    @staticmethod
    def delete_chunks_by_document_sync(
        tenant_id: uuid.UUID,
        document_id: uuid.UUID,
        client: Optional[QdrantClient] = None,
    ) -> None:
        """Delete all vector points belonging to a specific document under a tenant synchronously."""
        own_client = False
        if client is None:
            client = get_sync_qdrant_client()
            own_client = True

        try:
            collection_name = settings.QDRANT_COLLECTION_CHUNKS
            doc_filter = Filter(
                must=[
                    FieldCondition(
                        key="tenant_id",
                        match=MatchValue(value=str(tenant_id)),
                    ),
                    FieldCondition(
                        key="document_id",
                        match=MatchValue(value=str(document_id)),
                    ),
                ]
            )
            client.delete(
                collection_name=collection_name,
                points_selector=FilterSelector(filter=doc_filter),
                wait=True,
            )
            logger.info(
                f"Deleted Qdrant vector chunks for document {document_id} (tenant {tenant_id})"
            )
        except Exception as e:
            logger.warning(f"Error deleting Qdrant vector chunks: {e}")
        finally:
            if own_client:
                client.close()

    @staticmethod
    async def delete_chunks_by_document_async(
        tenant_id: uuid.UUID,
        document_id: uuid.UUID,
        client: Optional[AsyncQdrantClient] = None,
    ) -> None:
        """Delete all vector points belonging to a specific document under a tenant asynchronously."""
        own_client = False
        if client is None:
            client = get_qdrant_client()
            own_client = True

        try:
            collection_name = settings.QDRANT_COLLECTION_CHUNKS
            doc_filter = Filter(
                must=[
                    FieldCondition(
                        key="tenant_id",
                        match=MatchValue(value=str(tenant_id)),
                    ),
                    FieldCondition(
                        key="document_id",
                        match=MatchValue(value=str(document_id)),
                    ),
                ]
            )
            await client.delete(
                collection_name=collection_name,
                points_selector=FilterSelector(filter=doc_filter),
                wait=True,
            )
        except Exception as e:
            logger.warning(f"Error deleting Qdrant vector chunks (async): {e}")
        finally:
            if own_client:
                await client.close()

    @staticmethod
    async def search_chunks_async(
        tenant_id: uuid.UUID,
        query_vector: List[float],
        top_k: int = 20,
        document_ids: Optional[List[uuid.UUID]] = None,
        client: Optional[AsyncQdrantClient] = None,
    ) -> List[Dict[str, Any]]:
        """Perform semantic vector retrieval strictly isolated to the specified tenant."""
        if not tenant_id:
            raise ValueError("tenant_id is strictly required for vector search.")

        own_client = False
        if client is None:
            client = get_qdrant_client()
            own_client = True

        try:
            # Construct mandatory server-side tenant filter
            must_conditions = [
                FieldCondition(
                    key="tenant_id",
                    match=MatchValue(value=str(tenant_id)),
                )
            ]

            # Optional document ID filtering
            if document_ids:
                doc_conditions = [
                    FieldCondition(
                        key="document_id",
                        match=MatchValue(value=str(doc_id)),
                    )
                    for doc_id in document_ids
                ]
                must_conditions.append(Filter(should=doc_conditions))

            query_filter = Filter(must=must_conditions)

            # Query Qdrant vector collection
            resp = await client.query_points(
                collection_name=settings.QDRANT_COLLECTION_CHUNKS,
                query=query_vector,
                query_filter=query_filter,
                limit=top_k,
                with_payload=True,
            )

            results: List[Dict[str, Any]] = []
            for point in resp.points:
                payload = point.payload or {}
                # Cryptographic check: verify payload tenant matches
                if payload.get("tenant_id") != str(tenant_id):
                    logger.critical(
                        f"CRITICAL: Qdrant returned chunk {point.id} with mismatched tenant {payload.get('tenant_id')}!"
                    )
                    continue

                metadata = payload.get("metadata") or {}
                results.append({
                    "chunk_id": uuid.UUID(str(point.id)),
                    "document_id": uuid.UUID(str(payload.get("document_id"))),
                    "filename": metadata.get("filename") or "document.pdf",
                    "chunk_index": payload.get("chunk_index", 0),
                    "page_number": payload.get("page_number"),
                    "content": payload.get("content", ""),
                    "score": float(point.score),
                    "metadata": metadata,
                })
            return results
        finally:
            if own_client:
                await client.close()

    @staticmethod
    def search_chunks_sync(
        tenant_id: uuid.UUID,
        query_vector: List[float],
        top_k: int = 20,
        document_ids: Optional[List[uuid.UUID]] = None,
        client: Optional[QdrantClient] = None,
    ) -> List[Dict[str, Any]]:
        """Perform semantic vector retrieval strictly isolated to the specified tenant synchronously."""
        if not tenant_id:
            raise ValueError("tenant_id is strictly required for vector search.")

        own_client = False
        if client is None:
            client = get_sync_qdrant_client()
            own_client = True

        try:
            must_conditions = [
                FieldCondition(
                    key="tenant_id",
                    match=MatchValue(value=str(tenant_id)),
                )
            ]

            if document_ids:
                doc_conditions = [
                    FieldCondition(
                        key="document_id",
                        match=MatchValue(value=str(doc_id)),
                    )
                    for doc_id in document_ids
                ]
                must_conditions.append(Filter(should=doc_conditions))

            query_filter = Filter(must=must_conditions)

            resp = client.query_points(
                collection_name=settings.QDRANT_COLLECTION_CHUNKS,
                query=query_vector,
                query_filter=query_filter,
                limit=top_k,
                with_payload=True,
            )

            results: List[Dict[str, Any]] = []
            for point in resp.points:
                payload = point.payload or {}
                if payload.get("tenant_id") != str(tenant_id):
                    logger.critical(
                        f"CRITICAL: Qdrant returned chunk {point.id} with mismatched tenant {payload.get('tenant_id')}!"
                    )
                    continue

                metadata = payload.get("metadata") or {}
                results.append({
                    "chunk_id": uuid.UUID(str(point.id)),
                    "document_id": uuid.UUID(str(payload.get("document_id"))),
                    "filename": metadata.get("filename") or "document.pdf",
                    "chunk_index": payload.get("chunk_index", 0),
                    "page_number": payload.get("page_number"),
                    "content": payload.get("content", ""),
                    "score": float(point.score),
                    "metadata": metadata,
                })
            return results
        finally:
            if own_client:
                client.close()
