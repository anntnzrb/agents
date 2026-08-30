use std::time::Duration;
use thiserror::Error;

#[derive(Debug, Error)]
pub enum RegistryError {
    #[error("could not resolve {package}@{tag} (registry HTTP {status})")]
    Http {
        package: String,
        tag: String,
        status: u16,
    },
    #[error("registry metadata has no dist-tags for {0}")]
    MissingDistTags(String),
    #[error("registry has no {tag} version for {package}")]
    MissingTag { package: String, tag: String },
    #[error("invalid resolved version: {0}")]
    InvalidVersion(String),
    #[error("registry request error: {0}")]
    Request(String),
}

pub trait VersionResolver: Send + Sync {
    fn resolve(
        &self,
        package_name: &str,
        dist_tag: &str,
        timeout: Duration,
    ) -> Result<String, RegistryError>;
}

/// Validates that a resolved version is valid `SemVer` (e.g. `1.2.3`, `2.0.0-beta.1`).
pub fn validate_resolved_version(version: &str) -> Result<String, RegistryError> {
    if semver::Version::parse(version).is_err() {
        return Err(RegistryError::InvalidVersion(version.to_string()));
    }
    Ok(version.to_string())
}

#[derive(Debug, Default)]
pub struct DefaultNpmRegistryResolver;

impl VersionResolver for DefaultNpmRegistryResolver {
    fn resolve(
        &self,
        package_name: &str,
        dist_tag: &str,
        timeout: Duration,
    ) -> Result<String, RegistryError> {
        std::thread::scope(|scope| {
            scope
                .spawn(|| {
                    let encoded_package = package_name.strip_prefix('@').map_or_else(
                        || package_name.to_string(),
                        |stripped| format!("%40{}", stripped.replace('/', "%2F")),
                    );

                    let url = format!("https://registry.npmjs.org/{encoded_package}");

                    let client = reqwest::blocking::Client::builder()
                        .timeout(timeout)
                        .build()
                        .map_err(|e| RegistryError::Request(e.to_string()))?;

                    let response = client
                        .get(&url)
                        .header("accept", "application/vnd.npm.install-v1+json")
                        .send()
                        .map_err(|e| RegistryError::Request(e.to_string()))?;

                    if !response.status().is_success() {
                        return Err(RegistryError::Http {
                            package: package_name.to_string(),
                            tag: dist_tag.to_string(),
                            status: response.status().as_u16(),
                        });
                    }

                    let metadata: serde_json::Value = response
                        .json()
                        .map_err(|e| RegistryError::Request(e.to_string()))?;

                    let dist_tags = metadata
                        .get("dist-tags")
                        .and_then(|v| v.as_object())
                        .ok_or_else(|| RegistryError::MissingDistTags(package_name.to_string()))?;

                    let version_str = dist_tags
                        .get(dist_tag)
                        .and_then(|v| v.as_str())
                        .ok_or_else(|| RegistryError::MissingTag {
                            package: package_name.to_string(),
                            tag: dist_tag.to_string(),
                        })?;

                    validate_resolved_version(version_str)
                })
                .join()
                .map_err(|_| RegistryError::Request("registry fetch thread panicked".to_string()))?
        })
    }
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
    fn test_validate_resolved_version() {
        assert_eq!(validate_resolved_version("1.2.3").unwrap(), "1.2.3");
        assert_eq!(
            validate_resolved_version("2.0.0-beta.1").unwrap(),
            "2.0.0-beta.1"
        );
        assert!(validate_resolved_version("invalid-semver").is_err());
        assert!(validate_resolved_version("").is_err());
    }
}
