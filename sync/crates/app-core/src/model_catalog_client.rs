use std::collections::{BTreeMap, HashMap};
use std::fs;
use std::path::{Path, PathBuf};
use std::time::Duration;
use thiserror::Error;
use url::Url;

use crate::catalog::model::{CatalogCost, InputModality};

pub const CATALOG_VERSION: u32 = 1;
pub const DEFAULT_LIVE_MODELS_TIMEOUT: Duration = Duration::from_millis(2_000);

#[derive(Debug, Error)]
pub enum CatalogClientError {
    #[error("read model catalog {0}: {1}")]
    ReadFailed(String, String),

    #[error("invalid model catalog {0}")]
    InvalidCatalog(String),

    #[error("invalid {0}")]
    InvalidField(String),

    #[error("invalid {0}: expected {1}")]
    ExpectedStructure(String, String),

    #[error("invalid CLIProxyAPI base URL: {0}")]
    InvalidBaseUrl(String),

    #[error("duplicate live CLIProxyAPI model id: {0}")]
    DuplicateLiveId(String),

    #[error("live CLIProxyAPI model catalog has no text models")]
    NoTextModels,

    #[error("resolve live CLIProxyAPI model catalog {0}: {1}")]
    ResolveFailed(String, String),

    #[error("fetch live CLIProxyAPI models: HTTP {0}")]
    Http(u16),

    #[error("I/O error: {0}")]
    Io(#[from] std::io::Error),

    #[error("JSON error: {0}")]
    Json(#[from] serde_json::Error),
}

#[derive(Debug, Clone, PartialEq, serde::Serialize, serde::Deserialize)]
pub struct RuntimeCatalogModel {
    pub id: String,
    pub name: String,
    pub reasoning: bool,
    #[serde(rename = "reasoningEfforts", skip_serializing_if = "Option::is_none")]
    pub reasoning_efforts: Option<Vec<String>>,
    #[serde(
        rename = "defaultReasoningEffort",
        skip_serializing_if = "Option::is_none"
    )]
    pub default_reasoning_effort: Option<String>,
    pub input: Vec<InputModality>,
    pub cost: CatalogCost,
    #[serde(rename = "contextWindow")]
    pub context_window: u64,
    #[serde(rename = "maxTokens")]
    pub max_tokens: u64,
}

#[derive(Debug, Clone)]
pub struct LiveModelCatalogOptions {
    pub catalog_path: PathBuf,
    pub base_url: String,
    pub timeout: Option<Duration>,
}

pub trait LiveCatalogFetcher: Send + Sync {
    fn fetch_json(&self, url: &str, timeout: Duration) -> Result<serde_json::Value, String>;
}

pub struct ReqwestLiveCatalogFetcher {
    client: reqwest::Client,
}

impl Default for ReqwestLiveCatalogFetcher {
    fn default() -> Self {
        Self::new()
    }
}

impl ReqwestLiveCatalogFetcher {
    #[must_use]
    pub fn new() -> Self {
        Self {
            client: reqwest::Client::builder().build().unwrap_or_default(),
        }
    }
}
impl LiveCatalogFetcher for ReqwestLiveCatalogFetcher {
    fn fetch_json(&self, url: &str, timeout: Duration) -> Result<serde_json::Value, String> {
        let client = self.client.clone();
        let url = url.to_owned();
        std::thread::spawn(move || {
            let rt = tokio::runtime::Builder::new_current_thread()
                .enable_all()
                .build()
                .map_err(|e| e.to_string())?;

            rt.block_on(async move {
                let res = client
                    .get(url)
                    .header("Accept", "application/json")
                    .header("Cache-Control", "no-cache")
                    .timeout(timeout)
                    .send()
                    .await
                    .map_err(|e| e.to_string())?;

                if !res.status().is_success() {
                    return Err(format!("HTTP {}", res.status()));
                }

                res.json::<serde_json::Value>()
                    .await
                    .map_err(|e| e.to_string())
            })
        })
        .join()
        .map_err(|_| "live catalog fetch thread panicked".to_owned())?
    }
}

pub fn read_model_catalog(path: &Path) -> Result<Vec<RuntimeCatalogModel>, CatalogClientError> {
    let content = fs::read_to_string(path)
        .map_err(|e| CatalogClientError::ReadFailed(path.display().to_string(), e.to_string()))?;
    parse_model_catalog(&content, &path.display().to_string())
}

pub fn parse_model_catalog(
    content: &str,
    path_label: &str,
) -> Result<Vec<RuntimeCatalogModel>, CatalogClientError> {
    let value: serde_json::Value = serde_json::from_str(content)
        .map_err(|e| CatalogClientError::ReadFailed(path_label.to_string(), e.to_string()))?;

    let root = value.as_object().ok_or_else(|| {
        CatalogClientError::ExpectedStructure(
            format!("model catalog {path_label}"),
            "object".to_string(),
        )
    })?;

    let version = root
        .get("version")
        .and_then(serde_json::Value::as_u64)
        .ok_or_else(|| CatalogClientError::InvalidCatalog(path_label.to_string()))?;

    if version != u64::from(CATALOG_VERSION) {
        return Err(CatalogClientError::InvalidCatalog(path_label.to_string()));
    }

    let models_arr = root
        .get("models")
        .and_then(|m| m.as_array())
        .ok_or_else(|| CatalogClientError::InvalidCatalog(path_label.to_string()))?;

    let mut models = Vec::with_capacity(models_arr.len());
    for (idx, item) in models_arr.iter().enumerate() {
        let label = format!("model catalog models[{idx}]");
        models.push(parse_runtime_model(item, &label)?);
    }

    Ok(models)
}

fn parse_runtime_model(
    value: &serde_json::Value,
    label: &str,
) -> Result<RuntimeCatalogModel, CatalogClientError> {
    let obj = value.as_object().ok_or_else(|| {
        CatalogClientError::ExpectedStructure(label.to_string(), "object".to_string())
    })?;

    let id = obj
        .get("id")
        .and_then(|i| i.as_str())
        .filter(|s| !s.is_empty())
        .ok_or_else(|| CatalogClientError::InvalidField(format!("{label}.id")))?
        .to_string();

    let name = obj
        .get("name")
        .and_then(|n| n.as_str())
        .filter(|s| !s.is_empty())
        .ok_or_else(|| CatalogClientError::InvalidField(format!("{label}.name")))?
        .to_string();

    let reasoning = obj
        .get("reasoning")
        .and_then(serde_json::Value::as_bool)
        .ok_or_else(|| CatalogClientError::InvalidField(format!("{label}.reasoning")))?;

    let reasoning_efforts = parse_reasoning_efforts(
        obj.get("reasoningEfforts"),
        &format!("{label}.reasoningEfforts"),
    )?
    .or_else(|| {
        parse_legacy_thinking_level_map(
            obj.get("thinkingLevelMap"),
            &format!("{label}.thinkingLevelMap"),
        )
        .ok()
        .flatten()
    });

    let default_reasoning_effort = obj
        .get("defaultReasoningEffort")
        .and_then(|d| d.as_str())
        .filter(|s| !s.is_empty())
        .map(ToString::to_string);

    let input_arr = obj
        .get("input")
        .and_then(|i| i.as_array())
        .ok_or_else(|| CatalogClientError::InvalidField(format!("{label}.input")))?;

    if input_arr.is_empty() {
        return Err(CatalogClientError::InvalidField(format!("{label}.input")));
    }

    let mut input = Vec::new();
    for inp in input_arr {
        match inp.as_str() {
            Some("text") => input.push(InputModality::Text),
            Some("image") => input.push(InputModality::Image),
            _ => return Err(CatalogClientError::InvalidField(format!("{label}.input"))),
        }
    }

    let cost_obj = obj
        .get("cost")
        .and_then(|c| c.as_object())
        .ok_or_else(|| CatalogClientError::InvalidField(format!("{label}.cost")))?;

    let get_cost = |field: &str| -> Result<f64, CatalogClientError> {
        let v = cost_obj
            .get(field)
            .and_then(serde_json::Value::as_f64)
            .ok_or_else(|| CatalogClientError::InvalidField(format!("{label}.cost.{field}")))?;
        if v.is_finite() && v >= 0.0 {
            Ok(v)
        } else {
            Err(CatalogClientError::InvalidField(format!(
                "{label}.cost.{field}"
            )))
        }
    };

    let cost = CatalogCost {
        input: get_cost("input")?,
        output: get_cost("output")?,
        cache_read: get_cost("cacheRead")?,
        cache_write: get_cost("cacheWrite")?,
    };

    let context_window = obj
        .get("contextWindow")
        .and_then(serde_json::Value::as_u64)
        .filter(|&w| w > 0)
        .ok_or_else(|| CatalogClientError::InvalidField(format!("{label}.contextWindow")))?;

    let max_tokens = obj
        .get("maxTokens")
        .and_then(serde_json::Value::as_u64)
        .filter(|&t| t > 0)
        .ok_or_else(|| CatalogClientError::InvalidField(format!("{label}.maxTokens")))?;

    Ok(RuntimeCatalogModel {
        id,
        name,
        reasoning,
        reasoning_efforts,
        default_reasoning_effort,
        input,
        cost,
        context_window,
        max_tokens,
    })
}

fn parse_reasoning_efforts(
    value: Option<&serde_json::Value>,
    label: &str,
) -> Result<Option<Vec<String>>, CatalogClientError> {
    let Some(val) = value else { return Ok(None) };
    let arr = val
        .as_array()
        .ok_or_else(|| CatalogClientError::InvalidField(label.to_string()))?;

    let mut efforts = Vec::new();
    for item in arr {
        let s = item
            .as_str()
            .filter(|s| !s.is_empty())
            .ok_or_else(|| CatalogClientError::InvalidField(label.to_string()))?;
        if !efforts.contains(&s.to_string()) {
            efforts.push(s.to_string());
        }
    }

    if efforts.is_empty() {
        Ok(None)
    } else {
        Ok(Some(efforts))
    }
}

fn parse_legacy_thinking_level_map(
    value: Option<&serde_json::Value>,
    label: &str,
) -> Result<Option<Vec<String>>, CatalogClientError> {
    let Some(val) = value else { return Ok(None) };
    let obj = val
        .as_object()
        .ok_or_else(|| CatalogClientError::InvalidField(label.to_string()))?;

    let mut efforts = Vec::new();
    for (key, v) in obj {
        if v.is_null() {
            continue;
        }
        let s = v
            .as_str()
            .ok_or_else(|| CatalogClientError::InvalidField(format!("{label}.{key}")))?;
        if !s.is_empty() && !efforts.contains(&s.to_string()) {
            efforts.push(s.to_string());
        }
    }

    if efforts.is_empty() {
        Ok(None)
    } else {
        Ok(Some(efforts))
    }
}

pub fn live_models_url(base_url: &str) -> Result<String, CatalogClientError> {
    let mut url = Url::parse(base_url)
        .map_err(|_| CatalogClientError::InvalidBaseUrl(base_url.to_string()))?;
    if url.scheme() != "http" && url.scheme() != "https" {
        return Err(CatalogClientError::InvalidBaseUrl(base_url.to_string()));
    }
    let current_path = url.path().trim_end_matches('/');
    url.set_path(&format!("{current_path}/models"));
    url.set_query(Some("client_version"));
    url.set_fragment(None);
    Ok(url.to_string())
}

pub fn parse_live_model_catalog(
    value: &serde_json::Value,
    local: &[RuntimeCatalogModel],
) -> Result<Vec<RuntimeCatalogModel>, CatalogClientError> {
    let root = value.as_object().ok_or_else(|| {
        CatalogClientError::ExpectedStructure(
            "live CLIProxyAPI model catalog".to_string(),
            "object".to_string(),
        )
    })?;

    let rows = root
        .get("models")
        .and_then(|m| m.as_array())
        .ok_or_else(|| {
            CatalogClientError::InvalidField(
                "invalid live CLIProxyAPI model catalog: expected non-empty models array"
                    .to_string(),
            )
        })?;

    if rows.is_empty() {
        return Err(CatalogClientError::InvalidField(
            "invalid live CLIProxyAPI model catalog: expected non-empty models array".to_string(),
        ));
    }

    let local_by_id: HashMap<&str, &RuntimeCatalogModel> =
        local.iter().map(|m| (m.id.as_str(), m)).collect();

    let mut models_by_id: BTreeMap<String, RuntimeCatalogModel> = BTreeMap::new();

    for (index, entry) in rows.iter().enumerate() {
        let label = format!("live CLIProxyAPI model catalog.models[{index}]");
        let Some(model) = parse_single_live_model(entry, &label, &local_by_id)? else {
            continue;
        };

        if models_by_id.contains_key(&model.id) {
            return Err(CatalogClientError::DuplicateLiveId(model.id));
        }
        models_by_id.insert(model.id.clone(), model);
    }

    if models_by_id.is_empty() {
        return Err(CatalogClientError::NoTextModels);
    }

    Ok(models_by_id.into_values().collect())
}

#[allow(clippy::too_many_lines)]
fn parse_single_live_model(
    value: &serde_json::Value,
    label: &str,
    local_by_id: &HashMap<&str, &RuntimeCatalogModel>,
) -> Result<Option<RuntimeCatalogModel>, CatalogClientError> {
    let obj = value.as_object().ok_or_else(|| {
        CatalogClientError::ExpectedStructure(label.to_string(), "object".to_string())
    })?;

    let id = obj
        .get("slug")
        .and_then(|s| s.as_str())
        .filter(|s| !s.is_empty())
        .ok_or_else(|| CatalogClientError::InvalidField(format!("{label}.slug")))?
        .to_string();

    let input_arr = obj
        .get("input_modalities")
        .and_then(|i| i.as_array())
        .ok_or_else(|| CatalogClientError::InvalidField(format!("{label}.input_modalities")))?;

    let mut input = Vec::new();
    for inp in input_arr {
        match inp.as_str() {
            Some("text") if !input.contains(&InputModality::Text) => {
                input.push(InputModality::Text);
            }
            Some("image") if !input.contains(&InputModality::Image) => {
                input.push(InputModality::Image);
            }
            _ => {}
        }
    }

    if !input.contains(&InputModality::Text) {
        return Ok(None);
    }

    let reasoning_efforts_val = obj.get("supported_reasoning_levels");
    let mut reasoning_efforts = Vec::new();
    if let Some(r_arr) = reasoning_efforts_val.and_then(|r| r.as_array()) {
        for (idx, r_item) in r_arr.iter().enumerate() {
            let item_obj = r_item.as_object().ok_or_else(|| {
                CatalogClientError::ExpectedStructure(
                    format!("{label}.supported_reasoning_levels[{idx}]"),
                    "object".to_string(),
                )
            })?;
            let effort = item_obj
                .get("effort")
                .and_then(|e| e.as_str())
                .filter(|s| !s.is_empty())
                .ok_or_else(|| {
                    CatalogClientError::InvalidField(format!(
                        "{label}.supported_reasoning_levels[{idx}].effort"
                    ))
                })?;
            if !reasoning_efforts.contains(&effort.to_string()) {
                reasoning_efforts.push(effort.to_string());
            }
        }
    }

    let default_reasoning_effort = obj
        .get("default_reasoning_level")
        .and_then(|d| d.as_str())
        .filter(|s| !s.is_empty())
        .map(ToString::to_string);

    if let Some(def_eff) = &default_reasoning_effort
        && !reasoning_efforts.contains(def_eff)
    {
        return Err(CatalogClientError::InvalidField(format!(
            "{label}.default_reasoning_level"
        )));
    }

    let truncation = obj
        .get("truncation_policy")
        .and_then(|t| t.as_object())
        .ok_or_else(|| {
            CatalogClientError::ExpectedStructure(
                format!("{label}.truncation_policy"),
                "object".to_string(),
            )
        })?;

    let max_tokens = truncation
        .get("limit")
        .and_then(serde_json::Value::as_u64)
        .filter(|&l| l > 0)
        .ok_or_else(|| {
            CatalogClientError::InvalidField(format!("{label}.truncation_policy.limit"))
        })?;

    let context_window = obj
        .get("context_window")
        .and_then(serde_json::Value::as_u64)
        .filter(|&c| c > 0)
        .ok_or_else(|| CatalogClientError::InvalidField(format!("{label}.context_window")))?;

    let name = obj
        .get("display_name")
        .and_then(|d| d.as_str())
        .filter(|s| !s.is_empty())
        .ok_or_else(|| CatalogClientError::InvalidField(format!("{label}.display_name")))?
        .to_string();

    let cost = local_by_id
        .get(id.as_str())
        .map_or_else(CatalogCost::default, |m| m.cost.clone());

    let reasoning = reasoning_efforts.iter().any(|e| e != "none");
    let efforts_opt = if reasoning_efforts.is_empty() {
        None
    } else {
        Some(reasoning_efforts)
    };

    Ok(Some(RuntimeCatalogModel {
        id,
        name,
        reasoning,
        reasoning_efforts: efforts_opt,
        default_reasoning_effort,
        input,
        cost,
        context_window,
        max_tokens,
    }))
}

pub fn resolve_live_model_catalog(
    options: &LiveModelCatalogOptions,
    fetcher: Option<&dyn LiveCatalogFetcher>,
) -> Result<Vec<RuntimeCatalogModel>, CatalogClientError> {
    let local = read_model_catalog(&options.catalog_path).ok();

    let default_fetcher = ReqwestLiveCatalogFetcher::new();
    let actual_fetcher = fetcher.unwrap_or(&default_fetcher);

    let url = match live_models_url(&options.base_url) {
        Ok(u) => u,
        Err(e) => {
            if let Some(loc) = local {
                return Ok(loc);
            }
            return Err(e);
        }
    };

    let timeout = options.timeout.unwrap_or(DEFAULT_LIVE_MODELS_TIMEOUT);

    match actual_fetcher.fetch_json(&url, timeout) {
        Ok(payload) => {
            let local_slice = local.as_deref().unwrap_or(&[]);
            parse_live_model_catalog(&payload, local_slice)
        }
        Err(err) => {
            if let Some(loc) = local {
                return Ok(loc);
            }
            Err(CatalogClientError::ResolveFailed(
                options.base_url.clone(),
                err,
            ))
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;
    use std::sync::Mutex;
    use std::sync::atomic::{AtomicUsize, Ordering};
    use tempfile::tempdir;

    type MockResponder = Box<dyn Fn(&str) -> Result<serde_json::Value, String> + Send + Sync>;

    struct MockLiveFetcher {
        responder: MockResponder,
        calls: Mutex<Vec<String>>,
        call_count: AtomicUsize,
    }

    impl MockLiveFetcher {
        fn new(
            responder: impl Fn(&str) -> Result<serde_json::Value, String> + Send + Sync + 'static,
        ) -> Self {
            Self {
                responder: Box::new(responder),
                calls: Mutex::new(Vec::new()),
                call_count: AtomicUsize::new(0),
            }
        }
    }

    impl LiveCatalogFetcher for MockLiveFetcher {
        fn fetch_json(&self, url: &str, _timeout: Duration) -> Result<serde_json::Value, String> {
            self.call_count.fetch_add(1, Ordering::SeqCst);
            if let Ok(mut c) = self.calls.lock() {
                c.push(url.to_string());
            }
            (self.responder)(url)
        }
    }

    fn live_model_json(
        slug: &str,
        display_name: &str,
        context_window: u64,
        max_tokens: u64,
        input: &[&str],
        efforts: &[&str],
        default_effort: Option<&str>,
    ) -> serde_json::Value {
        let eff_objs: Vec<serde_json::Value> =
            efforts.iter().map(|e| json!({ "effort": e })).collect();
        let mut obj = json!({
            "slug": slug,
            "display_name": display_name,
            "context_window": context_window,
            "input_modalities": input,
            "supported_reasoning_levels": eff_objs,
            "truncation_policy": { "limit": max_tokens, "mode": "tokens" }
        });
        if let Some(def) = default_effort {
            obj["default_reasoning_level"] = serde_json::Value::String(def.to_string());
        }
        obj
    }

    #[test]
    fn installed_runtime_model_catalog_client_validates_and_projects_catalog() {
        let dir = tempdir().unwrap();
        let path = dir.path().join("catalog.json");

        let content = json!({
            "version": 1,
            "models": [
                {
                    "id": "example/model",
                    "name": "Example",
                    "api": "openai-responses",
                    "reasoning": true,
                    "reasoningEfforts": ["low", "ultra"],
                    "defaultReasoningEffort": "low",
                    "input": ["text", "image"],
                    "cost": { "input": 1.0, "output": 2.0, "cacheRead": 0.1, "cacheWrite": 0.0 },
                    "contextWindow": 128_000,
                    "maxTokens": 32000,
                    "compat": { "ignoredByRuntimeProjection": true }
                },
                {
                    "id": "example/legacy",
                    "name": "Legacy",
                    "api": "openai-responses",
                    "reasoning": true,
                    "thinkingLevelMap": { "low": "low", "high": "high", "max": null },
                    "input": ["text"],
                    "cost": { "input": 0.0, "output": 0.0, "cacheRead": 0.0, "cacheWrite": 0.0 },
                    "contextWindow": 128_000,
                    "maxTokens": 32000
                },
                {
                    "id": "example/empty",
                    "name": "Empty",
                    "api": "openai-responses",
                    "reasoning": false,
                    "reasoningEfforts": [],
                    "input": ["text"],
                    "cost": { "input": 0.0, "output": 0.0, "cacheRead": 0.0, "cacheWrite": 0.0 },
                    "contextWindow": 128_000,
                    "maxTokens": 32000
                }
            ]
        });

        fs::write(&path, content.to_string()).unwrap();

        let expected = vec![
            RuntimeCatalogModel {
                id: "example/model".to_string(),
                name: "Example".to_string(),
                reasoning: true,
                reasoning_efforts: Some(vec!["low".to_string(), "ultra".to_string()]),
                default_reasoning_effort: Some("low".to_string()),
                input: vec![InputModality::Text, InputModality::Image],
                cost: CatalogCost {
                    input: 1.0,
                    output: 2.0,
                    cache_read: 0.1,
                    cache_write: 0.0,
                },
                context_window: 128_000,
                max_tokens: 32_000,
            },
            RuntimeCatalogModel {
                id: "example/legacy".to_string(),
                name: "Legacy".to_string(),
                reasoning: true,
                reasoning_efforts: Some(vec!["low".to_string(), "high".to_string()]),
                default_reasoning_effort: None,
                input: vec![InputModality::Text],
                cost: CatalogCost::default(),
                context_window: 128_000,
                max_tokens: 32_000,
            },
            RuntimeCatalogModel {
                id: "example/empty".to_string(),
                name: "Empty".to_string(),
                reasoning: false,
                reasoning_efforts: None,
                default_reasoning_effort: None,
                input: vec![InputModality::Text],
                cost: CatalogCost::default(),
                context_window: 128_000,
                max_tokens: 32_000,
            },
        ];

        let models = read_model_catalog(&path).unwrap();
        assert_eq!(models, expected);
    }

    #[test]
    fn installed_runtime_model_catalog_client_uses_live_metadata_with_local_cost() {
        let dir = tempdir().unwrap();
        let path = dir.path().join("catalog.json");

        let known = json!({
            "id": "cmd/known",
            "name": "Cached",
            "reasoning": false,
            "input": ["text"],
            "cost": { "input": 1.0, "output": 2.0, "cacheRead": 0.1, "cacheWrite": 0.2 },
            "contextWindow": 128_000,
            "maxTokens": 16384
        });
        let old = json!({
            "id": "old/model",
            "name": "Old",
            "reasoning": false,
            "input": ["text"],
            "cost": { "input": 0.0, "output": 0.0, "cacheRead": 0.0, "cacheWrite": 0.0 },
            "contextWindow": 128_000,
            "maxTokens": 16384
        });

        fs::write(
            &path,
            json!({ "version": 1, "models": [known, old] }).to_string(),
        )
        .unwrap();

        let fetcher = MockLiveFetcher::new(|_| {
            Ok(json!({
                "models": [
                    live_model_json(
                        "cmd/known",
                        "Live Known",
                        1_000_000,
                        64_000,
                        &["text", "image"],
                        &["low", "high"],
                        Some("low"),
                    ),
                    live_model_json(
                        "cmd/new",
                        "Live New",
                        256_000,
                        32_000,
                        &["text"],
                        &["high", "max"],
                        Some("high"),
                    ),
                ]
            }))
        });

        let options = LiveModelCatalogOptions {
            catalog_path: path,
            base_url: "https://gateway.example.test/v1".to_string(),
            timeout: None,
        };

        let resolved = resolve_live_model_catalog(&options, Some(&fetcher)).unwrap();

        assert_eq!(resolved.len(), 2);
        assert_eq!(resolved[0].id, "cmd/known");
        assert_eq!(resolved[0].name, "Live Known");
        assert!(resolved[0].reasoning);
        assert_eq!(
            resolved[0].reasoning_efforts,
            Some(vec!["low".to_string(), "high".to_string()])
        );
        assert_eq!(
            resolved[0].default_reasoning_effort,
            Some("low".to_string())
        );
        assert_eq!(
            resolved[0].input,
            vec![InputModality::Text, InputModality::Image]
        );
        assert_eq!(
            resolved[0].cost,
            CatalogCost {
                input: 1.0,
                output: 2.0,
                cache_read: 0.1,
                cache_write: 0.2,
            }
        );
        assert_eq!(resolved[0].context_window, 1_000_000);
        assert_eq!(resolved[0].max_tokens, 64_000);

        assert_eq!(resolved[1].id, "cmd/new");
        assert_eq!(resolved[1].name, "Live New");
        assert_eq!(resolved[1].cost, CatalogCost::default());
    }

    #[test]
    fn installed_runtime_model_catalog_client_uses_local_fallback_after_live_failure() {
        let dir = tempdir().unwrap();
        let path = dir.path().join("catalog.json");

        let local_model = json!({
            "id": "cmd/cached",
            "name": "Cached",
            "reasoning": false,
            "input": ["text"],
            "cost": { "input": 0.0, "output": 0.0, "cacheRead": 0.0, "cacheWrite": 0.0 },
            "contextWindow": 128_000,
            "maxTokens": 16384
        });

        fs::write(
            &path,
            json!({ "version": 1, "models": [local_model] }).to_string(),
        )
        .unwrap();

        let fetcher = MockLiveFetcher::new(|_| Err("gateway unavailable".to_string()));

        let options = LiveModelCatalogOptions {
            catalog_path: path,
            base_url: "https://gateway.example.test/v1".to_string(),
            timeout: None,
        };

        let resolved = resolve_live_model_catalog(&options, Some(&fetcher)).unwrap();
        assert_eq!(resolved.len(), 1);
        assert_eq!(resolved[0].id, "cmd/cached");
    }

    #[test]
    fn installed_runtime_model_catalog_client_resolves_live_models_without_local_state() {
        let dir = tempdir().unwrap();
        let path = dir.path().join("missing.json");

        let fetcher = MockLiveFetcher::new(|_| {
            Ok(json!({
                "models": [
                    live_model_json("cmd/live", "Live", 1_000_000, 64_000, &["text"], &["low"], Some("low"))
                ]
            }))
        });

        let options = LiveModelCatalogOptions {
            catalog_path: path,
            base_url: "https://gateway.example.test/v1".to_string(),
            timeout: None,
        };

        let resolved = resolve_live_model_catalog(&options, Some(&fetcher)).unwrap();
        assert_eq!(resolved.len(), 1);
        assert_eq!(resolved[0].id, "cmd/live");
        assert_eq!(resolved[0].cost, CatalogCost::default());
    }
}
