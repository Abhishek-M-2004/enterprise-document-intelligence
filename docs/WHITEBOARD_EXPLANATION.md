# Whiteboard Explanation Guide: Multi-Tenant Enterprise Document Intelligence Platform

This guide prepares you to deliver crisp, confident explanations of the system architecture on a whiteboard, in virtual interviews, or during executive architectural reviews. It is organized into 60-second, 2-minute, and 5-minute explanations, followed by a whiteboard diagram layout.

---

## 1. The 60-Second Architecture Pitch

> "I built a Multi-Tenant Enterprise Document Intelligence Platform that lets organizations ingest sensitive PDFs and query them using an advanced, hallucination-resistant RAG pipeline.
> 
> The core problem in enterprise RAG is that pure vector search frequently misses exact keyword terms like part numbers or financial figures, while bi-encoder embeddings struggle with fine-grained relevance ordering.
> 
> To solve this, I designed a multi-stage retrieval architecture: When a query arrives, it runs in parallel across dense vector search in Qdrant using BGE embeddings and sparse lexical search using BM25. We fuse those candidate lists using Reciprocal Rank Fusion ($k=60$) to eliminate score calibration issues, and pass the top 15 candidates to a BGE Cross-Encoder reranker. The cross-encoder performs joint self-attention to select the top 5 most relevant chunks.
> 
> Answers are generated via LLM with Server-Sent Events streaming, and every citation tag like `[S1]` is strictly validated server-side against actual retrieved chunks before rendering.
> 
> For security, we enforce PostgreSQL Row-Level Security with a non-superuser role and Qdrant payload filters, ensuring zero cross-tenant data leakage. The entire platform is backed by 95 passing automated tests and Dockerized for production."

---

## 2. The 2-Minute Project Pitch

> "This platform is an enterprise-grade document intelligence SaaS designed for multi-tenant organizations that need to search and chat with confidential PDF documents with zero data leakage and high precision.
> 
> The architecture addresses three fundamental engineering challenges:
> 
> **First, Retrieval Precision and Recall.** Standard vector search often fails on domain-specific terminology or exact identifiers. We built a hybrid retrieval engine: A 384-dimensional dense vector search via Qdrant handles semantic intent, while in-memory BM25Okapi handles lexical matching. Because dense cosine similarities and BM25 scores have incompatible scales, we combine them using Reciprocal Rank Fusion with a smoothing constant of 60. Then, a two-stage pipeline feeds the top 15 candidates to a `BAAI/bge-reranker-base` cross-encoder. Unlike bi-encoders that encode queries and documents independently, the cross-encoder computes full cross-attention over all query-document token pairs, yielding superior semantic ranking in ~1.1 seconds on CPU.
> 
> **Second, Hallucination Prevention & Citation Grounding.** Rather than trusting the LLM to report where it found information, our server injects standardized bracketed identifiers like `[SOURCE: S1]` into the prompt. When the LLM streams its answer, a dedicated `CitationService` intercepts tokens, extracts citation tags, verifies them against our server-side retrieval map, and discards any hallucinated citations. Document names, page numbers, and snippet previews are populated strictly from verified database records.
> 
> **Third, Defense-in-Depth Multi-Tenancy.** Client-provided tenant headers are never trusted blindly. Requests authenticate via Argon2id and rotating JWTs. The application verifies tenant membership in PostgreSQL and activates transaction-local Row-Level Security via `SET LOCAL app.current_tenant_id`. FastAPI and Celery connect using an unprivileged PostgreSQL user with `NOSUPERUSER` and `NOBYPASSRLS`, making cross-tenant data leakage mathematically impossible even in the event of an SQL injection.
> 
> The platform includes real-time SSE streaming, a dual-engine Ragas evaluation suite, Prometheus metrics, and automated CI/CD with 95 passing tests."

---

## 3. The 5-Minute Technical Deep-Dive

When conducting a 5-minute architectural walkthrough, break the discussion into four distinct architectural quadrants:

### Quadrant 1: Asynchronous Ingestion & Document Processing
* **Upload Ingress**: The client uploads enterprise PDFs via `POST /api/v1/documents/upload`. The API validates MIME types (`application/pdf`), enforces a 50MB ceiling, computes a SHA-256 content hash for deduplication, writes the file to disk, and enqueues an asynchronous task in Celery via Redis.
* **Extraction & Chunking**: The worker invokes PyMuPDF (`fitz`), which benchmarks at ~1.88 ms for 5-page PDFs. Text is extracted with exact page boundary metadata. A token-aware sliding window chunks text into 512-token segments with 50-token overlap, respecting sentence boundaries.
* **Embedding & Indexing**: Chunks are embedded using `BAAI/bge-small-en-v1.5` (384-dim, normalized). The worker writes vectors to Qdrant with tenant payload tags (`tenant_id`, `document_id`, `page_number`), creates in-memory BM25 indexes, and persists chunk metadata to PostgreSQL.

### Quadrant 2: Multi-Stage Hybrid Retrieval & Cross-Encoder Reranking
* **Parallel Retrieval**: When a query arrives, two parallel searches execute:
  1. *Dense Semantic Search*: Query embedded in ~180ms CPU, queried against Qdrant HNSW index with a payload filter `tenant_id == current_tenant_id`.
  2. *Sparse Lexical Search*: BM25Okapi scores term frequencies against tokenized chunk vocabulary (0.21ms latency).
* **Reciprocal Rank Fusion (RRF)**:
  $$RRF(d) = \frac{w_{\text{dense}}}{60 + r_{\text{dense}}(d)} + \frac{w_{\text{bm25}}}{60 + r_{\text{bm25}}(d)}$$
  RRF relies strictly on relative ordinal rank rather than raw scores, avoiding score normalization skew.
* **Neural Cross-Encoder Reranking**: The top-15 fused candidates are packaged into `(query, chunk_text)` pairs and scored by `BAAI/bge-reranker-base`. Cross-encoders evaluate cross-attention across all token combinations, identifying nuanced relevance that dual-encoders miss. Top 5 reranked chunks are selected.

### Quadrant 3: LLM Generation, Citations & Streaming
* **Context Construction**: Passages are assembled into a prompt with explicit source boundaries: `[SOURCE: S1] Document: Q3_Financials.pdf, Page 12: <chunk_text>`. Strict system prompt guardrails instruct the model to treat context as untrusted data and abstain if facts are missing.
* **SSE Token Streaming**: Tokens stream to the client in real time via Server-Sent Events (`event: token`).
* **Server-Side Citation Validation**: The LLM emits citation markers like `[S1]`. The `CitationService` extracts these markers, validates them against the actual context items provided, strips ungrounded markers, and sends a final `event: done` packet containing verified document IDs, filenames, page numbers, and text snippets.

### Quadrant 4: Security, Isolation & Production Reliability
* **PostgreSQL RLS with Dedicated Role**: Unlike naive implementations where the app connects as database superuser (bypassing RLS), our platform connects as `docintel_app` (`NOSUPERUSER`, `NOBYPASSRLS`). The session sets `app.current_tenant_id`, and policies enforce `tenant_id = current_setting('app.current_tenant_id')`.
* **Rate Limiting & Observability**: Redis sliding-window limiter throttles unauthenticated and authenticated requests. Prometheus exposes query durations, search latencies, and token counters at `/metrics`.
* **Testing & Quality**: 95 automated backend tests verify RLS isolation, JWT rotation, hybrid search, RRF math, reranker sorting, and citation extraction.

---

## 4. 60-Second Whiteboard Diagram Layout

When drawing this on a physical or digital whiteboard, use this clean 4-tier flow:

```
+-----------------------------------------------------------------------------------+
| 1. INGRESS & CLIENT LAYER                                                         |
|    React 18 SPA  ───( Bearer JWT + X-Tenant-ID )───>  Nginx Reverse Proxy          |
|                                                       │ (proxy_buffering off)     |
+-------------------------------------------------------┼---------------------------+
                                                        ▼
+-----------------------------------------------------------------------------------+
| 2. FASTAPI MODULAR MONOLITH (Port 8000)                                           |
|    • AuthMiddleware: Verify JWT & Tenant Membership in PostgreSQL                 |
|    • Session Context: SET LOCAL app.current_tenant_id = :tid                      |
|                                                                                   |
|    [ User Query ]                                                                 |
|         │                                                                         |
|         ├──────────────────────────────┬──────────────────────────────┐           |
|         ▼                              ▼                              ▼           |
|    [ Dense Search ]             [ Lexical Search ]             [ Ingestion Queue ]|
|    BGE-small (384-d)            BM25Okapi                      PyMuPDF -> Chunker |
|    Qdrant HNSW Filter           Tokenized In-Memory            Celery + Redis     |
|         │                              │                              │           |
|         └──────────────┬───────────────┘                              │           |
|                        ▼                                              ▼           |
|            [ Reciprocal Rank Fusion ]                       [ PostgreSQL 16 RLS ] |
|            RRF(d) = Σ w / (60 + rank)                       docintel_app Role     |
|                        │                                    FORCE RLS Policies    |
|                        ▼                                                          |
|            [ BGE Cross-Encoder Rerank ]                                           |
|            Top-15 Candidates -> Top-5 Passages                                    |
|                        │                                                          |
|                        ▼                                                          |
|            [ ContextBuilder + Prompt ]                                            |
|            Labeled as [SOURCE: S1], [SOURCE: S2]                                  |
|                        │                                                          |
|                        ▼                                                          |
|            [ OpenAI LLM Streaming ]                                               |
|                        │                                                          |
|                        ▼                                                          |
|            [ CitationService Validation ] ──> Server-Sent Events (SSE) to React   |
+-----------------------------------------------------------------------------------+
| 3. DATA & STORAGE ENCLAVES (Isolated by Tenant ID)                                |
|    • PostgreSQL 16: Users, Tenants, Memberships, Documents, Chunks, Chat, Evals   |
|    • Qdrant Vector DB: HNSW index with payload filter (tenant_id == current_tid)  |
|    • Redis 7: Celery Broker, Sliding-Window Rate Limiter, Blacklist Tokens        |
+-----------------------------------------------------------------------------------+
```

---

## 5. Whiteboard Follow-Up Defense FAQ

### Q: "Why Reciprocal Rank Fusion instead of just summing normalized vector and BM25 scores?"
> "Vector cosine similarities are bounded between 0 and 1 with a bell-curve distribution centered around 0.6–0.8 for dense models, whereas BM25 scores are unbounded positive numbers ($[0, \infty)$) dependent on document length and inverse document frequency. Normalizing them with Min-Max or Z-score introduces severe distortion when a single candidate has an extreme outlier score. RRF uses purely ordinal ranks, making it mathematically invariant to scale differences."

### Q: "Why not use a Cross-Encoder for the entire retrieval instead of a two-stage approach?"
> "A cross-encoder must evaluate joint self-attention across the concatenated tokens of the query and document. Running that across 10,000 document chunks would take minutes per query. A bi-encoder pre-computes document representations into 384-dimensional vectors, allowing Qdrant to perform sub-10ms Approximate Nearest Neighbor (ANN) search over millions of vectors. The cross-encoder is only invoked on the top-15 candidates, where its ~1.1s CPU latency is acceptable and its pairwise token attention yields maximum reranking impact."

### Q: "How do you prevent a malicious user from querying another tenant's documents?"
> "We implement defense-in-depth across three separate layers:
> 1. **Application Layer**: We parse `X-Tenant-ID` and query PostgreSQL `memberships` table for `(user_id, tenant_id)`. If the user is not an active member, the request immediately terminates with HTTP 403.
> 2. **PostgreSQL RLS Layer**: All queries run inside a database session with `app.current_tenant_id` set. Every tenant table has `FORCE ROW LEVEL SECURITY` enabled. Even if an engineer wrote `SELECT * FROM documents`, PostgreSQL automatically appends `WHERE tenant_id = current_setting('app.current_tenant_id')`. Because the app runs as `docintel_app` (`NOSUPERUSER`), RLS cannot be bypassed.
> 3. **Qdrant Vector DB**: Vector searches enforce an immutable `Filter(must=[FieldCondition(key="tenant_id", match=MatchValue(value=tenant_id))])` on every search."
