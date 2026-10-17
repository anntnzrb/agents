//! Panic violation.
/// Unwraps unchecked input.
#[must_use = "Read the result"]
pub fn unchecked(value: Option<u32>) -> u32 {
    value.unwrap()
}
