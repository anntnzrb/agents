//! Arithmetic violation.
/// Adds without checking overflow.
#[must_use = "Read the result"]
pub const fn unchecked(value: u32) -> u32 {
    value + 1
}
