# PostgreSQL with pgvector is the only data store

Profiles, vectors, full-text index and the ingestion queue all live in one PostgreSQL database (pgvector extension). Queries such as "10 years in consulting" need SQL filters next to similarity search, and a second system (a dedicated vector database plus a broker) would add synchronisation and operations for a corpus that is far below the point where it pays off. The same image runs locally (Docker) and on Azure Database for PostgreSQL Flexible Server.

**Considered options:** Azure AI Search (strong hybrid search, but a second store to keep consistent and a costly SKU for a small corpus); Qdrant/Pinecone (extra service, no relational filters).

**Consequences:** the queue is a table claimed with `FOR UPDATE SKIP LOCKED`, which is correct for several workers but is not a replacement for a broker at very high throughput. HNSW indexes stay valid up to 2,000 dimensions, which is why embeddings are shortened to 1,024.
