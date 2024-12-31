# AlphaDB Quick Setup Guide

## Installation

Add this to your `Cargo.toml`:

```toml
[dependencies]
alphadb = { git = "https://github.com/yourusername/alphadb" }
```

## Basic Usage

Here's a complete example showing how to use the HNSW index:

```rust
use alphadb::HNSWIndex;

fn main() -> Result<(), Box<dyn std::error::Error>> {
    // Create a new index
    // Parameters: max_layers=4, ef_construction=100, m=16
    let mut index = HNSWIndex::new(4, 100, 16)?;

    // Insert some vectors
    index.insert("doc1".to_string(), vec![1.0, 0.0, 0.0])?;
    index.insert("doc2".to_string(), vec![0.0, 1.0, 0.0])?;
    index.insert("doc3".to_string(), vec![0.0, 0.0, 1.0])?;
    index.insert("doc4".to_string(), vec![0.5, 0.5, 0.0])?;

    // Search for nearest neighbors
    let query = vec![1.0, 0.0, 0.0];
    let k = 2; // number of nearest neighbors to return
    let results = index.search(&query, k)?;

    // Results contains (id, distance) pairs
    for (id, distance) in results {
        println!("ID: {}, Distance: {}", id, distance);
    }

    Ok(())
}
```

## Parameters Explained

- `max_layers`: Maximum number of layers in the hierarchy (typically 4-12)
- `ef_construction`: Size of the dynamic candidate list during construction (higher = more accurate but slower)
- `m`: Maximum number of connections per node per layer (typically 16-64)

## Performance Tips

1. Choose parameters based on your dataset:
   - Small dataset (<100K vectors): `max_layers=4, ef_construction=100, m=16`
   - Medium dataset (<1M vectors): `max_layers=6, ef_construction=200, m=32`
   - Large dataset (>1M vectors): `max_layers=8, ef_construction=400, m=48`

2. Vector dimensions:
   - All vectors (including queries) must have the same dimensions
   - Dimensions are set by the first vector inserted

## Example with Custom Types

```rust
#[derive(Debug)]
struct Document {
    id: String,
    title: String,
    embedding: Vec<f32>,
}

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let mut index = HNSWIndex::new(4, 100, 16)?;
    
    // Insert documents
    let docs = vec![
        Document {
            id: "1".to_string(),
            title: "First doc".to_string(),
            embedding: vec![1.0, 0.0, 0.0],
        },
        Document {
            id: "2".to_string(),
            title: "Second doc".to_string(),
            embedding: vec![0.0, 1.0, 0.0],
        },
    ];

    for doc in docs {
        index.insert(doc.id.clone(), doc.embedding)?;
    }

    // Search
    let query_vector = vec![1.0, 0.0, 0.0];
    let results = index.search(&query_vector, 1)?;
    
    println!("Nearest document ID: {}", results[0].0);
    Ok(())
}
```

## Current Limitations

1. In-memory only (no persistence)
2. Single-threaded implementation
3. Only L2 (Euclidean) distance metric supported
4. No delete operations
5. No vector updates

## Error Handling

The library uses custom error types for common issues:
- `DimensionMismatch`: Vector dimensions don't match
- `EmptyVector`: Attempted to insert empty vector
- `InvalidParameters`: Invalid index parameters
- `NodeNotFound`: Referenced node doesn't exist

## Benchmarking

The library includes a benchmark example that tests:
- Insertion performance
- Search performance
- Search accuracy
- Memory usage

To run the benchmarks:

```bash
cargo run --release --example benchmark
```

Expected performance (on modern hardware):
- Insertion: ~10,000 vectors/second
- Search: ~1,000 queries/second
- Memory: ~1.8GB per 1M vectors (128 dimensions)

Benchmark parameters can be adjusted in `examples/benchmark.rs`:
```rust
let n_vectors = 100_000;  // Number of vectors to insert
let n_queries = 1_000;    // Number of search queries
let dim = 128;           // Vector dimensions
let k = 10;             // Number of nearest neighbors to find
```

### Performance Tips

1. Index Parameters:
   ```rust
   // For better accuracy (slower):
   let index = HNSWIndex::new(8, 400, 48)?;
   
   // For better speed (less accurate):
   let index = HNSWIndex::new(4, 100, 16)?;
   ```

2. Memory vs Speed:
   - Higher `m` values use more memory but give better search accuracy
   - Higher `ef_construction` values give better index quality but slower insertion
   - The bottom layer uses `m0 = 2*m` connections for better recall

3. Production Settings:
   - Always use `--release` mode
   - Consider using larger `ef_construction` during index building
   - Monitor memory usage as the index grows 