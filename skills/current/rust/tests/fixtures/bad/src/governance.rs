//! Inner suppression caught by governance rather than the outer-attribute lint.
#![allow(clippy::needless_return, reason = "Deliberate governance fixture")]

/// Returns a fixed value with a deliberately suppressed needless return.
#[must_use = "Read the result"]
pub const fn suppressed() -> u32 {
    return 1;
}
