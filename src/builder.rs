use crate::{IndexParams, SimilarityType, VectorIndex};

pub struct VectorIndexBuilder {
    params: IndexParams,
    similarity_type: SimilarityType,
}

impl VectorIndexBuilder {
    pub fn new(dimension: usize) -> Self {
        Self {
            params: IndexParams {
                dimension,
                m: 16,
                ef_construction: 200,
                ef_search: 50,
                similarity_type: SimilarityType::Cosine,
            },
            similarity_type: SimilarityType::Cosine,
        }
    }

    pub fn with_m(mut self, m: usize) -> Self {
        self.params.m = m;
        self
    }

    pub fn with_ef_construction(mut self, ef: usize) -> Self {
        self.params.ef_construction = ef;
        self
    }

    pub fn with_similarity(mut self, sim_type: SimilarityType) -> Self {
        self.params.similarity_type = sim_type;
        self.similarity_type = sim_type;
        self
    }

    pub fn build(self) -> VectorIndex {
        VectorIndex::new(self.params)
    }
}
