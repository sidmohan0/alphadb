# Build your project
cargo build              # Debug build
cargo build --release    # Optimized release build

# Run your project
cargo run               # Build and run debug version
cargo run --release     # Build and run release version

# Test your code
cargo test              # Run all tests
cargo test <testname>   # Run specific test
cargo test -- --nocapture  # Show println! output in tests

# Check compilation without producing binary
cargo check             # Faster than build for catching errors

# Format your code
cargo fmt               # Format according to Rust style guidelines

# Lint your code
cargo clippy            # Run the Rust linter
cargo clippy --fix     # Auto-fix some common issues

# Clean build artifacts
cargo clean            # Remove target directory

# Generate and view docs locally
cargo doc              # Generate documentation
cargo doc --open       # Generate and open in browser

# Since you're using PyO3, you might want to use maturin
maturin develop       # Build and install in current virtualenv
maturin build        # Build wheel files