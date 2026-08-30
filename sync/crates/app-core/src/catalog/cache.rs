use std::collections::HashMap;
use std::fs;
use std::path::{Path, PathBuf};
use std::time::{Duration, SystemTime, UNIX_EPOCH};
use thiserror::Error;
use url::Url;

pub const CACHE_VERSION: u32 = 2;
pub const CACHE_MODE: u32 = 0o600;
pub const DEFAULT_TIMEOUT: Duration = Duration::from_secs(20);

#[derive(Debug, Error)]
pub enum CacheError {
    #[error("invalid model catalog URL: {0}")]
    InvalidUrl(String),

    #[error("invalid model catalog TTL: {0}")]
    InvalidTtl(u64),

    #[error("refresh model catalog {0}")]
    RefreshFailed(String),

    #[error("HTTP {0}")]
    Http(u16),

    #[error("I/O error: {0}")]
    Io(#[from] std::io::Error),

    #[error("JSON error: {0}")]
    Json(#[from] serde_json::Error),
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, serde::Serialize, serde::Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum CacheSource {
    Cache,
    Network,
    Stale,
}

#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
pub struct CacheEntry {
    pub version: u32,
    pub url: String,
    #[serde(rename = "fetchedAt")]
    pub fetched_at: i64,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub etag: Option<String>,
    pub payload: serde_json::Value,
}

#[derive(Debug, Clone)]
pub struct CachedJsonRequest {
    pub url: String,
    pub cache_path: PathBuf,
    pub ttl_ms: u64,
    pub force: bool,
    pub allow_stale_on_error: bool,
    pub headers: HashMap<String, String>,
}

impl CachedJsonRequest {
    #[must_use]
    pub fn new(url: impl Into<String>, cache_path: impl Into<PathBuf>, ttl_ms: u64) -> Self {
        Self {
            url: url.into(),
            cache_path: cache_path.into(),
            ttl_ms,
            force: false,
            allow_stale_on_error: true,
            headers: HashMap::new(),
        }
    }
}

#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
pub struct CachedJsonResult {
    pub payload: serde_json::Value,
    pub source: CacheSource,
}

#[derive(Debug, Clone)]
pub struct HttpFetchResponse {
    pub status: u16,
    pub etag: Option<String>,
    pub payload: serde_json::Value,
}

pub trait CatalogFetcher: Send + Sync {
    fn fetch(
        &self,
        url: &str,
        headers: &HashMap<String, String>,
        timeout: Duration,
    ) -> Result<HttpFetchResponse, String>;
}

pub struct ReqwestCatalogFetcher {
    client: reqwest::Client,
}

impl Default for ReqwestCatalogFetcher {
    fn default() -> Self {
        Self::new()
    }
}

impl ReqwestCatalogFetcher {
    #[must_use]
    pub fn new() -> Self {
        Self {
            client: reqwest::Client::builder().build().unwrap_or_default(),
        }
    }
}

impl CatalogFetcher for ReqwestCatalogFetcher {
    fn fetch(
        &self,
        url: &str,
        headers: &HashMap<String, String>,
        timeout: Duration,
    ) -> Result<HttpFetchResponse, String> {
        let client = self.client.clone();
        let url = url.to_owned();
        let headers = headers.clone();
        std::thread::spawn(move || {
            let rt = tokio::runtime::Builder::new_current_thread()
                .enable_all()
                .build()
                .map_err(|e| e.to_string())?;

            rt.block_on(async move {
                let mut req = client.get(url).timeout(timeout);
                for (key, val) in &headers {
                    req = req.header(key, val);
                }
                let response = req.send().await.map_err(|e| e.to_string())?;
                let status = response.status().as_u16();
                let etag = response
                    .headers()
                    .get("etag")
                    .and_then(|h| h.to_str().ok())
                    .map(ToString::to_string);

                if status == 304 {
                    return Ok(HttpFetchResponse {
                        status,
                        etag,
                        payload: serde_json::Value::Null,
                    });
                }

                if !response.status().is_success() {
                    return Err(format!("HTTP {status}"));
                }

                let payload = response
                    .json::<serde_json::Value>()
                    .await
                    .map_err(|e| e.to_string())?;
                Ok(HttpFetchResponse {
                    status,
                    etag,
                    payload,
                })
            })
        })
        .join()
        .map_err(|_| "catalog fetch thread panicked".to_owned())?
    }
}

#[must_use]
pub fn current_time_ms() -> i64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_or(0, |d| i64::try_from(d.as_millis()).unwrap_or(i64::MAX))
}

pub fn validate_request(request: &CachedJsonRequest) -> Result<(), CacheError> {
    let Ok(parsed_url) = Url::parse(&request.url) else {
        return Err(CacheError::InvalidUrl(request.url.clone()));
    };
    if parsed_url.scheme() != "http" && parsed_url.scheme() != "https" {
        return Err(CacheError::InvalidUrl(request.url.clone()));
    }
    if request.ttl_ms == 0 {
        return Err(CacheError::InvalidTtl(request.ttl_ms));
    }
    Ok(())
}

#[must_use]
pub fn read_cache(path: &Path, request_url: &str) -> Option<CacheEntry> {
    let content = fs::read_to_string(path).ok()?;
    let value: serde_json::Value = serde_json::from_str(&content).ok()?;
    let obj = value.as_object()?;

    let version = obj.get("version")?.as_u64()?;
    if version != u64::from(CACHE_VERSION) {
        return None;
    }

    let url = obj.get("url")?.as_str()?;
    if url != request_url {
        return None;
    }

    let fetched_at = obj.get("fetchedAt")?.as_i64()?;
    let payload = obj.get("payload")?.clone();

    let etag = match obj.get("etag") {
        Some(serde_json::Value::String(s)) => Some(s.clone()),
        Some(_) => return None,
        None => None,
    };

    Some(CacheEntry {
        version: CACHE_VERSION,
        url: url.to_string(),
        fetched_at,
        etag,
        payload,
    })
}

pub fn write_cache(path: &Path, entry: &CacheEntry) -> Result<(), CacheError> {
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent)?;
    }
    let serialized = serde_json::to_string(entry)?;
    let content = format!("{serialized}\n");
    fs::write(path, content)?;

    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        let _ = fs::set_permissions(path, fs::Permissions::from_mode(CACHE_MODE));
    }

    Ok(())
}

pub fn fetch_cached_json(
    request: &CachedJsonRequest,
    fetcher: Option<&dyn CatalogFetcher>,
    now_fn: Option<&dyn Fn() -> i64>,
) -> Result<CachedJsonResult, CacheError> {
    validate_request(request)?;
    let now = now_fn.map_or_else(current_time_ms, |f| f());
    let cached = read_cache(&request.cache_path, &request.url);

    if let Some(cached_entry) = &cached {
        let age = now.saturating_sub(cached_entry.fetched_at);
        if !request.force && age >= 0 && u64::try_from(age).unwrap_or(u64::MAX) < request.ttl_ms {
            return Ok(CachedJsonResult {
                payload: cached_entry.payload.clone(),
                source: CacheSource::Cache,
            });
        }
    }

    let mut headers = request.headers.clone();
    headers.insert("Accept".to_string(), "application/json".to_string());
    if let Some(cached_entry) = &cached
        && let Some(etag) = &cached_entry.etag
    {
        headers.insert("If-None-Match".to_string(), etag.clone());
    }

    let default_fetcher = ReqwestCatalogFetcher::new();
    let actual_fetcher = fetcher.unwrap_or(&default_fetcher);

    match actual_fetcher.fetch(&request.url, &headers, DEFAULT_TIMEOUT) {
        Ok(response) => {
            if response.status == 304
                && let Some(mut cached_entry) = cached
            {
                cached_entry.fetched_at = now;
                write_cache(&request.cache_path, &cached_entry)?;
                return Ok(CachedJsonResult {
                    payload: cached_entry.payload,
                    source: CacheSource::Network,
                });
            }
            if (200..=299).contains(&response.status) {
                let entry = CacheEntry {
                    version: CACHE_VERSION,
                    url: request.url.clone(),
                    fetched_at: now,
                    etag: response.etag,
                    payload: response.payload,
                };
                write_cache(&request.cache_path, &entry)?;
                return Ok(CachedJsonResult {
                    payload: entry.payload,
                    source: CacheSource::Network,
                });
            }
            if let Some(cached_entry) = cached
                && request.allow_stale_on_error
            {
                return Ok(CachedJsonResult {
                    payload: cached_entry.payload,
                    source: CacheSource::Stale,
                });
            }
            Err(CacheError::RefreshFailed(format!(
                "{} (HTTP {})",
                request.url, response.status
            )))
        }
        Err(err) => {
            if let Some(cached_entry) = cached
                && request.allow_stale_on_error
            {
                return Ok(CachedJsonResult {
                    payload: cached_entry.payload,
                    source: CacheSource::Stale,
                });
            }
            Err(CacheError::RefreshFailed(format!("{}: {err}", request.url)))
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;
    use std::sync::atomic::{AtomicUsize, Ordering};
    use std::sync::{Arc, Mutex};
    use tempfile::tempdir;

    type MockResponder = Box<
        dyn Fn(usize, &HashMap<String, String>) -> Result<HttpFetchResponse, String> + Send + Sync,
    >;

    struct MockFetcher {
        requests: Mutex<Vec<HashMap<String, String>>>,
        responder: MockResponder,
        call_count: AtomicUsize,
    }
    impl MockFetcher {
        fn new(
            responder: impl Fn(usize, &HashMap<String, String>) -> Result<HttpFetchResponse, String>
            + Send
            + Sync
            + 'static,
        ) -> Self {
            Self {
                requests: Mutex::new(Vec::new()),
                responder: Box::new(responder),
                call_count: AtomicUsize::new(0),
            }
        }
    }

    impl CatalogFetcher for MockFetcher {
        fn fetch(
            &self,
            _url: &str,
            headers: &HashMap<String, String>,
            _timeout: Duration,
        ) -> Result<HttpFetchResponse, String> {
            let count = self.call_count.fetch_add(1, Ordering::SeqCst);
            if let Ok(mut reqs) = self.requests.lock() {
                reqs.push(headers.clone());
            }
            (self.responder)(count, headers)
        }
    }

    #[test]
    fn model_catalog_cache_uses_ttl_and_revalidates_with_etag() {
        let dir = tempdir().expect("tempdir");
        let cache_path = dir.path().join("catalog.json");
        let now_val = Mutex::new(1000i64);

        let fetcher = MockFetcher::new(|idx, headers| {
            if idx == 0 {
                assert_eq!(headers.get("If-None-Match"), None);
                Ok(HttpFetchResponse {
                    status: 200,
                    etag: Some("\"one\"".to_string()),
                    payload: json!({ "data": [{ "id": "one" }] }),
                })
            } else {
                assert_eq!(headers.get("If-None-Match"), Some(&"\"one\"".to_string()));
                Ok(HttpFetchResponse {
                    status: 304,
                    etag: Some("\"one\"".to_string()),
                    payload: serde_json::Value::Null,
                })
            }
        });

        let request =
            CachedJsonRequest::new("https://example.test/v1/models", cache_path.clone(), 100);

        let res1 = fetch_cached_json(&request, Some(&fetcher), Some(&|| *now_val.lock().unwrap()))
            .unwrap();
        assert_eq!(res1.source, CacheSource::Network);
        assert_eq!(res1.payload, json!({ "data": [{ "id": "one" }] }));

        *now_val.lock().unwrap() = 1050;
        let res2 = fetch_cached_json(&request, Some(&fetcher), Some(&|| *now_val.lock().unwrap()))
            .unwrap();
        assert_eq!(res2.source, CacheSource::Cache);
        assert_eq!(res2.payload, json!({ "data": [{ "id": "one" }] }));

        *now_val.lock().unwrap() = 1200;
        let res3 = fetch_cached_json(&request, Some(&fetcher), Some(&|| *now_val.lock().unwrap()))
            .unwrap();
        assert_eq!(res3.source, CacheSource::Network);
        assert_eq!(res3.payload, json!({ "data": [{ "id": "one" }] }));

        let entry = read_cache(&cache_path, "https://example.test/v1/models").expect("entry");
        assert_eq!(entry.fetched_at, 1200);
    }

    #[test]
    fn model_catalog_cache_uses_stale_data_only_when_allowed() {
        let dir = tempdir().expect("tempdir");
        let cache_path = dir.path().join("catalog.json");
        let fail = Arc::new(Mutex::new(false));
        let fetch_fail = Arc::clone(&fail);

        let fetcher = MockFetcher::new(move |_idx, _headers| {
            if fetch_fail.lock().map_or(true, |state| *state) {
                Err("offline".to_string())
            } else {
                Ok(HttpFetchResponse {
                    status: 200,
                    etag: None,
                    payload: json!({ "data": [{ "id": "one" }] }),
                })
            }
        });

        let mut request = CachedJsonRequest::new("https://example.test/v1/models", cache_path, 100);
        request.force = true;

        let res1 = fetch_cached_json(&request, Some(&fetcher), Some(&|| 1000)).unwrap();
        assert_eq!(res1.source, CacheSource::Network);

        if let Ok(mut state) = fail.lock() {
            *state = true;
        }

        let res2 = fetch_cached_json(&request, Some(&fetcher), Some(&|| 1000)).unwrap();
        assert_eq!(res2.source, CacheSource::Stale);
        assert_eq!(res2.payload, json!({ "data": [{ "id": "one" }] }));

        request.allow_stale_on_error = false;
        let res3 = fetch_cached_json(&request, Some(&fetcher), Some(&|| 1000));
        assert!(res3.is_err());
    }

    #[test]
    fn model_catalog_cache_does_not_reuse_data_for_a_different_request_url() {
        let dir = tempdir().expect("tempdir");
        let cache_path = dir.path().join("catalog.json");

        let fetcher = MockFetcher::new(|_idx, _headers| {
            Ok(HttpFetchResponse {
                status: 200,
                etag: None,
                payload: json!({ "data": [{ "id": "url" }] }),
            })
        });

        let first_url = "https://old-gateway.test/v1/models";
        let second_url = "https://new-gateway.test/v1/models";

        let req_first = CachedJsonRequest::new(first_url, cache_path.clone(), 60_000);
        let result_first = fetch_cached_json(&req_first, Some(&fetcher), Some(&|| 1000)).unwrap();
        assert_eq!(result_first.source, CacheSource::Network);

        let req_second = CachedJsonRequest::new(second_url, cache_path.clone(), 60_000);
        let result_second = fetch_cached_json(&req_second, Some(&fetcher), Some(&|| 1000)).unwrap();
        assert_eq!(result_second.source, CacheSource::Network);
        assert_eq!(fetcher.call_count.load(Ordering::SeqCst), 2);

        let entry = read_cache(&cache_path, second_url).expect("entry");
        assert_eq!(entry.url, second_url);
    }

    #[test]
    fn model_catalog_cache_validates_url_and_ttl() {
        let dir = tempdir().expect("tempdir");
        let cache_path = dir.path().join("catalog.json");

        let req_ftp = CachedJsonRequest::new("ftp://example.test/v1", cache_path.clone(), 100);
        assert!(fetch_cached_json(&req_ftp, None, None).is_err());

        let req_zero_ttl = CachedJsonRequest::new("https://example.test/v1", cache_path, 0);
        assert!(fetch_cached_json(&req_zero_ttl, None, None).is_err());
    }
}
