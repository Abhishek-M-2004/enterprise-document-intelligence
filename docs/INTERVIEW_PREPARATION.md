# Comprehensive Technical Interview Preparation Guide
## Multi-Tenant Enterprise Document Intelligence Platform | Advanced RAG

This document provides in-depth, production-grounded interview questions and answers covering every layer of the platform: System Design, RAG & AI Engineering, Backend & Database Architecture, Multi-Tenant Security, Performance Optimization, and DevOps.

---

# SECTION A: Project Overview & High-Level Architecture

### Q1: Can you describe your project in 2–3 sentences?
> "I designed and built a Multi-Tenant Enterprise Document Intelligence Platform that allows organizations to securely ingest confidential PDF documents and query them using an advanced, hallucination-resistant RAG pipeline. It couples dense vector search in Qdrant with BM25 lexical search using Reciprocal Rank Fusion, followed by a BGE Cross-Encoder neural reranking stage to maximize retrieval precision. The system enforces cryptographic multi-tenant isolation via PostgreSQL Row-Level Security with an unprivileged database role, streams conversational answers with server-verified citations via Server-Sent Events, and evaluates retrieval quality using Ragas across 95 automated backend tests."

### Q2: What exact problem does this platform solve for enterprise users?
> "Enterprises sit on massive volumes of unstructured PDF data—financial reports, legal agreements, vendor contracts, technical specs—where answers must be exact, fully traceable, and isolated by organization.
> 
> Standard off-the-shelf RAG pipelines fail in three major ways:
> 1. **Retrieval Blindspots**: Pure vector search misses alphanumeric identifiers (like invoice `#INV-2024-9981` or regulatory clause numbers) that BM25 catches effortlessly.
> 2. **Ranking Inaccuracy**: Bi-encoders struggle to prioritize fine-grained nuances, resulting in irrelevant chunks being sent to the LLM.
> 3. **Data Leakage & Hallucination**: Weak multi-tenancy relies on application `WHERE` clauses that leak data if a developer makes a coding mistake, and LLMs invent false citations if source tracking is not verified server-side.
> 
> Our platform addresses all three with hybrid RRF retrieval, BGE cross-encoder reranking, PostgreSQL RLS, and server-side citation validation."

### Q3: Why did you choose a Modular Monolith over Microservices?
> "We chose a modular monolith for three critical engineering reasons:
> 1. **Transactional Integrity & Session Parameters**: Multi-tenant isolation relies on setting `app.current_tenant_id` within the PostgreSQL transaction session. Splitting services would have necessitated distributed transaction coordinators or fragile token forwarding.
> 2. **Zero Network Serialization Overhead**: In a RAG pipeline, candidate passages (often 50–100 kB of text) move from retrieval to reranker to context builder. Keeping this in-memory in a single process eliminates HTTP/gRPC serialization, JSON parsing overhead, and network hops.
> 3. **Simplicity of Deployment & Migrations**: A single unified container with Alembic migrations avoids distributed schema drift and coordinated deployments. The codebase enforces strict unidirectional dependency injection (`API` $\rightarrow$ `Services` $\rightarrow$ `DB`), so any domain (e.g. Ingestion or Reranking) can easily be split into an independent worker service if scaling requires it."

---

# SECTION B: System Design & Scalability

### Q4: Walk me through the end-to-end data lifecycle when a user uploads a document.
> "The ingestion pipeline is completely asynchronous:
> 1. **Ingress**: User sends a multipart PDF to `POST /api/v1/documents/upload`. The API verifies MIME type, checks a 50MB size ceiling, calculates a SHA-256 hash to detect duplicates, stores the raw PDF in tenant-segregated disk storage (`/storage/documents/{tenant_id}/`), creates a `Document` record in PostgreSQL with status `PENDING`, and dispatches a Celery task via Redis. The API returns `HTTP 202 Accepted` in under 30ms.
> 2. **Parsing**: The Celery worker opens the file using PyMuPDF (`fitz`), which parses text page-by-page while tracking page metadata.
> 3. **Chunking**: Text is split into 512-token windows with 50-token overlap, snapping to sentence boundaries (`. `, `\n\n`) to preserve semantic coherence.
> 4. **Embedding**: Chunks are batched and embedded using `BAAI/bge-small-en-v1.5` into 384-dimensional dense vectors.
> 5. **Indexing**: Vectors are written to Qdrant with payload metadata (`tenant_id`, `document_id`, `chunk_id`, `page_number`). Simultaneously, chunk text and metadata are inserted into PostgreSQL under the tenant's RLS policy.
> 6. **State Transition**: The document status transitions to `COMPLETED`, updating Prometheus gauges."

### Q5: What are the primary bottlenecks in this architecture, and how do you scale them?
> 1. **Cross-Encoder Neural Reranking**: The BGE cross-encoder evaluates joint self-attention across 15 candidate pairs, taking ~1.17s on CPU.
>    * *Scaling Strategy*: Offload the reranker model to a GPU-enabled inference worker (e.g. Triton Inference Server, vLLM, or dedicated Celery GPU nodes) or run ONNX Runtime / TensorRT with FP16 quantization to reduce latency to <100ms.
> 2. **Embedding Ingestion**: High-volume document uploads can saturate CPU.
>    * *Scaling Strategy*: Celery workers scale horizontally across independent nodes. Because workers are stateless consumers pulling from Redis, adding more worker pods scales ingestion linearly.
> 3. **Vector Database Scalability**: As tenant collections reach millions of points, in-memory HNSW graphs consume significant RAM.
>    * *Scaling Strategy*: Qdrant supports scalar quantization (int8) reducing memory footprint by 4x, as well as distributed sharding across nodes with tenant-based shard keys."

### Q6: How do you handle cache invalidation when a document is updated or deleted?
> "When a document is deleted via `DELETE /api/v1/documents/{document_id}`:
> 1. PostgreSQL deletes the document record, and database cascade constraints instantly delete all corresponding `document_chunks`.
> 2. A Qdrant client call executes `delete(collection, points_selector=Filter(must=[FieldCondition(key="document_id", match=MatchValue(value=document_id))]))`, removing all vector points immediately.
> 3. The raw file is unlinked from storage.
> 4. Any cached search results or in-memory BM25 index for that tenant is rebuilt or invalidated upon next query."

---

# SECTION C: RAG & AI Engineering Deep Dive

### Q7: Why use Hybrid Retrieval instead of pure vector search?
> "Pure vector search relies on semantic similarity in a compressed embedding space (e.g., 384 dimensions). While it is exceptional at understanding concepts (e.g. 'automobile repair' matching 'car maintenance'), it has well-documented failure modes:
> 1. **Exact Token Matching**: It struggles with product SKUs, serial numbers, invoice IDs, and specialized technical terms that were rare in the embedding model's pre-training corpus.
> 2. **Short Entity Queries**: Single-word queries produce diffuse vector representations with low discrimination.
> 
> BM25Okapi is based on inverse document frequency (IDF) and term frequency (TF), making it mathematically optimal for exact keyword precision. By combining both, we ensure that both conceptual questions and exact-keyword queries retrieve relevant passages."

### Q8: Explain Reciprocal Rank Fusion (RRF) and why it outperforms weighted score combination.
> "BM25 produces unbounded scores $[0, \infty)$ where the scale depends heavily on document lengths and corpus vocabulary. Dense vector search produces cosine similarities $[-1, 1]$ typically clustered between $0.6$ and $0.85$.
> 
> If you combine them using a linear formula like $\alpha \cdot S_{\text{dense}} + \beta \cdot S_{\text{bm25}}$, you must normalize both distributions. Standard Min-Max normalization fails catastrophically when an outlier score appears, compressing all other scores.
> 
> Reciprocal Rank Fusion eliminates score distribution dependencies by relying purely on ordinal rank positions:
> $$RRF(d) = \sum_{m \in M} \frac{w_m}{k + r_m(d)}$$
> With $k=60$, a document appearing near the top of both lists receives an additive boost that reliably outranks documents that only appear in one list. It is computationally lightweight (0.07 ms) and parameter-robust."

### Q9: Why use a Cross-Encoder for reranking instead of just taking the top vectors from Qdrant?
> "Bi-encoders (like BGE-small) embed query and document separately into static vector points: $s = \cos(\mathbf{e}_q, \mathbf{e}_d)$. No token in the query ever interacts directly with any token in the document during embedding generation.
> 
> In contrast, a Cross-Encoder feeds the concatenated string `[CLS] Query [SEP] Document [SEP]` through the transformer layers. Every query token performs self-attention with every document token across all layers. This allows the model to capture complex logic, negation (e.g. 'not eligible for refund'), conditional clauses, and positional importance.
> 
> However, cross-encoders cannot be pre-indexed into an ANN graph because the computation requires the query at runtime ($O(N)$ transformer passes). Therefore, our two-stage architecture retrieves 15 candidate passages with the fast bi-encoder + BM25, and uses the cross-encoder strictly to rerank those 15 down to the top 5."

### Q10: How do you prevent LLM hallucinations and enforce citation accuracy?
> "We prevent hallucinations using a 3-layer verification pattern:
> 1. **Standardized Context Tagging**: `ContextBuilder` wraps retrieved passages with explicit identifiers:
>    `[SOURCE: S1] Document: Policy.pdf, Page: 4: <passage_text>`
> 2. **Anti-Injection Prompt Directives**: The system prompt instructs the LLM:
>    - You must only answer using the facts provided in the `[SOURCE: S*]` passages.
>    - Cite your claims using `[S1]`, `[S2]`.
>    - If the provided sources do not contain the answer, state clearly: *'The requested information could not be found in the uploaded enterprise documents.'* Do not extrapolate.
> 3. **Server-Side Citation Validation (`CitationService`)**:
>    The LLM outputs raw bracketed markers like `[S1]`. The server regex-extracts these markers, matches them against the internal verified source map, and deletes any ungrounded markers (e.g. `[S99]`). The frontend receives genuine metadata (document filename, page number, chunk preview) populated exclusively by the server."

### Q11: Explain your RAG evaluation strategy (Ragas vs. Deterministic).
> "Evaluating RAG requires measuring both the retrieval component and the generation component. We built a dual-engine architecture:
> 1. **Ragas LLM-as-Judge**:
>    - *Faithfulness*: Uses an LLM to extract claims from the generated answer and verifies if each claim is entailed by the retrieved context. (Measures hallucination rate).
>    - *Answer Relevancy*: Evaluates if the answer directly addresses the query without superfluous fluff.
>    - *Context Precision*: Checks whether ground-truth relevant passages appear higher in the candidate ranking.
>    - *Context Recall*: Verifies if all necessary reference facts from the ground truth answer were retrieved.
> 2. **Deterministic Offline Engine**:
>    - For air-gapped systems, local development, and CI/CD pipelines, we cannot rely on external OpenAI API keys or incur LLM judge costs. We implemented a deterministic evaluation engine using token overlap, TF-IDF lexical similarity, and rank-based heuristics that executes in $<5$ ms with zero cost."

---

# SECTION D: Backend, Database & Storage Architecture

### Q12: How do you handle async database sessions in FastAPI with SQLAlchemy 2.0?
> "We use SQLAlchemy 2.0 with the `asyncpg` async driver. Sessions are injected into API endpoints via FastAPI's `Depends(get_db)`.
> 
> Key implementation details:
> 1. **Connection Pooling**: We configure `create_async_engine` with `pool_size=20`, `max_overflow=10`, and `pool_pre_ping=True` to detect dropped connections.
> 2. **Session Cleanup & Isolation**: The `get_db` dependency uses an `async with` block. In the `finally:` block, it executes `RESET app.current_tenant_id` before returning the connection to the pool, preventing connection-pool contamination across requests.
> 3. **Transaction Scoping**: Read operations run in implicit transactions, while write operations explicitly call `await db.commit()`."

### Q13: How do you manage database migrations without downtime?
> "Database migrations are managed via **Alembic**.
> 1. Migrations are executed by a dedicated startup migration container or CI step running as the superuser (`postgres`), completely decoupled from the web application runtime (`docintel_app`).
> 2. We follow forward-compatible migration practices:
>    - Adding columns as nullable or with safe defaults.
>    - Creating indexes concurrently (`CREATE INDEX CONCURRENTLY`) to prevent locking production tables.
>    - Never dropping or renaming columns in the same release as application code changes."

---

# SECTION E: Security, Multi-Tenancy & Authorization

### Q14: How does your PostgreSQL Row-Level Security (RLS) implementation work under the hood?
> "Many developers enable RLS but connect their web app using the default `postgres` superuser. PostgreSQL superusers automatically bypass all RLS policies, creating an illusion of security.
> 
> Our implementation is genuinely secure:
> 1. **Dedicated Role**: FastAPI connects as `docintel_app`, which explicitly has `NOSUPERUSER` and `NOBYPASSRLS`.
> 2. **Forced RLS**: Every tenant table has `ALTER TABLE <name> FORCE ROW LEVEL SECURITY;`. This ensures policies apply even to table owners.
> 3. **Tenant Context Injection**: When an authenticated request arrives, the application verifies the user's membership in the target organization and executes:
>    ```sql
>    SELECT set_config('app.current_tenant_id', :tenant_id, false);
>    ```
> 4. **Policy Enforcement**: Every tenant table has a policy:
>    ```sql
>    CREATE POLICY tenant_isolation_policy ON documents
>    USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid);
>    ```
>    If `app.current_tenant_id` is missing or empty, the query fails closed and returns 0 rows. Even if an attacker injects `SELECT * FROM documents`, they can only see records belonging to their active tenant."

### Q15: How does your Authentication and JWT lifecycle work?
> "We implement a high-security rotating token pattern:
> 1. **Password Hashing**: Passwords are hashed using **Argon2id** (memory cost 65536, time cost 3, parallelism 4), which is resistant to GPU-based brute-force attacks.
> 2. **Access Tokens**: Short-lived JWTs (15-minute expiration) signed with HMAC-SHA256, carrying `user_id` and token type. Access tokens are held exclusively in React memory, never in `localStorage` (protecting against XSS).
> 3. **Refresh Tokens**: Cryptographically secure, high-entropy 64-character hex strings stored as **SHA-256 hashes** in the database with a 7-day TTL.
> 4. **Token Rotation & Replay Protection**: When `/auth/refresh` is called, the database row is locked with `SELECT ... FOR UPDATE`. The old refresh token is immediately revoked, and a new key pair is issued. If a revoked token is ever presented again, the system detects a token theft / replay attack and immediately revokes all refresh tokens belonging to that user."

---

# SECTION F: Performance, Latency & Optimization

### Q16: What are the measured latencies across your system?
> "Based on our benchmark suite:
> * **PostgreSQL Connection Ping**: Avg 3.84 ms (p95 15.19 ms).
> * **Tenant-Scoped Indexed Query**: Avg **0.67 ms** (p95 0.87 ms) across 54 indexes.
> * **PDF Text Extraction (PyMuPDF)**: **1.88 ms** for 5-page PDF, **3.36 ms** for 15-page PDF.
> * **Dense Embedding Generation (CPU)**: ~180 ms for BGE-small (384 dimensions).
> * **In-Memory BM25 Lexical Search**: **0.21 ms** across 50 chunk candidates.
> * **Reciprocal Rank Fusion**: **0.07 ms** for top-15 candidate fusion.
> * **BGE Cross-Encoder Reranking (CPU)**: **~1.17 s** for top-15 down to top-5 passages.
> * **Time to First Token (TTFT)**: ~1.4–1.8 s (including retrieval, reranking, and first LLM streaming token)."

### Q17: Why did you have to configure Nginx specifically for Server-Sent Events (SSE)?
> "By default, Nginx buffers upstream responses in memory before sending them to the client. When using Server-Sent Events for LLM streaming, Nginx would hold back tokens until its 4KB buffer was filled, turning a smooth real-time stream into choppy, delayed bursts.
> 
> To fix this, our Nginx configuration explicitly disables buffering for chat endpoints:
> ```nginx
> location /api/v1/chat/ {
>     proxy_pass http://fastapi_backend;
>     proxy_buffering off;
>     proxy_cache off;
>     proxy_set_header X-Accel-Buffering no;
> }
> ```
> This guarantees that each token chunk generated by the LLM is pushed to the client browser over TCP within milliseconds."

---

# SECTION G: DevOps, Reliability & Production Readiness

### Q18: How do you verify system health in a containerized or Kubernetes environment?
> "We implement separate **Liveness** and **Readiness** probes following Kubernetes best practices:
> 1. **Liveness Probe (`/api/v1/health/live`)**: Checks if the FastAPI process is alive and responsive. Does not probe downstream dependencies. If this fails, the container orchestrator restarts the container.
> 2. **Readiness Probe (`/api/v1/health/ready`)**: Performs active pings against PostgreSQL, Redis, and Qdrant. If any dependency is down or in recovery, it returns `HTTP 503 Service Unavailable`. This instructs load balancers to stop sending user traffic to the instance without triggering an unnecessary restart loop."

### Q19: What is your disaster recovery and database backup procedure?
> "We built automated backup and restoration scripts in `scripts/`:
> 1. **Automated Backups (`backup_db.py`)**: Executes `pg_dump` via `docker exec sentinel-postgres` to create compressed, timestamped custom-format archive dumps (`.dump`). It computes a SHA-256 checksum and enforces an automatic 7-day retention policy, pruning old dumps.
> 2. **Point-in-Time Restore (`restore_db.py`)**: Validates the dump archive, checks checksum integrity, terminates active database connections, runs `pg_restore --clean --if-exists`, and executes post-restore integrity assertions.
> 3. **Automated Verification (`test_backup_restore.py`)**: Runs in CI to inject canary test records, dump the database, truncate tables, restore from the dump, and assert the exact state of the canary data."

### Q20: How many tests do you have and what do they cover?
> "We have **95 passing automated backend tests** spanning 15 test suites with zero failures:
> * `test_auth.py` & `test_auth_flow.py`: Registration, Argon2id verification, JWT rotation, token revocation.
> * `test_security_multitenancy.py` & `test_rls_policies.py`: Cross-tenant access rejection, unprivileged role RLS validation, fail-closed assertions.
> * `test_document_pipeline.py`: PyMuPDF parsing, token chunking, metadata retention.
> * `test_hybrid_retrieval.py` & `test_rrf.py`: BM25 tokenization, dense vector integration, RRF math correctness.
> * `test_reranker.py`: Cross-encoder score calibration and candidate reordering.
> * `test_citations.py`: Citation regex extraction, source map verification, hallucination marker stripping.
> * `test_ragas_evaluation.py` & `test_deterministic_eval.py`: Ragas metrics, offline metric calculations, missing ground-truth handling.
> * `test_rate_limiter.py`: Redis sliding-window enforcement and fail-open fallback."
