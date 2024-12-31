# AlphaDB Testing Guide

## Technical Overview

AlphaDB is a minimal vector similarity search implementation in Rust, focusing on:
- In-memory vector storage and retrieval
- HNSW-based approximate nearest neighbor search
- Multiple similarity metrics (cosine, euclidean, dot product)

## Design Decisions

### Core Architecture
- Single-node, in-memory design
- No persistence layer
- Graph-based ANN using HNSW algorithm
- Rust implementation for memory safety and performance

### Technical Limitations
- Maximum ~1M vectors (384 dimensions) in memory
- No distributed support
- Basic concurrency model (read-heavy)
- No compression/quantization

### Implementation Notes
- Uses f32 for vector components
- Brute force search for MVP, HNSW planned
- Thread-safe query operations
- Lock-based concurrency

## Performance Notes

### Memory Usage
- Vector storage: 4 bytes × dimensions × count
- Index overhead: ~20% of vector storage
- Runtime allocations: minimal, preallocated where possible

### Query Performance
- O(log n) average case with HNSW
- Linear scan fallback in edge cases
- Parallel query support via rayon

### Build Performance
- Sequential insertion: O(n log n)
- Bulk insertion: O(n log n) with better constants
- Index construction: configurable quality/speed tradeoff

## Development Roadmap

### Current Focus
- SIMD optimizations
- Basic HNSW implementation
- Query performance improvements

### Planned Features
- Persistence layer
- Better concurrency
- Quantization support

## Contributing

### Priority Areas
- SIMD implementations
- Index structure improvements
- Benchmarking infrastructure

### Development Setup
- Standard Rust toolchain
- No special requirements
- Tests must pass on both x86_64 and aarch64 