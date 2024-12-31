use pyo3::prelude::*;
use pyo3::wrap_pyfunction;

#[pyclass]
struct PyVectorIndex {
    inner: VectorIndex,
}

#[pymethods]
impl PyVectorIndex {
    #[new]
    fn new(dimension: usize) -> Self {
        Self {
            inner: VectorIndexBuilder::new(dimension).build()
        }
    }

    fn insert(&mut self, id: &str, vector: Vec<f32>) -> PyResult<()> {
        self.inner.insert(id, &vector)?;
        Ok(())
    }

    fn query(&self, vector: Vec<f32>, k: usize) -> Vec<(String, f32)> {
        self.inner.query(&vector, k)
    }
} 