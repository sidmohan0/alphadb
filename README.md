# AlphaDB

High-performance vector similarity search engine in Rust, featuring HNSW (Hierarchical Navigable Small World) graph-based indexing.

## Features
- HNSW-based approximate nearest neighbor search
- Multiple similarity metrics (Cosine, Euclidean, Dot Product)
- REST API and Python bindings
- Async support and thread-safe queries
- Builder pattern for easy configuration

## Usage

### Rust
```rust
use alphadb::builder::VectorIndexBuilder;
use alphadb::SimilarityType;

// Create index
let mut index = VectorIndexBuilder::new(384)
    .with_similarity(SimilarityType::Cosine)
    .with_ef_construction(100)
    .build();

// Insert vectors
index.insert("doc1", &vector1)?;

// Query
let results = index.query(&query_vector, 5)?;
```

### REST API
```bash
# Start server
cargo run --features rest

# Insert vector
curl -X POST http://localhost:3000/insert -d '{"id": "doc1", "vector": [...]}'

# Query
curl -X POST http://localhost:3000/query -d '{"vector": [...], "k": 5}'
```

### Python
```python
from alphadb import PyVectorIndex

index = PyVectorIndex()
# ... use similar to Rust API
```

## Configuration
- `dimension`: Vector dimension (required)
- `m`: Max number of connections per node (default: 16)
- `ef_construction`: Index build quality parameter (default: 200)
- `ef_search`: Search quality parameter (default: 50)
- `similarity_type`: Distance metric (Cosine/Euclidean/DotProduct)

## Performance Notes
- Time Complexity: O(log n) for queries
- Space Complexity: O(n * d) where n=vectors, d=dimension
- In-memory storage only
- Single-node implementation

## Development

```bash
# Run tests
cargo test

# Run with features
cargo test --features rest
cargo test --features python

# Run examples
cargo run --example basic
```

## License
MIT 