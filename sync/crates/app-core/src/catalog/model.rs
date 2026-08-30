use crate::runtime::fs::sync_private_text_file;
use std::collections::{BTreeMap, HashMap, HashSet};
use std::fs;
use std::path::Path;
use thiserror::Error;
use url::Url;

pub const MODEL_CATALOG_VERSION: u32 = 1;
pub const MODEL_CATALOG_MODE: u32 = 0o600;

#[derive(Debug, Error)]
pub enum CatalogError {
    #[error("invalid model catalog source {0}: {1}")]
    InvalidSource(String, String),

    #[error("invalid models.dev catalog: {0}")]
    InvalidModelsDev(String),

    #[error("invalid {0}: expected {1}")]
    InvalidStructure(String, String),

    #[error("invalid {0}")]
    InvalidField(String),

    #[error("duplicate model catalog id: {0}")]
    DuplicateId(String),

    #[error("read model catalog {0}: {1}")]
    ReadFailed(String, String),

    #[error("I/O error: {0}")]
    Io(#[from] std::io::Error),

    #[error("JSON error: {0}")]
    Json(#[from] serde_json::Error),
}

#[derive(
    Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash, serde::Serialize, serde::Deserialize,
)]
pub enum CatalogApi {
    #[serde(rename = "anthropic-messages")]
    AnthropicMessages,
    #[serde(rename = "openai-completions")]
    OpenAiCompletions,
    #[serde(rename = "openai-responses")]
    OpenAiResponses,
}

impl CatalogApi {
    #[must_use]
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::AnthropicMessages => "anthropic-messages",
            Self::OpenAiCompletions => "openai-completions",
            Self::OpenAiResponses => "openai-responses",
        }
    }
}

impl std::fmt::Display for CatalogApi {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(self.as_str())
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, serde::Serialize, serde::Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum InputModality {
    Text,
    Image,
}

#[derive(Debug, Clone, PartialEq, serde::Serialize, serde::Deserialize)]
pub struct CatalogCost {
    pub input: f64,
    pub output: f64,
    #[serde(rename = "cacheRead")]
    pub cache_read: f64,
    #[serde(rename = "cacheWrite")]
    pub cache_write: f64,
}

impl Default for CatalogCost {
    fn default() -> Self {
        Self {
            input: 0.0,
            output: 0.0,
            cache_read: 0.0,
            cache_write: 0.0,
        }
    }
}

#[derive(Debug, Clone, PartialEq, serde::Serialize, serde::Deserialize)]
pub struct CatalogModel {
    pub id: String,
    pub name: String,
    pub api: CatalogApi,
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
    #[serde(skip_serializing_if = "Option::is_none")]
    pub compat: Option<serde_json::Value>,
}

#[derive(Debug, Clone, PartialEq, Eq, serde::Serialize, serde::Deserialize)]
pub struct CliProxyThinkingLevels {
    pub levels: Vec<String>,
}

#[derive(Debug, Clone, PartialEq, Eq, serde::Serialize, serde::Deserialize)]
pub struct CliProxyModelMapping {
    pub name: String,
    pub alias: String,
    #[serde(rename = "display-name")]
    pub display_name: String,
    #[serde(rename = "max-context-length")]
    pub max_context_length: u64,
    #[serde(rename = "force-mapping")]
    pub force_mapping: bool,
    #[serde(rename = "is-compat")]
    pub is_compat: bool,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub thinking: Option<CliProxyThinkingLevels>,
}

#[derive(Debug, Clone, PartialEq, Eq, serde::Serialize, serde::Deserialize)]
pub struct UnsupportedCatalogModel {
    pub id: String,
    pub npm: Option<String>,
    pub shape: Option<String>,
}

#[derive(Debug, Clone, PartialEq, serde::Serialize, serde::Deserialize)]
pub struct SourceModels {
    pub groups: BTreeMap<CatalogApi, Vec<CliProxyModelMapping>>,
    pub models: Vec<CatalogModel>,
    pub unsupported: Vec<UnsupportedCatalogModel>,
}

#[derive(Debug, Clone, PartialEq, Eq, serde::Serialize, serde::Deserialize)]
pub struct ModelCatalogSource {
    pub id: String,
    #[serde(rename = "modelsDevProvider", alias = "models-dev-provider")]
    pub models_dev_provider: String,
    pub prefix: String,
    #[serde(rename = "baseUrl", alias = "base-url")]
    pub base_url: String,
}

#[derive(Debug, Clone, PartialEq, Eq, serde::Serialize, serde::Deserialize)]
pub struct CatalogAlias {
    pub id: String,
    #[serde(rename = "sourceId", alias = "source-id")]
    pub source_id: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub name: Option<String>,
}

#[derive(Debug, Clone, Default)]
pub struct GatewayCatalogOptions {
    pub aliases: Vec<CatalogAlias>,
    pub models_dev: Option<serde_json::Value>,
    pub managed_prefixes: Vec<String>,
    pub rich_gateway_payload: Option<serde_json::Value>,
}

#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
pub struct SerializedModelCatalog {
    pub version: u32,
    pub models: Vec<CatalogModel>,
}

#[must_use]
pub fn is_generation_only_model(id: &str) -> bool {
    let lower = id.to_ascii_lowercase();
    if lower == "codex-auto-review" {
        return true;
    }
    if lower.starts_with("gpt-image-") || lower.starts_with("grok-imagine-") {
        return true;
    }

    // Pattern matching for (?:^|-)image(?:-|$) or (?:^|-)video(?:-|$)
    let contains_isolated = |target: &str| -> bool {
        for segment in lower.split('/') {
            for part in segment.split('-') {
                if part == target {
                    return true;
                }
            }
        }
        false
    };

    contains_isolated("image") || contains_isolated("video")
}

pub fn validate_source(source: &ModelCatalogSource) -> Result<(), CatalogError> {
    if source.id.is_empty() {
        return Err(CatalogError::InvalidSource(
            source.id.clone(),
            "empty id".to_string(),
        ));
    }
    if source.models_dev_provider.is_empty() {
        return Err(CatalogError::InvalidSource(
            source.id.clone(),
            "empty modelsDevProvider".to_string(),
        ));
    }
    if source.prefix.is_empty() || source.prefix.contains('/') {
        return Err(CatalogError::InvalidSource(
            source.id.clone(),
            format!("invalid model catalog prefix: {}", source.prefix),
        ));
    }
    let Ok(url) = Url::parse(&source.base_url) else {
        return Err(CatalogError::InvalidSource(
            source.id.clone(),
            format!("invalid model catalog base URL: {}", source.base_url),
        ));
    };
    if url.scheme() != "http" && url.scheme() != "https" {
        return Err(CatalogError::InvalidSource(
            source.id.clone(),
            format!("invalid model catalog base URL: {}", source.base_url),
        ));
    }
    Ok(())
}

pub fn open_ai_data_rows<'a>(
    payload: &'a serde_json::Value,
    label: &str,
) -> Result<Vec<&'a serde_json::Value>, CatalogError> {
    if let Some(obj) = payload.as_object()
        && let Some(data) = obj.get("data").and_then(|d| d.as_array())
    {
        return Ok(data.iter().collect());
    }
    Err(CatalogError::InvalidStructure(
        label.to_string(),
        "expected data array".to_string(),
    ))
}

#[must_use]
pub fn is_agent_model(metadata: Option<&serde_json::Value>, upstream: &serde_json::Value) -> bool {
    if let Some(meta) = metadata {
        if meta.get("tool_call") == Some(&serde_json::Value::Bool(false)) {
            return false;
        }
        if let Some(modalities) = meta.get("modalities").and_then(|m| m.as_object()) {
            if let Some(input) = modalities.get("input").and_then(|i| i.as_array())
                && !input.is_empty()
                && !input.iter().any(|v| v.as_str() == Some("text"))
            {
                return false;
            }
            if let Some(output) = modalities.get("output").and_then(|o| o.as_array())
                && !output.is_empty()
                && !output.iter().any(|v| v.as_str() == Some("text"))
            {
                return false;
            }
        }
    }

    if let Some(arch) = upstream.get("architecture").and_then(|a| a.as_object()) {
        if let Some(input) = arch.get("input_modalities").and_then(|i| i.as_array())
            && !input.is_empty()
            && !input.iter().any(|v| v.as_str() == Some("text"))
        {
            return false;
        }
        if let Some(output) = arch.get("output_modalities").and_then(|o| o.as_array())
            && !output.is_empty()
            && !output.iter().any(|v| v.as_str() == Some("text"))
        {
            return false;
        }
    }

    if let Some(params) = upstream
        .get("supported_parameters")
        .and_then(|p| p.as_array())
        && !params.is_empty()
    {
        return params.iter().any(|v| v.as_str() == Some("tools"));
    }

    true
}

#[must_use]
pub fn api_for_provider(npm: &str, shape: Option<&str>) -> Option<CatalogApi> {
    if shape == Some("responses") {
        return Some(CatalogApi::OpenAiResponses);
    }
    if shape == Some("completions") {
        return Some(CatalogApi::OpenAiCompletions);
    }
    match npm {
        "@ai-sdk/openai" | "@ai-sdk/azure" => Some(CatalogApi::OpenAiResponses),
        "@ai-sdk/anthropic" => Some(CatalogApi::AnthropicMessages),
        "@ai-sdk/openai-compatible" | "@openrouter/ai-sdk-provider" => {
            Some(CatalogApi::OpenAiCompletions)
        }
        _ => None,
    }
}

#[must_use]
pub fn public_alias(source: &ModelCatalogSource, id: &str) -> String {
    let repeated = format!("{}/", source.prefix);
    id.strip_prefix(&repeated).unwrap_or(id).to_string()
}

#[must_use]
pub fn unprefix_model_id(id: &str) -> &str {
    id.split_once('/').map_or(id, |(_, rest)| rest)
}

#[must_use]
pub fn positive_integer(value: Option<&serde_json::Value>) -> Option<u64> {
    let val = value?;
    if let Some(num) = val.as_u64()
        && num > 0
    {
        return Some(num);
    }
    if let Some(num) = val.as_f64()
        && num.is_finite()
        && num > 0.0
        && num.fract() == 0.0
        && num < 18_446_744_073_709_551_616.0
    {
        return format!("{num:.0}").parse::<u64>().ok().filter(|&n| n > 0);
    }
    None
}

#[must_use]
pub fn non_negative_number(value: Option<&serde_json::Value>) -> f64 {
    let Some(val) = value else { return 0.0 };
    if let Some(num) = val.as_f64()
        && num.is_finite()
        && num >= 0.0
    {
        return num;
    }
    0.0
}

#[must_use]
pub fn per_token_price_to_millions(value: Option<&serde_json::Value>) -> Option<f64> {
    let val = value?;
    let parsed: f64 = if let Some(num) = val.as_f64() {
        num
    } else {
        let s = val.as_str()?;
        s.parse::<f64>().ok()?
    };
    if parsed.is_finite() && parsed >= 0.0 {
        Some(parsed * 1_000_000.0)
    } else {
        None
    }
}

pub fn string_array(value: Option<&serde_json::Value>) -> Vec<String> {
    let Some(val) = value else { return Vec::new() };
    val.as_array().map_or_else(Vec::new, |arr| {
        arr.iter()
            .filter_map(|v| v.as_str().map(ToString::to_string))
            .collect()
    })
}

pub fn reasoning_efforts_from_value(value: Option<&serde_json::Value>) -> Option<Vec<String>> {
    let arr = value?.as_array()?;
    let mut efforts = Vec::new();
    for item in arr {
        let effort = item.as_str().map(ToString::to_string).or_else(|| {
            item.as_object()?
                .get("effort")?
                .as_str()
                .map(ToString::to_string)
        });
        if let Some(eff) = effort
            && !efforts.contains(&eff)
        {
            efforts.push(eff);
        }
    }
    if efforts.is_empty() {
        None
    } else {
        Some(efforts)
    }
}

#[must_use]
pub fn compat_for(
    metadata: Option<&serde_json::Value>,
    supported_parameters: &[String],
) -> Option<serde_json::Value> {
    let interleaved = metadata
        .and_then(|m| m.get("interleaved"))
        .and_then(|i| i.as_object());
    let reasoning_field = interleaved
        .and_then(|i| i.get("field"))
        .and_then(|f| f.as_str());

    let supports_tool_choice = supported_parameters.iter().any(|p| p == "tool_choice");

    if reasoning_field == Some("reasoning_details") {
        let mut map = serde_json::Map::new();
        map.insert(
            "thinkingFormat".to_string(),
            serde_json::Value::String("openrouter".to_string()),
        );
        if !supports_tool_choice {
            map.insert(
                "supportsToolChoice".to_string(),
                serde_json::Value::Bool(false),
            );
        }
        return Some(serde_json::Value::Object(map));
    }

    if reasoning_field == Some("reasoning_content") {
        let mut map = serde_json::Map::new();
        map.insert(
            "thinkingFormat".to_string(),
            serde_json::Value::String("deepseek".to_string()),
        );
        map.insert(
            "requiresReasoningContentOnAssistantMessages".to_string(),
            serde_json::Value::Bool(true),
        );
        if !supports_tool_choice {
            map.insert(
                "supportsToolChoice".to_string(),
                serde_json::Value::Bool(false),
            );
        }
        return Some(serde_json::Value::Object(map));
    }

    if !supported_parameters.is_empty() && !supports_tool_choice {
        let mut map = serde_json::Map::new();
        map.insert(
            "supportsToolChoice".to_string(),
            serde_json::Value::Bool(false),
        );
        return Some(serde_json::Value::Object(map));
    }

    None
}

fn normalize_model(
    source: &ModelCatalogSource,
    alias: &str,
    api: CatalogApi,
    metadata: Option<&serde_json::Value>,
    upstream: &serde_json::Value,
) -> CatalogModel {
    let limit = metadata
        .and_then(|m| m.get("limit"))
        .and_then(|l| l.as_object());

    let context_window = positive_integer(upstream.get("context_length"))
        .or_else(|| positive_integer(limit.and_then(|l| l.get("context"))))
        .unwrap_or(128_000);

    let top_provider = upstream.get("top_provider").and_then(|tp| tp.as_object());

    let max_tokens = positive_integer(upstream.get("max_completion_tokens"))
        .or_else(|| positive_integer(top_provider.and_then(|tp| tp.get("max_completion_tokens"))))
        .or_else(|| positive_integer(limit.and_then(|l| l.get("output"))))
        .unwrap_or_else(|| context_window.min(16_384));

    let mut input_modalities = Vec::new();
    if let Some(arch) = upstream.get("architecture") {
        input_modalities.extend(string_array(arch.get("input_modalities")));
    }
    if let Some(meta) = metadata
        && let Some(mods) = meta.get("modalities")
    {
        input_modalities.extend(string_array(mods.get("input")));
    }

    let input = if input_modalities.iter().any(|m| m == "image") {
        vec![InputModality::Text, InputModality::Image]
    } else {
        vec![InputModality::Text]
    };

    let pricing = upstream.get("pricing").and_then(|p| p.as_object());
    let metadata_cost = metadata
        .and_then(|m| m.get("cost"))
        .and_then(|c| c.as_object());

    let cost = CatalogCost {
        input: per_token_price_to_millions(pricing.and_then(|p| p.get("prompt")))
            .unwrap_or_else(|| non_negative_number(metadata_cost.and_then(|c| c.get("input")))),
        output: per_token_price_to_millions(pricing.and_then(|p| p.get("completion")))
            .unwrap_or_else(|| non_negative_number(metadata_cost.and_then(|c| c.get("output")))),
        cache_read: per_token_price_to_millions(pricing.and_then(|p| p.get("input_cache_read")))
            .unwrap_or_else(|| {
                non_negative_number(metadata_cost.and_then(|c| c.get("cache_read")))
            }),
        cache_write: per_token_price_to_millions(pricing.and_then(|p| p.get("input_cache_write")))
            .unwrap_or_else(|| {
                non_negative_number(metadata_cost.and_then(|c| c.get("cache_write")))
            }),
    };

    let efforts = reasoning_efforts_from_value(metadata.and_then(|m| m.get("reasoning_options")));
    let default_reasoning_effort = metadata
        .and_then(|m| m.get("default_reasoning_effort"))
        .and_then(|d| d.as_str())
        .map(ToString::to_string);

    let supported_parameters = string_array(upstream.get("supported_parameters"));

    let reasoning = metadata
        .and_then(|m| m.get("reasoning"))
        .and_then(serde_json::Value::as_bool)
        == Some(true)
        || efforts
            .as_ref()
            .is_some_and(|effs| effs.iter().any(|e| e != "none"))
        || supported_parameters.iter().any(|p| p == "reasoning")
        || supported_parameters.iter().any(|p| p == "reasoning_effort");

    let name = upstream
        .get("name")
        .and_then(|n| n.as_str())
        .or_else(|| {
            metadata
                .and_then(|m| m.get("name"))
                .and_then(|n| n.as_str())
        })
        .unwrap_or(alias)
        .to_string();

    let compat = compat_for(metadata, &supported_parameters);

    CatalogModel {
        id: format!("{}/{}", source.prefix, alias),
        name,
        api,
        reasoning,
        reasoning_efforts: efforts,
        default_reasoning_effort,
        input,
        cost,
        context_window,
        max_tokens,
        compat,
    }
}

fn mapping_for(upstream_id: &str, alias: &str, model: &CatalogModel) -> CliProxyModelMapping {
    CliProxyModelMapping {
        name: upstream_id.to_string(),
        alias: alias.to_string(),
        display_name: model.name.clone(),
        max_context_length: model.context_window,
        force_mapping: true,
        is_compat: true,
        thinking: model.reasoning_efforts.as_ref().and_then(|efforts| {
            if efforts.is_empty() {
                None
            } else {
                Some(CliProxyThinkingLevels {
                    levels: efforts.clone(),
                })
            }
        }),
    }
}

pub fn models_for_source(
    source: &ModelCatalogSource,
    upstream_payload: &serde_json::Value,
    models_dev_payload: &serde_json::Value,
) -> Result<SourceModels, CatalogError> {
    validate_source(source)?;
    let upstream_rows =
        open_ai_data_rows(upstream_payload, &format!("{} model catalog", source.id))?;

    let models_dev = models_dev_payload.as_object().ok_or_else(|| {
        CatalogError::InvalidModelsDev("expected object for models.dev catalog".to_string())
    })?;

    let provider = models_dev
        .get(&source.models_dev_provider)
        .and_then(|p| p.as_object())
        .ok_or_else(|| {
            CatalogError::InvalidModelsDev(format!(
                "models.dev provider {} missing",
                source.models_dev_provider
            ))
        })?;

    let provider_npm = provider
        .get("npm")
        .and_then(|n| n.as_str())
        .ok_or_else(|| {
            CatalogError::InvalidModelsDev(format!(
                "invalid models.dev provider {}: missing npm",
                source.models_dev_provider
            ))
        })?;

    let metadata_by_id = provider.get("models").and_then(|m| m.as_object());

    let mut entries = Vec::new();
    let mut unsupported = Vec::new();

    for upstream in upstream_rows {
        let Some(id) = upstream.get("id").and_then(|i| i.as_str()) else {
            continue;
        };
        if is_generation_only_model(id) {
            continue;
        }

        let metadata = metadata_by_id.and_then(|m| m.get(id));
        if !is_agent_model(metadata, upstream) {
            continue;
        }

        let model_provider = metadata
            .and_then(|m| m.get("provider"))
            .and_then(|p| p.as_object());

        let npm = model_provider
            .and_then(|p| p.get("npm"))
            .and_then(|n| n.as_str())
            .unwrap_or(provider_npm);

        let shape = model_provider
            .and_then(|p| p.get("shape"))
            .and_then(|s| s.as_str());

        let api = api_for_provider(npm, shape);
        let Some(api) = api else {
            unsupported.push(UnsupportedCatalogModel {
                id: id.to_string(),
                npm: Some(npm.to_string()),
                shape: shape.map(ToString::to_string),
            });
            continue;
        };

        let alias = public_alias(source, id);
        let model = normalize_model(source, &alias, api, metadata, upstream);
        let mapping = mapping_for(id, &alias, &model);
        entries.push((mapping, model));
    }

    entries.sort_by(|a, b| a.1.id.cmp(&b.1.id));
    unsupported.sort_by(|a, b| a.id.cmp(&b.id));

    let mut groups: BTreeMap<CatalogApi, Vec<CliProxyModelMapping>> = BTreeMap::new();
    let mut models = Vec::with_capacity(entries.len());

    for (mapping, model) in entries {
        groups.entry(model.api).or_default().push(mapping);
        models.push(model);
    }

    Ok(SourceModels {
        groups,
        models,
        unsupported,
    })
}

#[derive(Debug, Clone, Default)]
struct RichGatewayModel {
    name: Option<String>,
    context_window: Option<u64>,
    input: Option<Vec<InputModality>>,
    reasoning_efforts: Option<Vec<String>>,
    default_reasoning_effort: Option<String>,
}

fn rich_gateway_models(
    payload: Option<&serde_json::Value>,
) -> Result<HashMap<String, RichGatewayModel>, CatalogError> {
    let mut map = HashMap::new();
    let Some(payload) = payload else {
        return Ok(map);
    };

    let obj = payload.as_object().ok_or_else(|| {
        CatalogError::InvalidStructure(
            "CLIProxyAPI rich model catalog".to_string(),
            "expected object".to_string(),
        )
    })?;

    let models_arr = obj
        .get("models")
        .and_then(|m| m.as_array())
        .ok_or_else(|| {
            CatalogError::InvalidStructure(
                "CLIProxyAPI rich model catalog".to_string(),
                "expected models array".to_string(),
            )
        })?;

    for (idx, row) in models_arr.iter().enumerate() {
        let row_obj = row.as_object().ok_or_else(|| {
            CatalogError::InvalidStructure(
                format!("CLIProxyAPI rich model catalog.models[{idx}]"),
                "expected object".to_string(),
            )
        })?;

        let slug = row_obj
            .get("slug")
            .and_then(|s| s.as_str())
            .ok_or_else(|| {
                CatalogError::InvalidField(format!(
                    "invalid CLIProxyAPI rich model catalog.models[{idx}].slug"
                ))
            })?;

        let name = row_obj
            .get("display_name")
            .and_then(|d| d.as_str())
            .map(ToString::to_string);

        let context_window = positive_integer(row_obj.get("context_window"));

        let input_modalities = string_array(row_obj.get("input_modalities"));
        let input = if input_modalities.is_empty() {
            None
        } else if input_modalities.iter().any(|m| m == "image") {
            Some(vec![InputModality::Text, InputModality::Image])
        } else {
            Some(vec![InputModality::Text])
        };

        let reasoning_efforts =
            reasoning_efforts_from_value(row_obj.get("supported_reasoning_levels"));

        let default_reasoning_effort = row_obj
            .get("default_reasoning_level")
            .and_then(|d| d.as_str())
            .map(ToString::to_string);

        map.insert(
            slug.to_string(),
            RichGatewayModel {
                name,
                context_window,
                input,
                reasoning_efforts,
                default_reasoning_effort,
            },
        );
    }

    Ok(map)
}

fn enrich_with_rich_gateway_model(
    mut model: CatalogModel,
    rich: Option<&RichGatewayModel>,
) -> CatalogModel {
    let Some(rich) = rich else { return model };

    if let Some(name) = &rich.name {
        model.name.clone_from(name);
    }
    if let Some(context_window) = rich.context_window {
        model.context_window = context_window;
    }
    if let Some(ref input) = rich.input {
        model.input.clone_from(input);
    }
    if let Some(ref efforts) = rich.reasoning_efforts {
        model.reasoning = efforts.iter().any(|e| e != "none");
        model.reasoning_efforts = Some(efforts.clone());
    }
    if let Some(ref def) = rich.default_reasoning_effort {
        model.default_reasoning_effort = Some(def.clone());
    }

    model
}

struct ModelsDevReference<'a> {
    provider_npm: &'a str,
    model: Option<&'a serde_json::Value>,
}

fn find_models_dev_reference<'a>(
    payload: Option<&'a serde_json::Value>,
    owned_by: &str,
    model_id: &str,
) -> Option<ModelsDevReference<'a>> {
    let providers = payload?.as_object()?;

    let check_provider =
        |p_obj: &'a serde_json::Map<String, serde_json::Value>| -> Option<ModelsDevReference<'a>> {
            let provider_npm = p_obj.get("npm")?.as_str()?;
            let models = p_obj.get("models")?.as_object()?;
            let model = models.get(model_id);
            if model.is_some() {
                Some(ModelsDevReference {
                    provider_npm,
                    model,
                })
            } else {
                None
            }
        };

    if let Some(preferred) = providers.get(owned_by).and_then(|p| p.as_object())
        && let Some(r) = check_provider(preferred)
    {
        return Some(r);
    }

    let mut provider_keys: Vec<&String> = providers.keys().collect();
    provider_keys.sort();

    for key in provider_keys {
        if let Some(p_obj) = providers.get(key).and_then(|p| p.as_object())
            && let Some(r) = check_provider(p_obj)
        {
            return Some(r);
        }
    }

    None
}

fn gateway_model(
    id: &str,
    owned_by: &str,
    gateway_row: &serde_json::Value,
    models_dev_payload: Option<&serde_json::Value>,
) -> CatalogModel {
    let unref = unprefix_model_id(id);
    let dev_ref = find_models_dev_reference(models_dev_payload, owned_by, unref);

    let model_provider = dev_ref
        .as_ref()
        .and_then(|r| r.model)
        .and_then(|m| m.get("provider"))
        .and_then(|p| p.as_object());

    let npm = model_provider
        .and_then(|p| p.get("npm"))
        .and_then(|n| n.as_str())
        .or_else(|| dev_ref.as_ref().map(|r| r.provider_npm))
        .unwrap_or("@ai-sdk/openai-compatible");

    let shape = model_provider
        .and_then(|p| p.get("shape"))
        .and_then(|s| s.as_str());

    let api = api_for_provider(npm, shape).unwrap_or(CatalogApi::OpenAiCompletions);

    let metadata = dev_ref.as_ref().and_then(|r| r.model);
    let limit = metadata
        .and_then(|m| m.get("limit"))
        .and_then(|l| l.as_object());

    let context_window = positive_integer(gateway_row.get("context_length"))
        .or_else(|| positive_integer(limit.and_then(|l| l.get("context"))))
        .unwrap_or(128_000);

    let max_tokens = positive_integer(gateway_row.get("max_completion_tokens"))
        .or_else(|| positive_integer(limit.and_then(|l| l.get("output"))))
        .unwrap_or_else(|| context_window.min(16_384));

    let mut input_modalities = Vec::new();
    if let Some(meta) = metadata
        && let Some(mods) = meta.get("modalities")
    {
        input_modalities.extend(string_array(mods.get("input")));
    }

    let input = if input_modalities.iter().any(|m| m == "image") {
        vec![InputModality::Text, InputModality::Image]
    } else {
        vec![InputModality::Text]
    };

    let metadata_cost = metadata
        .and_then(|m| m.get("cost"))
        .and_then(|c| c.as_object());

    let cost = metadata_cost.map_or_else(CatalogCost::default, |mc| CatalogCost {
        input: non_negative_number(mc.get("input")),
        output: non_negative_number(mc.get("output")),
        cache_read: non_negative_number(mc.get("cache_read")),
        cache_write: non_negative_number(mc.get("cache_write")),
    });

    let efforts = reasoning_efforts_from_value(metadata.and_then(|m| m.get("reasoning_options")));
    let default_reasoning_effort = metadata
        .and_then(|m| m.get("default_reasoning_effort"))
        .and_then(|d| d.as_str())
        .map(ToString::to_string);

    let supported_parameters = string_array(gateway_row.get("supported_parameters"));

    let reasoning = metadata
        .and_then(|m| m.get("reasoning"))
        .and_then(serde_json::Value::as_bool)
        == Some(true)
        || efforts
            .as_ref()
            .is_some_and(|effs| effs.iter().any(|e| e != "none"))
        || supported_parameters.iter().any(|p| p == "reasoning")
        || supported_parameters.iter().any(|p| p == "reasoning_effort");

    let name = metadata
        .and_then(|m| m.get("name"))
        .and_then(|n| n.as_str())
        .unwrap_or(id)
        .to_string();

    let compat = compat_for(metadata, &supported_parameters);

    CatalogModel {
        id: id.to_string(),
        name,
        api,
        reasoning,
        reasoning_efforts: efforts,
        default_reasoning_effort,
        input,
        cost,
        context_window,
        max_tokens,
        compat,
    }
}

pub fn enrich_gateway_models(
    discovered: &[CatalogModel],
    gateway_payload: &serde_json::Value,
    options: &GatewayCatalogOptions,
) -> Result<Vec<CatalogModel>, CatalogError> {
    let rich_models = rich_gateway_models(options.rich_gateway_payload.as_ref())?;

    let mut by_id: BTreeMap<String, CatalogModel> = BTreeMap::new();
    for model in discovered {
        let enriched = enrich_with_rich_gateway_model(model.clone(), rich_models.get(&model.id));
        by_id.insert(model.id.clone(), enriched);
    }

    let managed_prefixes: HashSet<&str> = options
        .managed_prefixes
        .iter()
        .map(String::as_str)
        .collect();

    let mut gateway_ids: HashSet<String> = HashSet::new();
    let gateway_rows = open_ai_data_rows(gateway_payload, "CLIProxyAPI model catalog")?;

    for row in gateway_rows {
        let Some(id) = row.get("id").and_then(|i| i.as_str()) else {
            continue;
        };
        let Some(owned_by) = row.get("owned_by").and_then(|o| o.as_str()) else {
            continue;
        };
        if is_generation_only_model(id) {
            continue;
        }
        gateway_ids.insert(id.to_string());

        let prefix_part = id.split_once('/').map_or("", |(p, _)| p);
        if managed_prefixes.contains(prefix_part) || by_id.contains_key(id) {
            continue;
        }

        let model = gateway_model(id, owned_by, row, options.models_dev.as_ref());
        let enriched = enrich_with_rich_gateway_model(model, rich_models.get(id));
        by_id.insert(id.to_string(), enriched);
    }

    for alias in &options.aliases {
        if by_id.contains_key(&alias.id) {
            continue;
        }
        if !gateway_ids.contains(&alias.id) && !rich_models.contains_key(&alias.id) {
            continue;
        }
        let Some(source) = by_id.get(&alias.source_id).cloned() else {
            continue;
        };
        let mut model = source;
        model.id.clone_from(&alias.id);
        if let Some(ref name) = alias.name {
            model.name.clone_from(name);
        }
        let enriched = enrich_with_rich_gateway_model(model, rich_models.get(&alias.id));
        by_id.insert(alias.id.clone(), enriched);
    }

    Ok(by_id.into_values().collect())
}

pub fn write_model_catalog(path: &Path, models: &[CatalogModel]) -> Result<(), CatalogError> {
    let mut unique: BTreeMap<&str, &CatalogModel> = BTreeMap::new();
    for model in models {
        if unique.insert(&model.id, model).is_some() {
            return Err(CatalogError::DuplicateId(model.id.clone()));
        }
    }

    let sorted_models: Vec<CatalogModel> = unique.into_values().cloned().collect();
    let catalog = SerializedModelCatalog {
        version: MODEL_CATALOG_VERSION,
        models: sorted_models,
    };

    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent)?;
    }

    let serialized = serde_json::to_string_pretty(&catalog)?;
    let content = format!("{serialized}\n");
    sync_private_text_file(path, &content)?;

    Ok(())
}

pub fn read_model_catalog(path: &Path) -> Result<Vec<CatalogModel>, CatalogError> {
    let content = fs::read_to_string(path)
        .map_err(|e| CatalogError::ReadFailed(path.display().to_string(), e.to_string()))?;
    parse_model_catalog_json(&content, &path.display().to_string())
}

pub fn parse_model_catalog_json(
    content: &str,
    label: &str,
) -> Result<Vec<CatalogModel>, CatalogError> {
    let value: serde_json::Value = serde_json::from_str(content)
        .map_err(|e| CatalogError::ReadFailed(label.to_string(), e.to_string()))?;

    let obj = value.as_object().ok_or_else(|| {
        CatalogError::InvalidStructure(label.to_string(), "expected object".to_string())
    })?;

    let version = obj
        .get("version")
        .and_then(serde_json::Value::as_u64)
        .ok_or_else(|| {
            CatalogError::InvalidField(format!("invalid model catalog {label}: missing version"))
        })?;

    if version != u64::from(MODEL_CATALOG_VERSION) {
        return Err(CatalogError::InvalidField(format!(
            "invalid model catalog {label}: unsupported version {version}"
        )));
    }

    let models_arr = obj
        .get("models")
        .and_then(|m| m.as_array())
        .ok_or_else(|| {
            CatalogError::InvalidStructure(
                format!("model catalog {label}"),
                "expected models array".to_string(),
            )
        })?;

    let mut models = Vec::with_capacity(models_arr.len());
    for (idx, item) in models_arr.iter().enumerate() {
        let model = parse_single_catalog_model(item, &format!("{label}.models[{idx}]"))?;
        models.push(model);
    }

    Ok(models)
}

fn parse_single_catalog_model(
    value: &serde_json::Value,
    label: &str,
) -> Result<CatalogModel, CatalogError> {
    let obj = value.as_object().ok_or_else(|| {
        CatalogError::InvalidStructure(label.to_string(), "expected object".to_string())
    })?;

    let id = obj
        .get("id")
        .and_then(|i| i.as_str())
        .ok_or_else(|| CatalogError::InvalidField(format!("{label}.id")))?
        .to_string();

    let name = obj
        .get("name")
        .and_then(|n| n.as_str())
        .ok_or_else(|| CatalogError::InvalidField(format!("{label}.name")))?
        .to_string();

    let api_str = obj
        .get("api")
        .and_then(|a| a.as_str())
        .ok_or_else(|| CatalogError::InvalidField(format!("{label}.api")))?;

    let api = match api_str {
        "anthropic-messages" => CatalogApi::AnthropicMessages,
        "openai-completions" => CatalogApi::OpenAiCompletions,
        "openai-responses" => CatalogApi::OpenAiResponses,
        _ => {
            return Err(CatalogError::InvalidField(format!(
                "{label}.api: {api_str}"
            )));
        }
    };

    let reasoning = obj
        .get("reasoning")
        .and_then(serde_json::Value::as_bool)
        .ok_or_else(|| CatalogError::InvalidField(format!("{label}.reasoning")))?;

    let reasoning_efforts = reasoning_efforts_from_value(obj.get("reasoningEfforts"))
        .or_else(|| parse_legacy_thinking_level_map(obj.get("thinkingLevelMap")));

    let default_reasoning_effort = obj
        .get("defaultReasoningEffort")
        .and_then(|d| d.as_str())
        .map(ToString::to_string);

    let input_arr = obj
        .get("input")
        .and_then(|i| i.as_array())
        .ok_or_else(|| CatalogError::InvalidField(format!("{label}.input")))?;

    let mut input = Vec::new();
    for inp in input_arr {
        match inp.as_str() {
            Some("text") => input.push(InputModality::Text),
            Some("image") => input.push(InputModality::Image),
            _ => return Err(CatalogError::InvalidField(format!("{label}.input"))),
        }
    }
    if input.is_empty() {
        return Err(CatalogError::InvalidField(format!("{label}.input: empty")));
    }

    let cost_obj = obj
        .get("cost")
        .and_then(|c| c.as_object())
        .ok_or_else(|| CatalogError::InvalidField(format!("{label}.cost")))?;

    let cost = CatalogCost {
        input: cost_obj
            .get("input")
            .and_then(serde_json::Value::as_f64)
            .ok_or_else(|| CatalogError::InvalidField(format!("{label}.cost.input")))?,
        output: cost_obj
            .get("output")
            .and_then(serde_json::Value::as_f64)
            .ok_or_else(|| CatalogError::InvalidField(format!("{label}.cost.output")))?,
        cache_read: cost_obj
            .get("cacheRead")
            .and_then(serde_json::Value::as_f64)
            .ok_or_else(|| CatalogError::InvalidField(format!("{label}.cost.cacheRead")))?,
        cache_write: cost_obj
            .get("cacheWrite")
            .and_then(serde_json::Value::as_f64)
            .ok_or_else(|| CatalogError::InvalidField(format!("{label}.cost.cacheWrite")))?,
    };

    let context_window = positive_integer(obj.get("contextWindow"))
        .ok_or_else(|| CatalogError::InvalidField(format!("{label}.contextWindow")))?;

    let max_tokens = positive_integer(obj.get("maxTokens"))
        .ok_or_else(|| CatalogError::InvalidField(format!("{label}.maxTokens")))?;

    let compat = obj.get("compat").cloned();

    Ok(CatalogModel {
        id,
        name,
        api,
        reasoning,
        reasoning_efforts,
        default_reasoning_effort,
        input,
        cost,
        context_window,
        max_tokens,
        compat,
    })
}

fn parse_legacy_thinking_level_map(value: Option<&serde_json::Value>) -> Option<Vec<String>> {
    let obj = value?.as_object()?;
    let mut efforts = Vec::new();
    for (_key, val) in obj {
        if let Some(s) = val.as_str()
            && !efforts.contains(&s.to_string())
        {
            efforts.push(s.to_string());
        }
    }
    if efforts.is_empty() {
        None
    } else {
        Some(efforts)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;
    use tempfile::tempdir;

    fn test_source() -> ModelCatalogSource {
        ModelCatalogSource {
            id: "example".to_string(),
            models_dev_provider: "example".to_string(),
            prefix: "example".to_string(),
            base_url: "https://example.test/v1".to_string(),
        }
    }

    fn model_metadata(name: &str) -> serde_json::Value {
        json!({
            "name": name,
            "limit": { "context": 300_000, "output": 100_000 },
            "modalities": { "input": ["text", "image"], "output": ["text"] },
            "reasoning": true,
            "reasoning_options": [{ "effort": "low" }, { "effort": "high" }]
        })
    }

    #[test]
    fn models_dev_metadata_routes_live_models_without_local_model_policies() {
        let source = test_source();
        let upstream = json!({
            "data": [
                { "id": "chat-next" },
                { "id": "responses-next" },
                { "id": "claude-next" },
                { "id": "google-next" },
                { "id": "no-tools" },
                { "id": "not-in-metadata", "context_length": 64000 }
            ]
        });
        let models_dev = json!({
            "example": {
                "npm": "@ai-sdk/openai-compatible",
                "models": {
                    "chat-next": model_metadata("Chat Next"),
                    "responses-next": {
                        "name": "Responses Next",
                        "limit": { "context": 300_000, "output": 100_000 },
                        "modalities": { "input": ["text", "image"], "output": ["text"] },
                        "reasoning": true,
                        "reasoning_options": [{ "effort": "low" }, { "effort": "high" }],
                        "provider": { "npm": "@ai-sdk/openai" }
                    },
                    "claude-next": {
                        "name": "Claude Next",
                        "limit": { "context": 300_000, "output": 100_000 },
                        "modalities": { "input": ["text", "image"], "output": ["text"] },
                        "reasoning": true,
                        "provider": { "npm": "@ai-sdk/anthropic" }
                    },
                    "google-next": {
                        "name": "Google Next",
                        "provider": { "npm": "@ai-sdk/google" }
                    },
                    "no-tools": {
                        "name": "No Tools",
                        "tool_call": false
                    }
                }
            }
        });

        let result = models_for_source(&source, &upstream, &models_dev).unwrap();

        let group_keys: Vec<CatalogApi> = result.groups.keys().copied().collect();
        assert_eq!(
            group_keys,
            vec![
                CatalogApi::AnthropicMessages,
                CatalogApi::OpenAiCompletions,
                CatalogApi::OpenAiResponses,
            ]
        );

        assert_eq!(
            result.unsupported,
            vec![UnsupportedCatalogModel {
                id: "google-next".to_string(),
                npm: Some("@ai-sdk/google".to_string()),
                shape: None,
            }]
        );

        let ids: Vec<&str> = result.models.iter().map(|m| m.id.as_str()).collect();
        assert_eq!(
            ids,
            vec![
                "example/chat-next",
                "example/claude-next",
                "example/not-in-metadata",
                "example/responses-next",
            ]
        );

        let responses_next = result
            .models
            .iter()
            .find(|m| m.id.ends_with("responses-next"))
            .unwrap();
        assert_eq!(responses_next.api, CatalogApi::OpenAiResponses);
        assert!(responses_next.reasoning);
        assert_eq!(
            responses_next.reasoning_efforts,
            Some(vec!["low".to_string(), "high".to_string()])
        );
        assert_eq!(
            responses_next.input,
            vec![InputModality::Text, InputModality::Image]
        );
        assert_eq!(responses_next.context_window, 300_000);
        assert_eq!(responses_next.max_tokens, 100_000);

        let not_in_meta = result
            .models
            .iter()
            .find(|m| m.id.ends_with("not-in-metadata"))
            .unwrap();
        assert_eq!(not_in_meta.api, CatalogApi::OpenAiCompletions);
        assert_eq!(not_in_meta.context_window, 64_000);
    }

    #[test]
    fn openrouter_metadata_routes_command_code_models_through_chat_completions() {
        let source = ModelCatalogSource {
            id: "command-code".to_string(),
            models_dev_provider: "openrouter".to_string(),
            prefix: "cmd".to_string(),
            base_url: "https://api.commandcode.ai/provider/v1".to_string(),
        };
        let upstream = json!({
            "data": [
                { "id": "claude-sonnet-5", "context_length": 1_000_000 },
                { "id": "deepseek/deepseek-v4-flash", "context_length": 1_000_000 }
            ]
        });
        let models_dev = json!({
            "openrouter": {
                "npm": "@openrouter/ai-sdk-provider",
                "models": {
                    "deepseek/deepseek-v4-flash": model_metadata("DeepSeek V4 Flash")
                }
            }
        });

        let result = models_for_source(&source, &upstream, &models_dev).unwrap();
        let group_keys: Vec<CatalogApi> = result.groups.keys().copied().collect();
        assert_eq!(group_keys, vec![CatalogApi::OpenAiCompletions]);

        assert_eq!(result.models.len(), 2);
        assert_eq!(result.models[0].id, "cmd/claude-sonnet-5");
        assert_eq!(result.models[0].api, CatalogApi::OpenAiCompletions);
        assert_eq!(result.models[0].context_window, 1_000_000);

        assert_eq!(result.models[1].id, "cmd/deepseek/deepseek-v4-flash");
        assert_eq!(result.models[1].api, CatalogApi::OpenAiCompletions);
        assert_eq!(result.models[1].context_window, 1_000_000);
        assert_eq!(result.unsupported, []);
    }

    #[test]
    fn models_dev_shape_override_wins_over_npm_default() {
        let source = test_source();
        let upstream = json!({
            "data": [{ "id": "shape-completions" }, { "id": "shape-responses" }]
        });
        let models_dev = json!({
            "example": {
                "npm": "@ai-sdk/openai",
                "models": {
                    "shape-completions": {
                        "name": "Completions",
                        "provider": { "shape": "completions" }
                    },
                    "shape-responses": {
                        "name": "Responses",
                        "provider": { "shape": "responses" }
                    }
                }
            }
        });

        let result = models_for_source(&source, &upstream, &models_dev).unwrap();
        assert_eq!(result.models[0].id, "example/shape-completions");
        assert_eq!(result.models[0].api, CatalogApi::OpenAiCompletions);
        assert_eq!(result.models[1].id, "example/shape-responses");
        assert_eq!(result.models[1].api, CatalogApi::OpenAiResponses);
    }

    #[test]
    fn rich_openai_catalog_fields_enrich_models_dev_metadata() {
        let source = ModelCatalogSource {
            id: "router".to_string(),
            prefix: "router".to_string(),
            models_dev_provider: "router".to_string(),
            base_url: "https://example.test/v1".to_string(),
        };
        let upstream = json!({
            "data": [
                {
                    "id": "router/auto",
                    "name": "Auto Router",
                    "context_length": 2_000_000,
                    "architecture": {
                        "input_modalities": ["text", "image"],
                        "output_modalities": ["text"]
                    },
                    "supported_parameters": ["tools", "reasoning", "tool_choice"],
                    "pricing": { "prompt": "0.000001", "completion": "0.000002" },
                    "top_provider": { "max_completion_tokens": 64000 }
                }
            ]
        });
        let models_dev = json!({
            "router": {
                "npm": "@ai-sdk/openai-compatible",
                "models": {
                    "router/auto": model_metadata("Catalog Name")
                }
            }
        });

        let result = models_for_source(&source, &upstream, &models_dev).unwrap();
        assert_eq!(result.models.len(), 1);
        let model = &result.models[0];
        assert_eq!(model.id, "router/auto");
        assert_eq!(model.name, "Auto Router");
        assert_eq!(model.api, CatalogApi::OpenAiCompletions);
        assert!(model.reasoning);
        assert_eq!(model.input, vec![InputModality::Text, InputModality::Image]);
        assert_eq!(model.context_window, 2_000_000);
        assert_eq!(model.max_tokens, 64_000);
        assert_eq!(model.cost.input, 1.0);
        assert_eq!(model.cost.output, 2.0);
    }

    #[test]
    fn gateway_catalog_adds_oauth_models_without_overwriting_richer_models() {
        let source = test_source();
        let external = models_for_source(
            &source,
            &json!({ "data": [{ "id": "responses-next" }] }),
            &json!({
                "example": {
                    "npm": "@ai-sdk/openai",
                    "models": {
                        "responses-next": model_metadata("Responses Next")
                    }
                }
            }),
        )
        .unwrap()
        .models;

        let gateway_payload = json!({
            "data": [
                { "id": "example/responses-next", "owned_by": "openai" },
                { "id": "chatgpt/gpt-oauth-next", "owned_by": "openai" },
                { "id": "gemini-oauth-next", "owned_by": "antigravity" },
                { "id": "gpt-image-next", "owned_by": "openai" }
            ]
        });

        let models_dev = json!({
            "openai": {
                "npm": "@ai-sdk/openai",
                "models": {
                    "gpt-oauth-next": model_metadata("GPT OAuth Next")
                }
            }
        });

        let options = GatewayCatalogOptions {
            models_dev: Some(models_dev),
            ..Default::default()
        };

        let merged = enrich_gateway_models(&external, &gateway_payload, &options).unwrap();
        let ids: Vec<&str> = merged.iter().map(|m| m.id.as_str()).collect();
        assert_eq!(
            ids,
            vec![
                "chatgpt/gpt-oauth-next",
                "example/responses-next",
                "gemini-oauth-next",
            ]
        );

        let resp_next = merged
            .iter()
            .find(|m| m.id == "example/responses-next")
            .unwrap();
        assert_eq!(resp_next.context_window, 300_000);

        let gpt_oauth = merged
            .iter()
            .find(|m| m.id == "chatgpt/gpt-oauth-next")
            .unwrap();
        assert_eq!(gpt_oauth.name, "GPT OAuth Next");
        assert_eq!(gpt_oauth.api, CatalogApi::OpenAiResponses);
        assert!(gpt_oauth.reasoning);
        assert_eq!(gpt_oauth.context_window, 300_000);
    }

    #[test]
    fn gateway_catalog_clones_explicit_aliases_under_managed_prefixes() {
        let source = test_source();
        let discovered = models_for_source(
            &source,
            &json!({ "data": [{ "id": "responses-next" }] }),
            &json!({
                "example": {
                    "npm": "@ai-sdk/openai",
                    "models": { "responses-next": model_metadata("Responses Next") }
                }
            }),
        )
        .unwrap()
        .models;

        let gateway_payload = json!({
            "data": [
                { "id": "example/responses-next", "owned_by": "example" },
                { "id": "example/nnn-responses-next-high", "owned_by": "example" }
            ]
        });

        let options = GatewayCatalogOptions {
            aliases: vec![CatalogAlias {
                id: "example/nnn-responses-next-high".to_string(),
                source_id: "example/responses-next".to_string(),
                name: Some("[nnn] Responses Next (High)".to_string()),
            }],
            managed_prefixes: vec!["example".to_string()],
            rich_gateway_payload: Some(json!({
                "models": [
                    {
                        "slug": "example/nnn-responses-next-high",
                        "display_name": "[nnn] Responses Next (High)",
                        "context_window": 400_000,
                        "supported_reasoning_levels": [{ "effort": "high" }]
                    }
                ]
            })),
            ..Default::default()
        };

        let merged = enrich_gateway_models(&discovered, &gateway_payload, &options).unwrap();
        let ids: Vec<&str> = merged.iter().map(|m| m.id.as_str()).collect();
        assert_eq!(
            ids,
            vec!["example/nnn-responses-next-high", "example/responses-next",]
        );
        assert_eq!(merged[0].name, "[nnn] Responses Next (High)");
        assert_eq!(merged[0].api, CatalogApi::OpenAiResponses);
        assert!(merged[0].reasoning);
        assert_eq!(merged[0].reasoning_efforts, Some(vec!["high".to_string()]));
        assert_eq!(merged[0].context_window, 400_000);
    }

    #[test]
    fn write_and_read_model_catalog_round_trip() {
        let dir = tempdir().unwrap();
        let catalog_path = dir.path().join("catalog.json");

        let models = vec![
            CatalogModel {
                id: "model-b".to_string(),
                name: "Model B".to_string(),
                api: CatalogApi::OpenAiResponses,
                reasoning: false,
                reasoning_efforts: None,
                default_reasoning_effort: None,
                input: vec![InputModality::Text],
                cost: CatalogCost::default(),
                context_window: 128_000,
                max_tokens: 16_384,
                compat: None,
            },
            CatalogModel {
                id: "model-a".to_string(),
                name: "Model A".to_string(),
                api: CatalogApi::OpenAiCompletions,
                reasoning: true,
                reasoning_efforts: Some(vec!["low".to_string()]),
                default_reasoning_effort: Some("low".to_string()),
                input: vec![InputModality::Text, InputModality::Image],
                cost: CatalogCost {
                    input: 1.0,
                    output: 2.0,
                    cache_read: 0.1,
                    cache_write: 0.2,
                },
                context_window: 256_000,
                max_tokens: 32_000,
                compat: Some(json!({ "supportsToolChoice": false })),
            },
        ];

        write_model_catalog(&catalog_path, &models).unwrap();
        let read = read_model_catalog(&catalog_path).unwrap();

        assert_eq!(read.len(), 2);
        // Models must be sorted by ID
        assert_eq!(read[0].id, "model-a");
        assert_eq!(read[1].id, "model-b");
    }

    #[test]
    fn write_model_catalog_rejects_duplicates() {
        let dir = tempdir().unwrap();
        let catalog_path = dir.path().join("catalog.json");

        let models = vec![
            CatalogModel {
                id: "duplicate".to_string(),
                name: "One".to_string(),
                api: CatalogApi::OpenAiResponses,
                reasoning: false,
                reasoning_efforts: None,
                default_reasoning_effort: None,
                input: vec![InputModality::Text],
                cost: CatalogCost::default(),
                context_window: 128_000,
                max_tokens: 16_384,
                compat: None,
            },
            CatalogModel {
                id: "duplicate".to_string(),
                name: "Two".to_string(),
                api: CatalogApi::OpenAiResponses,
                reasoning: false,
                reasoning_efforts: None,
                default_reasoning_effort: None,
                input: vec![InputModality::Text],
                cost: CatalogCost::default(),
                context_window: 128_000,
                max_tokens: 16_384,
                compat: None,
            },
        ];

        assert!(write_model_catalog(&catalog_path, &models).is_err());
    }
}
