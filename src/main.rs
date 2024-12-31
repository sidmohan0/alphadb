use alphadb::builder::VectorIndexBuilder;
use clap::Parser; // Updated import path

#[derive(Parser, Debug)]
#[command(name = "alphadb")]

enum Command {
    /// Insert a vector
    Insert {
        #[arg(short, long)]
        id: String,
        #[arg(short, long)]
        vector_file: String, // Path to a JSON file containing the vector
    },
    /// Query for similar vectors
    Query {
        #[arg(short, long)]
        vector_file: String,
        #[arg(short, long, default_value = "5")]
        k: usize,
    },
}

// ... existing code ...

fn main() {
    let _cmd = Command::parse(); // Add underscore to acknowledge unused variable
                                 // Or better yet, actually use the command:
    match Command::parse() {
        cmd => {
            // Handle your commands here
            println!("Received command: {:?}", cmd);
        }
    }
}
