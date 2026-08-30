use std::collections::BTreeMap;
use thiserror::Error;

#[derive(Debug, Error)]
pub enum SpecValidationError {
    #[error("invalid {label}: {value}")]
    InvalidComponent { label: String, value: String },
    #[error("invalid package: {0}")]
    InvalidPackage(String),
    #[error("missing smoke check")]
    MissingSmokeCheck,
}

#[derive(Debug, Clone, PartialEq, Eq, serde::Serialize, serde::Deserialize)]
pub struct NpmPackageSpec {
    pub tool: String,
    pub package: String,
    pub bin: String,
    pub dist_tag: Option<String>,
    pub smoke_check: Option<String>,
    pub env: Option<BTreeMap<String, String>>,
}

/// Checks if a string satisfies `^[A-Za-z0-9._-]+$` and is not "." or "..".
#[must_use]
pub fn is_valid_component(value: &str) -> bool {
    !value.is_empty()
        && value != "."
        && value != ".."
        && value
            .chars()
            .all(|c| c.is_ascii_alphanumeric() || c == '.' || c == '_' || c == '-')
}

/// Checks if a string satisfies `^(?:@[A-Za-z0-9._~-]+\/)?[A-Za-z0-9._~-]+$`.
#[must_use]
pub fn is_valid_package_name(package: &str) -> bool {
    if package.is_empty() {
        return false;
    }

    let is_package_component = |s: &str| -> bool {
        !s.is_empty()
            && s != "."
            && s != ".."
            && s.chars()
                .all(|c| c.is_ascii_alphanumeric() || c == '.' || c == '_' || c == '~' || c == '-')
    };

    if let Some(stripped) = package.strip_prefix('@') {
        let mut parts = stripped.split('/');
        let Some(scope) = parts.next() else {
            return false;
        };
        let Some(name) = parts.next() else {
            return false;
        };
        if parts.next().is_some() {
            return false;
        }
        is_package_component(scope) && is_package_component(name)
    } else {
        if package.contains('/') {
            return false;
        }
        is_package_component(package)
    }
}

/// Validates an `NpmPackageSpec`.
pub fn validate_spec(spec: &NpmPackageSpec) -> Result<(), SpecValidationError> {
    if !is_valid_component(&spec.tool) {
        return Err(SpecValidationError::InvalidComponent {
            label: String::from("tool"),
            value: spec.tool.clone(),
        });
    }

    if !is_valid_component(&spec.bin) {
        return Err(SpecValidationError::InvalidComponent {
            label: String::from("bin"),
            value: spec.bin.clone(),
        });
    }

    let tag = spec.dist_tag.as_deref().unwrap_or("latest");
    if !is_valid_component(tag) {
        return Err(SpecValidationError::InvalidComponent {
            label: String::from("dist-tag"),
            value: tag.to_string(),
        });
    }

    if !is_valid_package_name(&spec.package) {
        return Err(SpecValidationError::InvalidPackage(spec.package.clone()));
    }

    if let Some(smoke) = &spec.smoke_check
        && smoke != "-"
        && smoke.trim().is_empty()
    {
        return Err(SpecValidationError::MissingSmokeCheck);
    }

    Ok(())
}

#[cfg(test)]
#[allow(
    clippy::unwrap_used,
    clippy::expect_used,
    clippy::indexing_slicing,
    clippy::panic
)]
mod tests {
    use super::*;

    #[test]
    fn test_valid_components() {
        assert!(is_valid_component("codex"));
        assert!(is_valid_component("cli.proxy-api_v2"));
        assert!(!is_valid_component(""));
        assert!(!is_valid_component("."));
        assert!(!is_valid_component(".."));
        assert!(!is_valid_component("has/slash"));
        assert!(!is_valid_component("has space"));
    }

    #[test]
    fn test_valid_package_names() {
        assert!(is_valid_package_name("mcporter"));
        assert!(is_valid_package_name("@openai/codex"));
        assert!(is_valid_package_name("@steipete/summarize"));
        assert!(is_valid_package_name("package-with.dots_and~tilde"));
        assert!(!is_valid_package_name(""));
        assert!(!is_valid_package_name("@openai/"));
        assert!(!is_valid_package_name("@/package"));
        assert!(!is_valid_package_name("too/many/slashes"));
        assert!(!is_valid_package_name("invalid chars in package"));
    }

    #[test]
    fn test_validate_spec() {
        let valid = NpmPackageSpec {
            tool: String::from("demo"),
            package: String::from("@scope/demo-package"),
            bin: String::from("demo"),
            dist_tag: Some(String::from("latest")),
            smoke_check: Some(String::from("--version")),
            env: None,
        };
        assert!(validate_spec(&valid).is_ok());

        let invalid_tool = NpmPackageSpec {
            tool: String::from("../escape"),
            ..valid.clone()
        };
        assert!(validate_spec(&invalid_tool).is_err());

        let empty_smoke = NpmPackageSpec {
            smoke_check: Some(String::from("   ")),
            ..valid.clone()
        };
        assert!(matches!(
            validate_spec(&empty_smoke),
            Err(SpecValidationError::MissingSmokeCheck)
        ));

        let dash_smoke = NpmPackageSpec {
            smoke_check: Some(String::from("-")),
            ..valid
        };
        assert!(validate_spec(&dash_smoke).is_ok());
    }
}
