use std::collections::{HashMap, HashSet};
use std::fs;
use std::path::{Path, PathBuf};
use thiserror::Error;
use url::Url;

use crate::catalog::cache::{
    CacheSource, CachedJsonRequest, CachedJsonResult, CatalogFetcher, fetch_cached_json,
};
use crate::catalog::model::{
    CatalogAlias, GatewayCatalogOptions, ModelCatalogSource, SourceModels, enrich_gateway_models,
    models_for_source, open_ai_data_rows, write_model_catalog,
};
use crate::cliproxy::deployment::{
    CliProxyDeployment, cli_proxy_models_url, cli_proxy_rich_models_url,
};
use crate::runtime::fs::sync_private_text_file;

pub const POOL_MARKER: &str = "x-credential-pool";
pub const MODEL_SOURCES_MARKER: &str = "x-model-sources";
pub const MAX_CREDENTIAL_WEIGHT: u32 = 1_000_000;
pub const MODELS_DEV_URL: &str = "https://models.dev/api.json";
pub const MODELS_DEV_TTL_MS: u64 = 60 * 60 * 1000;
pub const UPSTREAM_MODELS_TTL_MS: u64 = 6 * 60 * 60 * 1000;
pub const GATEWAY_MODELS_TTL_MS: u64 = 60 * 60 * 1000;

pub const NATIVE_CREDENTIAL_SECTIONS: &[&str] = &[
    "claude-api-key",
    "codex-api-key",
    "gemini-api-key",
    "interactions-api-key",
    "vertex-api-key",
    "xai-api-key",
];

#[derive(Debug, Error)]
pub enum CliProxyConfigError {
    #[error("invalid pool name: {0}")]
    InvalidPoolName(String),

    #[error("missing CLIProxyAPI credential pool: {0}")]
    MissingPool(String),

    #[error("unreferenced CLIProxyAPI credential pool: {0}")]
    UnreferencedPools(String),

    #[error("duplicate API key in CLIProxyAPI credential pool {0}: {1}")]
    DuplicateApiKey(String, String),

    #[error("invalid {0}: expected {1}")]
    ExpectedStructure(String, String),

    #[error("invalid {0}")]
    InvalidField(String),

    #[error("invalid {0}: {1}")]
    FieldValidation(String, String),

    #[error("invalid {0}: unknown field {1}")]
    UnknownField(String, String),

    #[error("duplicate CLIProxyAPI model alias: {0}")]
    DuplicateAlias(String),

    #[error("missing CLIProxyAPI model source: {0}")]
    MissingSource(String),

    #[error(
        "missing CLIProxyAPI model sources: credential pool models were discovered without model sources"
    )]
    MissingModelSources,

    #[error("missing {0}")]
    MissingRequirement(String),

    #[error("parse CLIProxyAPI template ({0})")]
    ParseTemplateFailed(String),

    #[error("parse CLIProxyAPI secrets {0} ({1})")]
    ParseSecretsFailed(String, String),

    #[error("render CLIProxyAPI config {0} -> {1} ({2})")]
    RenderConfigFailed(String, String, String),

    #[error("I/O error: {0}")]
    Io(#[from] std::io::Error),

    #[error("JSON error: {0}")]
    Json(#[from] serde_json::Error),

    #[error("YAML error: {0}")]
    Yaml(#[from] serde_yaml::Error),

    #[error("catalog error: {0}")]
    Catalog(#[from] crate::catalog::model::CatalogError),

    #[error("cache error: {0}")]
    Cache(#[from] crate::catalog::cache::CacheError),
}

#[derive(Debug, Clone, PartialEq, Eq, serde::Serialize, serde::Deserialize)]
pub struct Credential {
    #[serde(rename = "apiKey", alias = "api-key")]
    pub api_key: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub weight: Option<u32>,
    #[serde(
        rename = "proxyUrl",
        alias = "proxy-url",
        skip_serializing_if = "Option::is_none"
    )]
    pub proxy_url: Option<String>,
}

#[derive(Debug, Clone, PartialEq, Eq, serde::Serialize, serde::Deserialize)]
pub struct CliProxySecrets {
    #[serde(rename = "CLIPROXY_CREDENTIAL_POOLS")]
    pub credential_pools: HashMap<String, Vec<Credential>>,
}

#[derive(Debug, Clone, PartialEq, Eq, serde::Serialize, serde::Deserialize)]
pub struct CliProxyModelSource {
    pub id: String,
    #[serde(rename = "models-dev-provider", alias = "modelsDevProvider")]
    pub models_dev_provider: String,
    #[serde(rename = "credential-pool", alias = "credentialPool")]
    pub credential_pool: String,
    pub prefix: String,
    #[serde(rename = "base-url", alias = "baseUrl")]
    pub base_url: String,
    #[serde(
        rename = "models-url",
        alias = "modelsUrl",
        skip_serializing_if = "Option::is_none"
    )]
    pub models_url: Option<String>,
    #[serde(
        rename = "models-field",
        alias = "modelsField",
        skip_serializing_if = "Option::is_none"
    )]
    pub models_field: Option<String>,
}

impl From<&CliProxyModelSource> for ModelCatalogSource {
    fn from(s: &CliProxyModelSource) -> Self {
        Self {
            id: s.id.clone(),
            models_dev_provider: s.models_dev_provider.clone(),
            prefix: s.prefix.clone(),
            base_url: s.base_url.clone(),
        }
    }
}

#[derive(Debug, Clone, Default)]
pub struct CliProxyConfigSyncOptions {
    pub write_server_config: bool,
    pub cache_root: Option<PathBuf>,
    pub runtime_root: Option<PathBuf>,
    pub force_model_refresh: bool,
    pub quiet_model_refresh: bool,
}

#[must_use]
pub fn is_valid_pool_name(name: &str) -> bool {
    if name.is_empty() {
        return false;
    }
    let mut chars = name.chars();
    let Some(first) = chars.next() else {
        return false;
    };
    if !first.is_ascii_lowercase() {
        return false;
    }
    chars.all(|c| c.is_ascii_lowercase() || c.is_ascii_digit() || c == '-')
}

#[must_use]
pub fn runtime_client_api_key_path(runtime_root: &Path) -> PathBuf {
    runtime_root.join("cliproxyapi").join("client-api-key")
}

#[must_use]
pub fn runtime_model_catalog_path(runtime_root: &Path) -> PathBuf {
    runtime_root.join("model-catalog").join("catalog.json")
}

#[must_use]
pub fn legacy_model_catalog_path(cache_root: &Path) -> PathBuf {
    cache_root.join("catalog.json")
}

#[allow(clippy::too_many_lines)]
pub fn read_cli_proxy_secrets(path: &Path) -> Result<CliProxySecrets, CliProxyConfigError> {
    let content = fs::read_to_string(path)?;
    let value: serde_json::Value = json5::from_str(&content).map_err(|e| {
        CliProxyConfigError::ParseSecretsFailed(path.display().to_string(), e.to_string())
    })?;

    let root = value.as_object().ok_or_else(|| {
        CliProxyConfigError::ExpectedStructure(
            "CLIProxyAPI secrets".to_string(),
            "object".to_string(),
        )
    })?;

    let pools_val = root.get("CLIPROXY_CREDENTIAL_POOLS").ok_or_else(|| {
        CliProxyConfigError::InvalidField(
            "invalid CLIProxyAPI secrets: missing CLIPROXY_CREDENTIAL_POOLS".to_string(),
        )
    })?;

    let pools_obj = pools_val.as_object().ok_or_else(|| {
        CliProxyConfigError::ExpectedStructure(
            "CLIPROXY_CREDENTIAL_POOLS".to_string(),
            "object".to_string(),
        )
    })?;

    let mut credential_pools = HashMap::new();

    for (pool_name, creds_val) in pools_obj {
        if !is_valid_pool_name(pool_name) {
            return Err(CliProxyConfigError::InvalidPoolName(pool_name.clone()));
        }

        let creds_arr = creds_val.as_array().ok_or_else(|| {
            CliProxyConfigError::ExpectedStructure(
                format!("CLIPROXY_CREDENTIAL_POOLS[{pool_name}]"),
                "array".to_string(),
            )
        })?;

        let mut seen_keys = HashSet::new();
        let mut credentials = Vec::new();

        for (idx, cred_val) in creds_arr.iter().enumerate() {
            let label = format!("CLIPROXY_CREDENTIAL_POOLS[{pool_name}][{idx}]");
            let cred_obj = cred_val.as_object().ok_or_else(|| {
                CliProxyConfigError::ExpectedStructure(label.clone(), "object".to_string())
            })?;

            let api_key = cred_obj
                .get("apiKey")
                .or_else(|| cred_obj.get("api-key"))
                .and_then(|k| k.as_str())
                .ok_or_else(|| {
                    CliProxyConfigError::FieldValidation(
                        format!("{label}.apiKey"),
                        "expected non-empty string".to_string(),
                    )
                })?;

            if api_key.is_empty() {
                return Err(CliProxyConfigError::FieldValidation(
                    format!("{label}.apiKey"),
                    "expected non-empty string".to_string(),
                ));
            }

            if seen_keys.contains(api_key) {
                return Err(CliProxyConfigError::DuplicateApiKey(
                    pool_name.clone(),
                    api_key.to_string(),
                ));
            }
            seen_keys.insert(api_key.to_string());

            let weight = match cred_obj.get("weight") {
                Some(w) => {
                    let w_num = w.as_u64().ok_or_else(|| {
                        CliProxyConfigError::FieldValidation(
                            format!("{label}.weight"),
                            format!("expected integer from 1 to {MAX_CREDENTIAL_WEIGHT}"),
                        )
                    })?;
                    if w_num < 1 || w_num > u64::from(MAX_CREDENTIAL_WEIGHT) {
                        return Err(CliProxyConfigError::FieldValidation(
                            format!("{label}.weight"),
                            format!("expected integer from 1 to {MAX_CREDENTIAL_WEIGHT}"),
                        ));
                    }
                    Some(u32::try_from(w_num).map_err(|_| {
                        CliProxyConfigError::FieldValidation(
                            format!("{label}.weight"),
                            format!("expected integer from 1 to {MAX_CREDENTIAL_WEIGHT}"),
                        )
                    })?)
                }
                None => None,
            };

            let proxy_url = match cred_obj
                .get("proxyUrl")
                .or_else(|| cred_obj.get("proxy-url"))
            {
                Some(p) => {
                    let p_str = p.as_str().ok_or_else(|| {
                        CliProxyConfigError::FieldValidation(
                            format!("{label}.proxyUrl"),
                            "expected non-empty string".to_string(),
                        )
                    })?;
                    let normalized = validate_http_url(p_str, &format!("{label}.proxyUrl"))?;
                    Some(normalized)
                }
                None => None,
            };

            credentials.push(Credential {
                api_key: api_key.to_string(),
                weight,
                proxy_url,
            });
        }

        credential_pools.insert(pool_name.clone(), credentials);
    }

    Ok(CliProxySecrets { credential_pools })
}

fn validate_http_url(raw: &str, label: &str) -> Result<String, CliProxyConfigError> {
    let raw_trimmed = raw.trim_end_matches('/');
    if raw_trimmed.is_empty() {
        return Err(CliProxyConfigError::FieldValidation(
            label.to_string(),
            "expected non-empty string".to_string(),
        ));
    }
    let url = Url::parse(raw_trimmed).map_err(|_| {
        CliProxyConfigError::FieldValidation(label.to_string(), "expected URL".to_string())
    })?;

    if url.scheme() != "http" && url.scheme() != "https" {
        return Err(CliProxyConfigError::FieldValidation(
            label.to_string(),
            "expected HTTP(S) URL".to_string(),
        ));
    }

    if !url.username().is_empty()
        || url.password().is_some()
        || url.query().is_some()
        || url.fragment().is_some()
    {
        return Err(CliProxyConfigError::FieldValidation(
            label.to_string(),
            "expected HTTP URL without credentials, query, or fragment".to_string(),
        ));
    }

    Ok(raw_trimmed.to_string())
}

#[allow(clippy::too_many_lines)]
pub fn model_sources_from_template(
    template: &str,
) -> Result<Vec<CliProxyModelSource>, CliProxyConfigError> {
    let parsed: serde_yaml::Value = serde_yaml::from_str(template)
        .map_err(|e| CliProxyConfigError::ParseTemplateFailed(e.to_string()))?;

    let root = parsed.as_mapping().ok_or_else(|| {
        CliProxyConfigError::ExpectedStructure(
            "CLIProxyAPI template root".to_string(),
            "mapping".to_string(),
        )
    })?;

    let sources_key = serde_yaml::Value::String(MODEL_SOURCES_MARKER.to_string());
    let Some(sources_val) = root.get(&sources_key) else {
        return Ok(Vec::new());
    };

    if sources_val.is_null() {
        return Ok(Vec::new());
    }

    let sources_arr = sources_val.as_sequence().ok_or_else(|| {
        CliProxyConfigError::ExpectedStructure(
            MODEL_SOURCES_MARKER.to_string(),
            "array".to_string(),
        )
    })?;

    let mut seen_ids = HashSet::new();
    let mut seen_prefixes = HashSet::new();
    let mut sources = Vec::new();

    let allowed_fields: HashSet<&str> = [
        "id",
        "models-dev-provider",
        "modelsDevProvider",
        "credential-pool",
        "credentialPool",
        "prefix",
        "base-url",
        "baseUrl",
        "models-url",
        "modelsUrl",
        "models-field",
        "modelsField",
    ]
    .iter()
    .copied()
    .collect();

    for (idx, item) in sources_arr.iter().enumerate() {
        let label = format!("{MODEL_SOURCES_MARKER}[{idx}]");
        let item_map = item.as_mapping().ok_or_else(|| {
            CliProxyConfigError::ExpectedStructure(label.clone(), "mapping".to_string())
        })?;

        for key_val in item_map.keys() {
            if let Some(key_str) = key_val.as_str()
                && !allowed_fields.contains(key_str)
            {
                return Err(CliProxyConfigError::UnknownField(
                    label.clone(),
                    key_str.to_string(),
                ));
            }
        }

        let get_str = |k1: &str, k2: &str| -> Result<String, CliProxyConfigError> {
            let v1 = serde_yaml::Value::String(k1.to_string());
            let v2 = serde_yaml::Value::String(k2.to_string());
            let val = item_map.get(&v1).or_else(|| item_map.get(&v2));
            val.and_then(|v| v.as_str())
                .filter(|s| !s.is_empty())
                .map(ToString::to_string)
                .ok_or_else(|| {
                    CliProxyConfigError::FieldValidation(
                        format!("{label}.{k1}"),
                        "expected non-empty string".to_string(),
                    )
                })
        };

        let id = get_str("id", "id")?;
        if !is_valid_pool_name(&id) {
            return Err(CliProxyConfigError::InvalidField(format!(
                "{label}.id: {id}"
            )));
        }
        if seen_ids.contains(&id) {
            return Err(CliProxyConfigError::InvalidField(format!(
                "duplicate model source id: {id}"
            )));
        }
        seen_ids.insert(id.clone());

        let models_dev_provider = get_str("models-dev-provider", "modelsDevProvider")?;
        let credential_pool = get_str("credential-pool", "credentialPool")?;
        let prefix = get_str("prefix", "prefix")?;

        if !is_valid_pool_name(&prefix) {
            return Err(CliProxyConfigError::InvalidField(format!(
                "{label}.prefix: {prefix}"
            )));
        }
        if seen_prefixes.contains(&prefix) {
            return Err(CliProxyConfigError::InvalidField(format!(
                "duplicate model source prefix: {prefix}"
            )));
        }
        seen_prefixes.insert(prefix.clone());

        let base_url_raw = get_str("base-url", "baseUrl")?;
        let base_url = validate_http_url(&base_url_raw, &format!("{label}.base-url"))?;

        let get_opt_str = |k1: &str, k2: &str| -> Option<String> {
            let v1 = serde_yaml::Value::String(k1.to_string());
            let v2 = serde_yaml::Value::String(k2.to_string());
            item_map
                .get(&v1)
                .or_else(|| item_map.get(&v2))
                .and_then(|v| v.as_str())
                .filter(|s| !s.is_empty())
                .map(ToString::to_string)
        };

        let models_url = if let Some(m_url) = get_opt_str("models-url", "modelsUrl") {
            Some(validate_http_url(&m_url, &format!("{label}.models-url"))?)
        } else {
            None
        };

        let models_field = get_opt_str("models-field", "modelsField");

        sources.push(CliProxyModelSource {
            id,
            models_dev_provider,
            credential_pool,
            prefix,
            base_url,
            models_url,
            models_field,
        });
    }

    Ok(sources)
}

#[must_use]
pub fn qualify_model_id(prefix: &str, id: &str) -> String {
    if !prefix.is_empty() && !id.starts_with(&format!("{prefix}/")) {
        format!("{prefix}/{id}")
    } else {
        id.to_string()
    }
}

pub fn model_aliases_from_template(
    template: &str,
) -> Result<Vec<CatalogAlias>, CliProxyConfigError> {
    let parsed: serde_yaml::Value = serde_yaml::from_str(template)
        .map_err(|e| CliProxyConfigError::ParseTemplateFailed(e.to_string()))?;

    let Some(root) = parsed.as_mapping() else {
        return Ok(Vec::new());
    };

    let compat_key = serde_yaml::Value::String("openai-compatibility".to_string());
    let Some(compat_val) = root.get(&compat_key) else {
        return Ok(Vec::new());
    };

    let compat_arr = compat_val.as_sequence().ok_or_else(|| {
        CliProxyConfigError::ExpectedStructure(
            "openai-compatibility".to_string(),
            "array".to_string(),
        )
    })?;

    let mut aliases = Vec::new();
    let mut seen = HashSet::new();

    for (p_idx, raw_profile) in compat_arr.iter().enumerate() {
        let p_label = format!("openai-compatibility[{p_idx}]");
        let p_map = raw_profile.as_mapping().ok_or_else(|| {
            CliProxyConfigError::ExpectedStructure(p_label.clone(), "mapping".to_string())
        })?;

        let prefix_key = serde_yaml::Value::String("prefix".to_string());
        let prefix = p_map
            .get(&prefix_key)
            .and_then(|v| v.as_str())
            .unwrap_or("");

        let models_key = serde_yaml::Value::String("models".to_string());
        let Some(models_val) = p_map.get(&models_key) else {
            continue;
        };

        let models_arr = models_val.as_sequence().ok_or_else(|| {
            CliProxyConfigError::ExpectedStructure(format!("{p_label}.models"), "array".to_string())
        })?;

        for (m_idx, raw_model) in models_arr.iter().enumerate() {
            let m_label = format!("{p_label}.models[{m_idx}]");
            let m_map = raw_model.as_mapping().ok_or_else(|| {
                CliProxyConfigError::ExpectedStructure(m_label.clone(), "mapping".to_string())
            })?;

            let name_key = serde_yaml::Value::String("name".to_string());
            let name = m_map
                .get(&name_key)
                .and_then(|v| v.as_str())
                .filter(|s| !s.is_empty())
                .ok_or_else(|| {
                    CliProxyConfigError::FieldValidation(
                        format!("{m_label}.name"),
                        "expected non-empty string".to_string(),
                    )
                })?;

            let alias_key = serde_yaml::Value::String("alias".to_string());
            let alias = m_map
                .get(&alias_key)
                .and_then(|v| v.as_str())
                .filter(|s| !s.is_empty())
                .ok_or_else(|| {
                    CliProxyConfigError::FieldValidation(
                        format!("{m_label}.alias"),
                        "expected non-empty string".to_string(),
                    )
                })?;

            if name == alias {
                continue;
            }

            let id = qualify_model_id(prefix, alias);
            if seen.contains(&id) {
                return Err(CliProxyConfigError::DuplicateAlias(id));
            }
            seen.insert(id.clone());

            let display_key = serde_yaml::Value::String("display-name".to_string());
            let display_name = m_map
                .get(&display_key)
                .and_then(|v| v.as_str())
                .map(ToString::to_string);

            aliases.push(CatalogAlias {
                id,
                source_id: qualify_model_id(prefix, name),
                name: display_name,
            });
        }
    }

    Ok(aliases)
}

fn credential_to_yaml(cred: &Credential) -> serde_yaml::Mapping {
    let mut map = serde_yaml::Mapping::new();
    map.insert(
        serde_yaml::Value::String("api-key".to_string()),
        serde_yaml::Value::String(cred.api_key.clone()),
    );
    if let Some(weight) = cred.weight {
        map.insert(
            serde_yaml::Value::String("weight".to_string()),
            serde_yaml::Value::Number(weight.into()),
        );
    }
    if let Some(ref proxy_url) = cred.proxy_url {
        map.insert(
            serde_yaml::Value::String("proxy-url".to_string()),
            serde_yaml::Value::String(proxy_url.clone()),
        );
    }
    map
}

#[allow(clippy::too_many_lines)]
pub fn render_cli_proxy_config<S: ::std::hash::BuildHasher>(
    template: &str,
    secrets: &CliProxySecrets,
    deployment: &CliProxyDeployment,
    discovered_sources: &HashMap<String, SourceModels, S>,
) -> Result<String, CliProxyConfigError> {
    let mut parsed: serde_yaml::Value = serde_yaml::from_str(template)
        .map_err(|e| CliProxyConfigError::ParseTemplateFailed(e.to_string()))?;

    let root = parsed.as_mapping_mut().ok_or_else(|| {
        CliProxyConfigError::ExpectedStructure(
            "CLIProxyAPI template root".to_string(),
            "mapping".to_string(),
        )
    })?;

    root.insert(
        serde_yaml::Value::String("host".to_string()),
        serde_yaml::Value::String(deployment.listen.host.clone()),
    );
    root.insert(
        serde_yaml::Value::String("port".to_string()),
        serde_yaml::Value::Number(deployment.listen.port.into()),
    );

    let mut referenced_pools: HashSet<String> = HashSet::new();

    let sources_key = serde_yaml::Value::String(MODEL_SOURCES_MARKER.to_string());
    if let Some(sources_val) = root.remove(&sources_key) {
        if !sources_val.is_null() {
            let sources = model_sources_from_template(template)?;
            let mut gen_claude = Vec::new();
            let mut gen_codex = Vec::new();
            let mut gen_compat = Vec::new();

            for source in sources {
                let pool = secrets
                    .credential_pools
                    .get(&source.credential_pool)
                    .ok_or_else(|| {
                        CliProxyConfigError::MissingPool(source.credential_pool.clone())
                    })?;
                referenced_pools.insert(source.credential_pool.clone());

                let discovered = discovered_sources
                    .get(&source.id)
                    .ok_or_else(|| CliProxyConfigError::MissingSource(source.id.clone()))?;

                for (api, mappings) in &discovered.groups {
                    if mappings.is_empty() {
                        continue;
                    }

                    let models_yaml: Vec<serde_yaml::Value> = mappings
                        .iter()
                        .map(|m| {
                            let mut m_map = serde_yaml::Mapping::new();
                            m_map.insert(
                                serde_yaml::Value::String("name".to_string()),
                                serde_yaml::Value::String(m.name.clone()),
                            );
                            m_map.insert(
                                serde_yaml::Value::String("alias".to_string()),
                                serde_yaml::Value::String(m.alias.clone()),
                            );
                            serde_yaml::Value::Mapping(m_map)
                        })
                        .collect();

                    match api {
                        crate::catalog::model::CatalogApi::OpenAiCompletions => {
                            let mut profile = serde_yaml::Mapping::new();
                            profile.insert(
                                serde_yaml::Value::String("name".to_string()),
                                serde_yaml::Value::String(source.id.clone()),
                            );
                            profile.insert(
                                serde_yaml::Value::String("prefix".to_string()),
                                serde_yaml::Value::String(source.prefix.clone()),
                            );
                            profile.insert(
                                serde_yaml::Value::String("base-url".to_string()),
                                serde_yaml::Value::String(source.base_url.clone()),
                            );
                            profile.insert(
                                serde_yaml::Value::String("models".to_string()),
                                serde_yaml::Value::Sequence(models_yaml),
                            );

                            let entries: Vec<serde_yaml::Value> = pool
                                .iter()
                                .map(|c| serde_yaml::Value::Mapping(credential_to_yaml(c)))
                                .collect();

                            profile.insert(
                                serde_yaml::Value::String("api-key-entries".to_string()),
                                serde_yaml::Value::Sequence(entries),
                            );
                            gen_compat.push(serde_yaml::Value::Mapping(profile));
                        }
                        crate::catalog::model::CatalogApi::AnthropicMessages => {
                            let base_url = source
                                .base_url
                                .trim_end_matches('/')
                                .strip_suffix("/v1")
                                .unwrap_or(&source.base_url)
                                .to_string();

                            for cred in pool {
                                let mut entry = credential_to_yaml(cred);
                                entry.insert(
                                    serde_yaml::Value::String("prefix".to_string()),
                                    serde_yaml::Value::String(source.prefix.clone()),
                                );
                                entry.insert(
                                    serde_yaml::Value::String("base-url".to_string()),
                                    serde_yaml::Value::String(base_url.clone()),
                                );
                                entry.insert(
                                    serde_yaml::Value::String("models".to_string()),
                                    serde_yaml::Value::Sequence(models_yaml.clone()),
                                );
                                gen_claude.push(serde_yaml::Value::Mapping(entry));
                            }
                        }
                        crate::catalog::model::CatalogApi::OpenAiResponses => {
                            for cred in pool {
                                let mut entry = credential_to_yaml(cred);
                                entry.insert(
                                    serde_yaml::Value::String("prefix".to_string()),
                                    serde_yaml::Value::String(source.prefix.clone()),
                                );
                                entry.insert(
                                    serde_yaml::Value::String("base-url".to_string()),
                                    serde_yaml::Value::String(source.base_url.clone()),
                                );
                                entry.insert(
                                    serde_yaml::Value::String("models".to_string()),
                                    serde_yaml::Value::Sequence(models_yaml.clone()),
                                );
                                gen_codex.push(serde_yaml::Value::Mapping(entry));
                            }
                        }
                    }
                }
            }

            append_section_profiles(root, "claude-api-key", gen_claude);
            append_section_profiles(root, "codex-api-key", gen_codex);
            append_section_profiles(root, "openai-compatibility", gen_compat);
        }
    } else if !discovered_sources.is_empty() {
        return Err(CliProxyConfigError::MissingModelSources);
    }

    for section_name in NATIVE_CREDENTIAL_SECTIONS {
        let key = serde_yaml::Value::String((*section_name).to_string());
        if let Some(sec_val) = root.get_mut(&key) {
            let sec_arr = sec_val.as_sequence_mut().ok_or_else(|| {
                CliProxyConfigError::ExpectedStructure(
                    (*section_name).to_string(),
                    "array".to_string(),
                )
            })?;

            let mut expanded = Vec::new();
            for raw_prof in sec_arr.drain(..) {
                let prof_map = raw_prof.as_mapping().ok_or_else(|| {
                    CliProxyConfigError::ExpectedStructure(
                        (*section_name).to_string(),
                        "mapping".to_string(),
                    )
                })?;

                let marker_key = serde_yaml::Value::String(POOL_MARKER.to_string());
                if let Some(pool_val) = prof_map.get(&marker_key) {
                    let pool_name = pool_val.as_str().ok_or_else(|| {
                        CliProxyConfigError::FieldValidation(
                            format!("{section_name}.{POOL_MARKER}"),
                            "expected string".to_string(),
                        )
                    })?;

                    if !is_valid_pool_name(pool_name) {
                        return Err(CliProxyConfigError::InvalidPoolName(pool_name.to_string()));
                    }

                    for forbidden in ["api-key", "apiKey", "weight", "proxy-url", "proxyUrl"] {
                        if prof_map.contains_key(serde_yaml::Value::String(forbidden.to_string())) {
                            return Err(CliProxyConfigError::InvalidField(format!(
                                "{section_name}: {forbidden} is owned by its credential pool"
                            )));
                        }
                    }

                    let pool = secrets
                        .credential_pools
                        .get(pool_name)
                        .ok_or_else(|| CliProxyConfigError::MissingPool(pool_name.to_string()))?;
                    referenced_pools.insert(pool_name.to_string());

                    for cred in pool {
                        let mut entry = prof_map.clone();
                        entry.remove(&marker_key);
                        let cred_map = credential_to_yaml(cred);
                        for (k, v) in cred_map {
                            entry.insert(k, v);
                        }
                        expanded.push(serde_yaml::Value::Mapping(entry));
                    }
                } else {
                    expanded.push(raw_prof);
                }
            }
            *sec_arr = expanded;
        }
    }

    let compat_key = serde_yaml::Value::String("openai-compatibility".to_string());
    if let Some(compat_val) = root.get_mut(&compat_key) {
        let compat_arr = compat_val.as_sequence_mut().ok_or_else(|| {
            CliProxyConfigError::ExpectedStructure(
                "openai-compatibility".to_string(),
                "array".to_string(),
            )
        })?;

        let mut expanded = Vec::new();
        for raw_prof in compat_arr.drain(..) {
            let prof_map = raw_prof.as_mapping().ok_or_else(|| {
                CliProxyConfigError::ExpectedStructure(
                    "openai-compatibility".to_string(),
                    "mapping".to_string(),
                )
            })?;

            let marker_key = serde_yaml::Value::String(POOL_MARKER.to_string());
            if let Some(pool_val) = prof_map.get(&marker_key) {
                let pool_name = pool_val.as_str().ok_or_else(|| {
                    CliProxyConfigError::FieldValidation(
                        format!("openai-compatibility.{POOL_MARKER}"),
                        "expected string".to_string(),
                    )
                })?;

                if !is_valid_pool_name(pool_name) {
                    return Err(CliProxyConfigError::InvalidPoolName(pool_name.to_string()));
                }

                for forbidden in [
                    "api-key",
                    "apiKey",
                    "weight",
                    "proxy-url",
                    "proxyUrl",
                    "api-key-entries",
                ] {
                    if prof_map.contains_key(serde_yaml::Value::String(forbidden.to_string())) {
                        return Err(CliProxyConfigError::InvalidField(format!(
                            "openai-compatibility: {forbidden} is owned by its credential pool"
                        )));
                    }
                }

                let pool = secrets
                    .credential_pools
                    .get(pool_name)
                    .ok_or_else(|| CliProxyConfigError::MissingPool(pool_name.to_string()))?;
                referenced_pools.insert(pool_name.to_string());

                let mut entry = prof_map.clone();
                entry.remove(&marker_key);

                let entries: Vec<serde_yaml::Value> = pool
                    .iter()
                    .map(|c| serde_yaml::Value::Mapping(credential_to_yaml(c)))
                    .collect();

                entry.insert(
                    serde_yaml::Value::String("api-key-entries".to_string()),
                    serde_yaml::Value::Sequence(entries),
                );
                expanded.push(serde_yaml::Value::Mapping(entry));
            } else {
                expanded.push(raw_prof);
            }
        }
        *compat_arr = expanded;
    }

    let mut unreferenced: Vec<String> = secrets
        .credential_pools
        .keys()
        .filter(|k| !referenced_pools.contains(*k))
        .cloned()
        .collect();
    unreferenced.sort();

    if !unreferenced.is_empty() {
        return Err(CliProxyConfigError::UnreferencedPools(
            unreferenced.join(", "),
        ));
    }

    let mut out = serde_yaml::to_string(&parsed)?;
    if !out.ends_with('\n') {
        out.push('\n');
    }
    Ok(out)
}

fn append_section_profiles(
    root: &mut serde_yaml::Mapping,
    section: &str,
    profiles: Vec<serde_yaml::Value>,
) {
    if profiles.is_empty() {
        return;
    }
    let key = serde_yaml::Value::String(section.to_string());
    if let Some(sec_val) = root.get_mut(&key) {
        if let Some(sec_arr) = sec_val.as_sequence_mut() {
            sec_arr.extend(profiles);
        }
    } else {
        root.insert(key, serde_yaml::Value::Sequence(profiles));
    }
}

fn fetch_catalog_request(
    request: &CachedJsonRequest,
    options: &CliProxyConfigSyncOptions,
    fetcher: Option<&dyn CatalogFetcher>,
    now_fn: Option<&dyn Fn() -> i64>,
) -> Result<CachedJsonResult, CliProxyConfigError> {
    let result = fetch_cached_json(request, fetcher, now_fn)?;
    if result.source == CacheSource::Stale && !options.quiet_model_refresh {
        eprintln!(
            "sync: warning: model catalog refresh failed; using stale cache for {}",
            request.url
        );
    }
    Ok(result)
}

#[allow(clippy::too_many_lines)]
pub fn sync_cli_proxy_config(
    src: &Path,
    dst: &Path,
    secrets_path: &Path,
    deployment: &CliProxyDeployment,
    options: &CliProxyConfigSyncOptions,
    fetcher: Option<&dyn CatalogFetcher>,
    now_fn: Option<&dyn Fn() -> i64>,
) -> Result<(), CliProxyConfigError> {
    let template = fs::read_to_string(src)?;
    let secrets = read_cli_proxy_secrets(secrets_path)?;

    if let Some(ref runtime_root) = options.runtime_root {
        let key_path = runtime_client_api_key_path(runtime_root);
        let _ = fs::remove_file(key_path);
    }

    let sources = model_sources_from_template(&template)?;
    let aliases = model_aliases_from_template(&template)?;

    let cache_root = options.cache_root.as_deref().ok_or_else(|| {
        CliProxyConfigError::MissingRequirement("missing model catalog cache root".to_string())
    })?;

    let (discovered_map, models_dev) = if sources.is_empty() {
        (HashMap::new(), None)
    } else {
        let models_dev_request = CachedJsonRequest {
            url: MODELS_DEV_URL.to_string(),
            cache_path: cache_root.join("models-dev.json"),
            ttl_ms: MODELS_DEV_TTL_MS,
            force: options.force_model_refresh,
            allow_stale_on_error: !options.force_model_refresh,
            headers: HashMap::new(),
        };
        let models_dev_response =
            fetch_catalog_request(&models_dev_request, options, fetcher, now_fn)?;

        let mut discovered = HashMap::new();

        for source in &sources {
            let pool = secrets
                .credential_pools
                .get(&source.credential_pool)
                .ok_or_else(|| CliProxyConfigError::MissingPool(source.credential_pool.clone()))?;

            let first_cred = pool.first().ok_or_else(|| {
                CliProxyConfigError::MissingPool(format!("empty pool {}", source.credential_pool))
            })?;

            let url = source
                .models_url
                .clone()
                .unwrap_or_else(|| format!("{}/models", source.base_url.trim_end_matches('/')));

            let mut headers = HashMap::new();
            headers.insert(
                "Authorization".to_string(),
                format!("Bearer {}", first_cred.api_key),
            );

            let req = CachedJsonRequest {
                url,
                cache_path: cache_root.join(format!("source-{}.json", source.id)),
                ttl_ms: UPSTREAM_MODELS_TTL_MS,
                force: options.force_model_refresh,
                allow_stale_on_error: !options.force_model_refresh,
                headers,
            };

            let res = fetch_catalog_request(&req, options, fetcher, now_fn)?;
            let src_models =
                models_for_source(&source.into(), &res.payload, &models_dev_response.payload)?;
            if options.force_model_refresh
                && !options.quiet_model_refresh
                && !src_models.unsupported.is_empty()
            {
                let mut unsupported: Vec<String> = src_models
                    .unsupported
                    .iter()
                    .map(|model| model.npm.clone().unwrap_or_else(|| model.id.clone()))
                    .collect();
                unsupported.sort_unstable();
                unsupported.dedup();
                eprintln!(
                    "sync: warning: unsupported models for {}: {}",
                    source.id,
                    unsupported.join(", ")
                );
            }
            discovered.insert(source.id.clone(), src_models);
        }

        (discovered, Some(models_dev_response.payload))
    };

    let rendered = render_cli_proxy_config(&template, &secrets, deployment, &discovered_map)?;

    if options.write_server_config {
        if let Some(parent) = dst.parent() {
            fs::create_dir_all(parent)?;
        }
        sync_private_text_file(dst, &rendered)?;
    }

    if !sources.is_empty() {
        let runtime_root = options.runtime_root.as_deref().ok_or_else(|| {
            CliProxyConfigError::MissingRequirement("missing agents runtime root".to_string())
        })?;

        let mut external_models = Vec::new();
        for sm in discovered_map.values() {
            external_models.extend(sm.models.clone());
        }

        let gateway_request = CachedJsonRequest {
            url: cli_proxy_models_url(deployment),
            cache_path: cache_root.join("gateway.json"),
            ttl_ms: GATEWAY_MODELS_TTL_MS,
            force: options.force_model_refresh,
            allow_stale_on_error: !options.force_model_refresh,
            headers: HashMap::new(),
        };
        let gateway_response =
            match fetch_catalog_request(&gateway_request, options, fetcher, now_fn) {
                Ok(response) => Some(response),
                Err(error) if options.force_model_refresh => return Err(error),
                Err(_) => None,
            };

        let rich_request = CachedJsonRequest {
            url: cli_proxy_rich_models_url(deployment),
            cache_path: cache_root.join("gateway-rich.json"),
            ttl_ms: GATEWAY_MODELS_TTL_MS,
            force: options.force_model_refresh,
            allow_stale_on_error: !options.force_model_refresh,
            headers: HashMap::new(),
        };
        let rich_response = match fetch_catalog_request(&rich_request, options, fetcher, now_fn) {
            Ok(response) => Some(response),
            Err(error) if options.force_model_refresh => return Err(error),
            Err(_) => None,
        };

        let gateway_payload = gateway_response
            .as_ref()
            .map_or_else(|| serde_json::json!({ "data": [] }), |r| r.payload.clone());

        let options_gateway = GatewayCatalogOptions {
            aliases,
            models_dev,
            managed_prefixes: sources.iter().map(|s| s.prefix.clone()).collect(),
            rich_gateway_payload: rich_response.map(|r| r.payload),
        };

        let enriched = enrich_gateway_models(&external_models, &gateway_payload, &options_gateway)?;
        write_model_catalog(&runtime_model_catalog_path(runtime_root), &enriched)?;

        let legacy_path = legacy_model_catalog_path(cache_root);
        let _ = fs::remove_file(legacy_path);
    }

    Ok(())
}

pub fn sync_client_model_catalog(
    src: &Path,
    deployment: &CliProxyDeployment,
    options: &CliProxyConfigSyncOptions,
    fetcher: Option<&dyn CatalogFetcher>,
    now_fn: Option<&dyn Fn() -> i64>,
) -> Result<(), CliProxyConfigError> {
    let template = fs::read_to_string(src)?;
    let sources = model_sources_from_template(&template)?;
    let aliases = model_aliases_from_template(&template)?;

    let cache_root = options.cache_root.as_deref().ok_or_else(|| {
        CliProxyConfigError::MissingRequirement("missing model catalog cache root".to_string())
    })?;
    let runtime_root = options.runtime_root.as_deref().ok_or_else(|| {
        CliProxyConfigError::MissingRequirement("missing agents runtime root".to_string())
    })?;

    let _ = fs::remove_file(runtime_client_api_key_path(runtime_root));

    let models_dev_request = CachedJsonRequest {
        url: MODELS_DEV_URL.to_string(),
        cache_path: cache_root.join("models-dev.json"),
        ttl_ms: MODELS_DEV_TTL_MS,
        force: options.force_model_refresh,
        allow_stale_on_error: !options.force_model_refresh,
        headers: HashMap::new(),
    };
    let models_dev_response = fetch_catalog_request(&models_dev_request, options, fetcher, now_fn)?;

    let gateway_request = CachedJsonRequest {
        url: cli_proxy_models_url(deployment),
        cache_path: cache_root.join("gateway.json"),
        ttl_ms: GATEWAY_MODELS_TTL_MS,
        force: options.force_model_refresh,
        allow_stale_on_error: !options.force_model_refresh,
        headers: HashMap::new(),
    };
    let gateway_response = fetch_catalog_request(&gateway_request, options, fetcher, now_fn)?;

    let rich_request = CachedJsonRequest {
        url: cli_proxy_rich_models_url(deployment),
        cache_path: cache_root.join("gateway-rich.json"),
        ttl_ms: GATEWAY_MODELS_TTL_MS,
        force: options.force_model_refresh,
        allow_stale_on_error: !options.force_model_refresh,
        headers: HashMap::new(),
    };
    let rich_response = fetch_catalog_request(&rich_request, options, fetcher, now_fn)?;

    let gateway_rows = open_ai_data_rows(&gateway_response.payload, "CLIProxyAPI model catalog")?;

    let mut external_models = Vec::new();
    for source in &sources {
        let prefix = format!("{}/", source.prefix);
        let mut rows = Vec::new();

        for row in &gateway_rows {
            if let Some(id) = row.get("id").and_then(|i| i.as_str())
                && let Some(stripped) = id.strip_prefix(&prefix)
            {
                let mut cloned = (*row).clone();
                if let Some(obj) = cloned.as_object_mut() {
                    obj.insert(
                        "id".to_string(),
                        serde_json::Value::String(stripped.to_string()),
                    );
                }
                rows.push(cloned);
            }
        }

        if rows.is_empty() {
            continue;
        }

        let payload = serde_json::json!({ "data": rows });
        let sm = models_for_source(&source.into(), &payload, &models_dev_response.payload)?;
        external_models.extend(sm.models);
    }

    let options_gateway = GatewayCatalogOptions {
        aliases,
        models_dev: Some(models_dev_response.payload),
        managed_prefixes: sources.iter().map(|s| s.prefix.clone()).collect(),
        rich_gateway_payload: Some(rich_response.payload),
    };

    let enriched = enrich_gateway_models(
        &external_models,
        &gateway_response.payload,
        &options_gateway,
    )?;
    write_model_catalog(&runtime_model_catalog_path(runtime_root), &enriched)?;

    let legacy_path = legacy_model_catalog_path(cache_root);
    let _ = fs::remove_file(legacy_path);

    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::catalog::cache::HttpFetchResponse;
    use crate::cliproxy::deployment::{CliProxyClient, CliProxyListen, CliProxyServer};
    use serde_json::json;
    use std::sync::Mutex;
    use std::sync::atomic::{AtomicUsize, Ordering};
    use tempfile::tempdir;

    fn test_deployment() -> CliProxyDeployment {
        CliProxyDeployment {
            server: CliProxyServer {
                hostname: "test-gateway".to_string(),
            },
            listen: CliProxyListen {
                host: "100.64.0.42".to_string(),
                port: 9443,
            },
            client: CliProxyClient {
                base_url: "https://gateway.example.test:9443/v1".to_string(),
            },
        }
    }

    fn test_secrets() -> CliProxySecrets {
        let mut credential_pools = HashMap::new();
        credential_pools.insert(
            "example".to_string(),
            vec![
                Credential {
                    api_key: "one".to_string(),
                    weight: Some(1),
                    proxy_url: None,
                },
                Credential {
                    api_key: "two".to_string(),
                    weight: Some(2),
                    proxy_url: None,
                },
            ],
        );
        CliProxySecrets { credential_pools }
    }

    type MockResponder = Box<dyn Fn(&str) -> Result<HttpFetchResponse, String> + Send + Sync>;

    struct MockFetcher {
        responder: MockResponder,
        calls: Mutex<Vec<String>>,
        call_count: AtomicUsize,
    }

    impl MockFetcher {
        fn new(
            responder: impl Fn(&str) -> Result<HttpFetchResponse, String> + Send + Sync + 'static,
        ) -> Self {
            Self {
                responder: Box::new(responder),
                calls: Mutex::new(Vec::new()),
                call_count: AtomicUsize::new(0),
            }
        }
    }

    impl CatalogFetcher for MockFetcher {
        fn fetch(
            &self,
            url: &str,
            _headers: &HashMap<String, String>,
            _timeout: std::time::Duration,
        ) -> Result<HttpFetchResponse, String> {
            self.call_count.fetch_add(1, Ordering::SeqCst);
            if let Ok(mut c) = self.calls.lock() {
                c.push(url.to_string());
            }
            (self.responder)(url)
        }
    }

    #[test]
    fn parse_secrets_validates_pool_names_and_weights() {
        let dir = tempdir().unwrap();
        let path = dir.path().join("secrets.json");

        fs::write(
            &path,
            json!({
                "CLIPROXY_CREDENTIAL_POOLS": {
                    "valid-pool-1": [
                        { "apiKey": "k1", "weight": 100 },
                        { "apiKey": "k2", "proxyUrl": "https://proxy.test" }
                    ]
                }
            })
            .to_string(),
        )
        .unwrap();

        let secrets = read_cli_proxy_secrets(&path).unwrap();
        assert_eq!(secrets.credential_pools.len(), 1);
        let creds = &secrets.credential_pools["valid-pool-1"];
        assert_eq!(creds.len(), 2);
        assert_eq!(creds[0].api_key, "k1");
        assert_eq!(creds[0].weight, Some(100));
        assert_eq!(creds[1].proxy_url, Some("https://proxy.test".to_string()));

        // Invalid pool name
        fs::write(
            &path,
            json!({
                "CLIPROXY_CREDENTIAL_POOLS": {
                    "INVALID_NAME": [{ "apiKey": "k1" }]
                }
            })
            .to_string(),
        )
        .unwrap();
        assert!(read_cli_proxy_secrets(&path).is_err());

        // Duplicate API keys in pool
        fs::write(
            &path,
            json!({
                "CLIPROXY_CREDENTIAL_POOLS": {
                    "pool": [
                        { "apiKey": "dup" },
                        { "apiKey": "dup" }
                    ]
                }
            })
            .to_string(),
        )
        .unwrap();
        assert!(read_cli_proxy_secrets(&path).is_err());
    }

    #[test]
    fn model_sources_and_aliases_from_template() {
        let template = "
x-model-sources:
  - id: command-code
    models-dev-provider: openrouter
    credential-pool: command-code
    prefix: cmd
    base-url: https://api.commandcode.ai/provider/v1
openai-compatibility:
  - name: example-custom
    prefix: example
    models:
      - name: responses-next
        alias: nnn-responses-next-high
        display-name: \"[nnn] Responses Next (High)\"
      - name: unchanged
        alias: unchanged
";

        let sources = model_sources_from_template(template).unwrap();
        assert_eq!(sources.len(), 1);
        assert_eq!(sources[0].id, "command-code");
        assert_eq!(sources[0].prefix, "cmd");

        let aliases = model_aliases_from_template(template).unwrap();
        assert_eq!(aliases.len(), 1);
        assert_eq!(aliases[0].id, "example/nnn-responses-next-high");
        assert_eq!(aliases[0].source_id, "example/responses-next");
        assert_eq!(
            aliases[0].name,
            Some("[nnn] Responses Next (High)".to_string())
        );
    }

    #[test]
    fn cliproxy_renderer_synthesizes_protocol_profiles_from_model_sources() {
        let source = ModelCatalogSource {
            id: "example".to_string(),
            models_dev_provider: "example".to_string(),
            prefix: "example".to_string(),
            base_url: "https://example.test/v1".to_string(),
        };

        let discovered = models_for_source(
            &source,
            &json!({
                "data": [{ "id": "chat-next" }, { "id": "responses-next" }, { "id": "claude-next" }]
            }),
            &json!({
                "example": {
                    "npm": "@ai-sdk/openai-compatible",
                    "models": {
                        "chat-next": { "name": "Chat Next" },
                        "responses-next": {
                            "name": "Responses Next",
                            "provider": { "npm": "@ai-sdk/openai" }
                        },
                        "claude-next": {
                            "name": "Claude Next",
                            "provider": { "npm": "@ai-sdk/anthropic" }
                        }
                    }
                }
            }),
        )
        .unwrap();

        let mut discovered_map = HashMap::new();
        discovered_map.insert("example".to_string(), discovered);

        let template = "
remote-management:
  allow-remote: true
x-model-sources:
  - id: example
    models-dev-provider: example
    credential-pool: example
    prefix: example
    base-url: https://example.test/v1
";

        let rendered = render_cli_proxy_config(
            template,
            &test_secrets(),
            &test_deployment(),
            &discovered_map,
        )
        .unwrap();

        let parsed: serde_yaml::Value = serde_yaml::from_str(&rendered).unwrap();
        let obj = parsed.as_mapping().unwrap();

        assert!(!obj.contains_key(serde_yaml::Value::String("x-model-sources".to_string())));

        let compat = obj
            .get(serde_yaml::Value::String(
                "openai-compatibility".to_string(),
            ))
            .unwrap()
            .as_sequence()
            .unwrap();
        assert_eq!(compat.len(), 1);

        let codex = obj
            .get(serde_yaml::Value::String("codex-api-key".to_string()))
            .unwrap()
            .as_sequence()
            .unwrap();
        assert_eq!(codex.len(), 2);

        let claude = obj
            .get(serde_yaml::Value::String("claude-api-key".to_string()))
            .unwrap()
            .as_sequence()
            .unwrap();
        assert_eq!(claude.len(), 2);
    }

    #[test]
    #[allow(clippy::too_many_lines)]
    fn cliproxy_sync_discovers_and_writes_config_and_catalog() {
        let dir = tempdir().unwrap();
        let src = dir.path().join("config.yaml.tmpl");
        let dst = dir.path().join("runtime").join("config.yaml");
        let secrets_path = dir.path().join("secrets.json");
        let cache_root = dir.path().join("cache");
        let runtime_root = dir.path().join("data");

        fs::create_dir_all(dir.path().join("runtime")).unwrap();
        fs::create_dir_all(&cache_root).unwrap();
        fs::create_dir_all(&runtime_root).unwrap();

        fs::write(legacy_model_catalog_path(&cache_root), "legacy catalog\n").unwrap();

        fs::write(
            &src,
            "
host: ${CLIPROXY_LISTEN_HOST}
port: ${CLIPROXY_LISTEN_PORT}
tls:
  enable: false
remote-management:
  allow-remote: true
x-model-sources:
  - id: example
    models-dev-provider: example
    credential-pool: example
    prefix: example
    base-url: https://example.test/v1
",
        )
        .unwrap();

        fs::write(
            &secrets_path,
            json!({
                "CLIPROXY_CREDENTIAL_POOLS": {
                    "example": [{ "apiKey": "upstream", "weight": 1 }]
                }
            })
            .to_string(),
        )
        .unwrap();

        let fetcher = MockFetcher::new(|url| {
            if url == "https://models.dev/api.json" {
                return Ok(HttpFetchResponse {
                    status: 200,
                    etag: None,
                    payload: json!({
                        "example": {
                            "npm": "@ai-sdk/openai-compatible",
                            "models": { "chat-next": { "name": "Chat Next" } }
                        }
                    }),
                });
            }
            if url == "https://example.test/v1/models" {
                return Ok(HttpFetchResponse {
                    status: 200,
                    etag: None,
                    payload: json!({ "data": [{ "id": "chat-next" }] }),
                });
            }
            if url == "https://gateway.example.test:9443/v1/models" {
                return Ok(HttpFetchResponse {
                    status: 200,
                    etag: None,
                    payload: json!({ "data": [{ "id": "oauth-next", "owned_by": "example-oauth" }] }),
                });
            }
            if url == "https://gateway.example.test:9443/v1/models?client_version=0.144.1" {
                return Ok(HttpFetchResponse {
                    status: 200,
                    etag: None,
                    payload: json!({
                        "models": [{
                            "slug": "example/chat-next",
                            "display_name": "Chat Next Live",
                            "context_window": 256_000,
                            "input_modalities": ["text"],
                            "supported_reasoning_levels": [{ "effort": "low" }, { "effort": "high" }]
                        }]
                    }),
                });
            }
            Err("not found".to_string())
        });

        let options = CliProxyConfigSyncOptions {
            write_server_config: true,
            cache_root: Some(cache_root.clone()),
            runtime_root: Some(runtime_root.clone()),
            force_model_refresh: true,
            quiet_model_refresh: false,
        };

        sync_cli_proxy_config(
            &src,
            &dst,
            &secrets_path,
            &test_deployment(),
            &options,
            Some(&fetcher),
            Some(&|| 1000),
        )
        .unwrap();

        assert_eq!(fetcher.call_count.load(Ordering::SeqCst), 4);
        assert!(dst.exists());
        assert!(runtime_model_catalog_path(&runtime_root).exists());
        assert!(!legacy_model_catalog_path(&cache_root).exists());

        let catalog_content =
            fs::read_to_string(runtime_model_catalog_path(&runtime_root)).unwrap();
        let cat_json: serde_json::Value = serde_json::from_str(&catalog_content).unwrap();
        let ids: Vec<&str> = cat_json["models"]
            .as_array()
            .unwrap()
            .iter()
            .map(|m| m["id"].as_str().unwrap())
            .collect();
        assert_eq!(ids, vec!["example/chat-next", "oauth-next"]);
    }
}
