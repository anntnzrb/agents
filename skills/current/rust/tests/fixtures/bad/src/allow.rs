//! Suppression violation.
/// Suppresses a lint rather than satisfying it.
#[allow(clippy::needless_return)]
#[must_use = "Read the result"]
pub const fn suppressed() -> u32 {
    return 1;
}

#[cfg(test)]
mod tests {
    #[test]
    #[ignore]
    fn silently_disabled() {
        assert_eq!(super::suppressed(), 1, "suppressed must return one");
    }
}
