use std::collections::HashSet;
use std::fs;
use std::path::{Path, PathBuf};
use std::time::Duration;
use thiserror::Error;
use url::Url;

pub const CLI_PROXY_SOURCE_DIR: &str = "tools/cliproxyapi";
pub const CLI_PROXY_CLIENT_BASE_URL_PLACEHOLDER: &str = "${CLIPROXY_CLIENT_BASE_URL}";
pub const ENDPOINT_READY_TIMEOUT: Duration = Duration::from_millis(500);

#[derive(Debug, Error)]
pub enum CliProxyError {
    #[error("invalid CLIProxyAPI deployment: {0}")]
    InvalidDeployment(String),

    #[error("invalid CLIProxyAPI deployment ({0})")]
    InvalidDeploymentDetails(String),

    #[error("invalid {0}: unknown field {1}")]
    UnknownField(String, String),

    #[error("invalid {0}: expected {1}")]
    ExpectedStructure(String, String),

    #[error("missing CLIProxyAPI endpoint placeholder: {0}")]
    MissingPlaceholder(String),

    #[error("read CLIProxyAPI endpoint template {0} ({1})")]
    ReadTemplateFailed(String, String),

    #[error("render CLIProxyAPI endpoint template {0} -> {1} ({2})")]
    RenderTemplateFailed(String, String, String),

    #[error("I/O error: {0}")]
    Io(#[from] std::io::Error),

    #[error("JSON error: {0}")]
    Json(#[from] serde_json::Error),
}

#[derive(Debug, Clone, PartialEq, Eq, serde::Serialize, serde::Deserialize)]
pub struct CliProxyServer {
    pub hostname: String,
}

#[derive(Debug, Clone, PartialEq, Eq, serde::Serialize, serde::Deserialize)]
pub struct CliProxyListen {
    pub host: String,
    pub port: u16,
}

#[derive(Debug, Clone, PartialEq, Eq, serde::Serialize, serde::Deserialize)]
pub struct CliProxyClient {
    #[serde(rename = "baseUrl")]
    pub base_url: String,
}

#[derive(Debug, Clone, PartialEq, Eq, serde::Serialize, serde::Deserialize)]
pub struct CliProxyDeployment {
    pub server: CliProxyServer,
    pub listen: CliProxyListen,
    pub client: CliProxyClient,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CliProxyEndpointTarget {
    pub src: PathBuf,
    pub dst: PathBuf,
    pub preserve_top_levels: Vec<String>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum CliProxyEndpointPublication {
    Published,
    Skipped,
}

#[derive(Debug, Clone, Default)]
pub struct CliProxyEndpointSyncOptions {
    pub timeout: Option<Duration>,
    pub skip_readiness: bool,
}

pub trait EndpointFetcher: Send + Sync {
    fn fetch_json(&self, url: &str, timeout: Duration) -> Result<serde_json::Value, String>;
}

pub struct ReqwestEndpointFetcher {
    client: reqwest::Client,
}

impl Default for ReqwestEndpointFetcher {
    fn default() -> Self {
        Self::new()
    }
}

impl ReqwestEndpointFetcher {
    #[must_use]
    pub fn new() -> Self {
        Self {
            client: reqwest::Client::builder().build().unwrap_or_default(),
        }
    }
}
impl EndpointFetcher for ReqwestEndpointFetcher {
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
        .map_err(|_| "endpoint fetch thread panicked".to_owned())?
    }
}

fn is_unspecified_ipv4(host: &str) -> bool {
    let lower = host.to_ascii_lowercase();
    if lower == "0x0" {
        return true;
    }
    let parts: Vec<&str> = lower.split('.').collect();
    if parts.len() > 4 || parts.is_empty() {
        return false;
    }
    parts
        .iter()
        .all(|part| !part.is_empty() && part.chars().all(|c| c == '0'))
}

fn is_unspecified_ipv6(host: &str) -> bool {
    let address = host.split('%').next().unwrap_or(host);

    if address.is_empty() {
        return false;
    }

    let is_zero_group =
        |g: &str| -> bool { !g.is_empty() && g.len() <= 4 && g.chars().all(|c| c == '0') };

    if address.contains('.') {
        if let Some(sep) = address.rfind(':') {
            let Some(ipv4_str) = address.get(sep.saturating_add(1)..) else {
                return false;
            };
            let parts: Vec<&str> = ipv4_str.split('.').collect();
            if parts.len() != 4
                || !parts
                    .iter()
                    .all(|p| p.chars().all(|c| c.is_ascii_digit()) && !p.is_empty())
            {
                return false;
            }
            let bytes: Vec<u32> = parts.iter().filter_map(|p| p.parse::<u32>().ok()).collect();
            if bytes.len() != 4 || bytes.iter().any(|&b| b > 255) {
                return false;
            }
            if bytes.iter().any(|&b| b != 0) {
                return false;
            }
            let Some(head) = address.get(..sep) else {
                return false;
            };
            let head_groups: Vec<&str> = head.split(':').collect();
            return head_groups.iter().all(|g| g.is_empty() || is_zero_group(g));
        }
        return false;
    }

    if let Some(comp_idx) = address.find("::") {
        if address
            .get(comp_idx.saturating_add(2)..)
            .and_then(|rem| rem.find("::"))
            .is_some()
        {
            return false;
        }
        let explicit: Vec<&str> = address.split(':').filter(|g| !g.is_empty()).collect();
        return explicit.iter().copied().all(is_zero_group) && explicit.len() < 8;
    }

    let groups: Vec<&str> = address.split(':').collect();
    groups.len() == 8 && groups.iter().copied().all(is_zero_group)
}

pub fn validate_server_hostname(h: &str) -> Result<(), CliProxyError> {
    if h.is_empty() || h != h.trim() || h.chars().any(|c| c.is_whitespace() || "/?#@:".contains(c))
    {
        return Err(CliProxyError::InvalidDeploymentDetails(
            "expected a local OS hostname".to_string(),
        ));
    }
    Ok(())
}

pub fn validate_listen_host(host: &str) -> Result<(), CliProxyError> {
    if host.is_empty()
        || host != host.trim()
        || host
            .chars()
            .any(|c| c.is_whitespace() || "/?#@".contains(c))
        || host.contains("://")
        || host.contains('[')
        || host.contains(']')
        || is_unspecified_ipv4(host)
        || is_unspecified_ipv6(host)
    {
        return Err(CliProxyError::InvalidDeploymentDetails(
            "expected a specific host or interface address".to_string(),
        ));
    }
    Ok(())
}

pub fn validate_listen_port(port: u16) -> Result<(), CliProxyError> {
    if port == 0 {
        return Err(CliProxyError::InvalidDeploymentDetails(
            "expected integer from 1 to 65535".to_string(),
        ));
    }
    Ok(())
}

pub fn validate_and_normalize_client_base_url(raw: &str) -> Result<String, CliProxyError> {
    if raw.is_empty() || raw != raw.trim() || raw.chars().any(|c| "?#".contains(c)) {
        return Err(CliProxyError::InvalidDeploymentDetails(
            "expected an HTTP(S) /v1 endpoint without credentials, query, or fragment".to_string(),
        ));
    }

    let Ok(parsed) = Url::parse(raw) else {
        return Err(CliProxyError::InvalidDeploymentDetails(
            "expected URL".to_string(),
        ));
    };

    if parsed.scheme() != "http" && parsed.scheme() != "https" {
        return Err(CliProxyError::InvalidDeploymentDetails(
            "expected an HTTP(S) /v1 endpoint without credentials, query, or fragment".to_string(),
        ));
    }

    if !parsed.username().is_empty()
        || parsed.password().is_some()
        || parsed.query().is_some()
        || parsed.fragment().is_some()
        || parsed.host_str().is_none()
    {
        return Err(CliProxyError::InvalidDeploymentDetails(
            "expected an HTTP(S) /v1 endpoint without credentials, query, or fragment".to_string(),
        ));
    }

    let path_normalized = parsed.path().trim_end_matches('/');
    if path_normalized != "/v1" {
        return Err(CliProxyError::InvalidDeploymentDetails(
            "expected an HTTP(S) /v1 endpoint without credentials, query, or fragment".to_string(),
        ));
    }

    Ok(raw.trim_end_matches('/').to_string())
}

fn reject_unknown_fields(
    map: &serde_json::Map<String, serde_json::Value>,
    allowed: &[&str],
    label: &str,
) -> Result<(), CliProxyError> {
    let allowed_set: HashSet<&str> = allowed.iter().copied().collect();
    for key in map.keys() {
        if !allowed_set.contains(key.as_str()) {
            return Err(CliProxyError::UnknownField(label.to_string(), key.clone()));
        }
    }
    Ok(())
}

pub fn parse_cli_proxy_deployment(
    value: &serde_json::Value,
) -> Result<CliProxyDeployment, CliProxyError> {
    let root = value.as_object().ok_or_else(|| {
        CliProxyError::ExpectedStructure("CLIProxyAPI deployment".to_string(), "object".to_string())
    })?;
    reject_unknown_fields(
        root,
        &["server", "listen", "client"],
        "CLIProxyAPI deployment",
    )?;

    let server_obj = root
        .get("server")
        .and_then(|s| s.as_object())
        .ok_or_else(|| {
            CliProxyError::ExpectedStructure(
                "CLIProxyAPI deployment.server".to_string(),
                "object".to_string(),
            )
        })?;
    reject_unknown_fields(server_obj, &["hostname"], "CLIProxyAPI deployment.server")?;

    let hostname = server_obj
        .get("hostname")
        .and_then(|h| h.as_str())
        .ok_or_else(|| {
            CliProxyError::InvalidDeploymentDetails("missing server.hostname".to_string())
        })?;
    validate_server_hostname(hostname)?;

    let listen_obj = root
        .get("listen")
        .and_then(|l| l.as_object())
        .ok_or_else(|| {
            CliProxyError::ExpectedStructure(
                "CLIProxyAPI deployment.listen".to_string(),
                "object".to_string(),
            )
        })?;
    reject_unknown_fields(
        listen_obj,
        &["host", "port"],
        "CLIProxyAPI deployment.listen",
    )?;

    let host = listen_obj
        .get("host")
        .and_then(|h| h.as_str())
        .ok_or_else(|| {
            CliProxyError::InvalidDeploymentDetails("missing listen.host".to_string())
        })?;
    validate_listen_host(host)?;

    let port_num = listen_obj
        .get("port")
        .and_then(serde_json::Value::as_u64)
        .ok_or_else(|| {
            CliProxyError::InvalidDeploymentDetails("expected integer from 1 to 65535".to_string())
        })?;
    let port = u16::try_from(port_num).map_err(|_| {
        CliProxyError::InvalidDeploymentDetails("expected integer from 1 to 65535".to_string())
    })?;
    validate_listen_port(port)?;

    let client_obj = root
        .get("client")
        .and_then(|c| c.as_object())
        .ok_or_else(|| {
            CliProxyError::ExpectedStructure(
                "CLIProxyAPI deployment.client".to_string(),
                "object".to_string(),
            )
        })?;
    reject_unknown_fields(client_obj, &["baseUrl"], "CLIProxyAPI deployment.client")?;

    let base_url_raw = client_obj
        .get("baseUrl")
        .and_then(|b| b.as_str())
        .ok_or_else(|| {
            CliProxyError::InvalidDeploymentDetails("missing client.baseUrl".to_string())
        })?;
    let normalized_base_url = validate_and_normalize_client_base_url(base_url_raw)?;

    Ok(CliProxyDeployment {
        server: CliProxyServer {
            hostname: hostname.to_string(),
        },
        listen: CliProxyListen {
            host: host.to_string(),
            port,
        },
        client: CliProxyClient {
            base_url: normalized_base_url,
        },
    })
}

pub fn read_cli_proxy_deployment(path: &Path) -> Result<CliProxyDeployment, CliProxyError> {
    let content = fs::read_to_string(path)?;
    // Use json5 to support JSONC
    let value: serde_json::Value = json5::from_str(&content)
        .map_err(|e| CliProxyError::InvalidDeployment(format!("{}: {e}", path.display())))?;
    parse_cli_proxy_deployment(&value)
}

#[must_use]
pub fn is_cli_proxy_gateway_host(
    deployment: &CliProxyDeployment,
    current_hostname: Option<&str>,
) -> bool {
    let default_host = gethostname::gethostname().to_string_lossy().to_string();
    let host = current_hostname.unwrap_or(&default_host);
    host.trim()
        .eq_ignore_ascii_case(&deployment.server.hostname)
}

mod gethostname {
    pub fn gethostname() -> std::ffi::OsString {
        let mut buf = vec![0u8; 256];
        let res = unsafe { libc::gethostname(buf.as_mut_ptr().cast::<libc::c_char>(), buf.len()) };
        if res == 0 {
            if let Some(pos) = buf.iter().position(|&b| b == 0) {
                buf.truncate(pos);
            }
            std::ffi::OsString::from(String::from_utf8_lossy(&buf).to_string())
        } else {
            std::ffi::OsString::from("localhost")
        }
    }
}

#[must_use]
pub fn cli_proxy_models_url(deployment: &CliProxyDeployment) -> String {
    format!(
        "{}/models",
        deployment.client.base_url.trim_end_matches('/')
    )
}

#[must_use]
pub fn cli_proxy_rich_models_url(deployment: &CliProxyDeployment) -> String {
    format!(
        "{}?client_version=0.144.1",
        cli_proxy_models_url(deployment)
    )
}

pub fn render_cli_proxy_endpoint_template(
    template: &str,
    deployment: &CliProxyDeployment,
) -> Result<String, CliProxyError> {
    if !template.contains(CLI_PROXY_CLIENT_BASE_URL_PLACEHOLDER) {
        return Err(CliProxyError::MissingPlaceholder(
            CLI_PROXY_CLIENT_BASE_URL_PLACEHOLDER.to_string(),
        ));
    }
    Ok(template.replace(
        CLI_PROXY_CLIENT_BASE_URL_PLACEHOLDER,
        &deployment.client.base_url,
    ))
}

pub fn read_preserved_top_level_tail(
    dst: &Path,
    preserve_top_levels: &[String],
) -> Result<String, CliProxyError> {
    if preserve_top_levels.is_empty() {
        return Ok(String::new());
    }

    let existing = match fs::read_to_string(dst) {
        Ok(s) => s,
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => return Ok(String::new()),
        Err(e) => return Err(CliProxyError::Io(e)),
    };

    let mut first_header: Option<usize> = None;

    for top_level in preserve_top_levels {
        let header = format!("[{top_level}");
        let mut offset = 0;
        for line in existing.split_inclusive('\n') {
            let trimmed = line.trim_end_matches('\n').trim_end_matches('\r');
            if trimmed.starts_with(&header) {
                let remainder = trimmed.get(header.len()..).unwrap_or("");
                if remainder.starts_with('.') || remainder.starts_with(']') {
                    first_header = Some(first_header.map_or(offset, |prev| prev.min(offset)));
                    break;
                }
            }
            offset = offset.saturating_add(line.len());
        }
    }

    let Some(header_pos) = first_header else {
        return Ok(String::new());
    };

    let separator_start = if header_pos >= 2
        && existing.get(header_pos.saturating_sub(2)..header_pos) == Some("\r\n")
    {
        header_pos.saturating_sub(2)
    } else if header_pos >= 1
        && existing.get(header_pos.saturating_sub(1)..header_pos) == Some("\n")
    {
        header_pos.saturating_sub(1)
    } else {
        header_pos
    };

    Ok(existing.get(separator_start..).unwrap_or("").to_string())
}

pub fn sync_cli_proxy_endpoint_template(
    src: &Path,
    dst: &Path,
    deployment: &CliProxyDeployment,
    preserve_top_levels: &[String],
) -> Result<(), CliProxyError> {
    let template = fs::read_to_string(src)
        .map_err(|e| CliProxyError::ReadTemplateFailed(src.display().to_string(), e.to_string()))?;

    #[cfg(unix)]
    let mode = {
        fs::metadata(dst)
            .or_else(|_| fs::metadata(src))
            .map_or(0o644, |meta| {
                use std::os::unix::fs::PermissionsExt;
                meta.permissions().mode() & 0o777
            })
    };

    let rendered = render_cli_proxy_endpoint_template(&template, deployment).map_err(|e| {
        CliProxyError::RenderTemplateFailed(
            src.display().to_string(),
            dst.display().to_string(),
            e.to_string(),
        )
    })?;

    let tail = read_preserved_top_level_tail(dst, preserve_top_levels)?;
    let content = format!("{rendered}{tail}");

    if let Some(parent) = dst.parent() {
        fs::create_dir_all(parent)?;
    }

    fs::write(dst, &content).map_err(|e| {
        CliProxyError::RenderTemplateFailed(
            src.display().to_string(),
            dst.display().to_string(),
            e.to_string(),
        )
    })?;

    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        let _ = fs::set_permissions(dst, fs::Permissions::from_mode(mode));
    }

    Ok(())
}

#[must_use]
pub fn is_cli_proxy_target_ready(
    deployment: &CliProxyDeployment,
    fetcher: Option<&dyn EndpointFetcher>,
    timeout: Option<Duration>,
) -> bool {
    let default_fetcher = ReqwestEndpointFetcher::new();
    let actual_fetcher = fetcher.unwrap_or(&default_fetcher);
    let url = cli_proxy_models_url(deployment);
    let timeout_duration = timeout.unwrap_or(ENDPOINT_READY_TIMEOUT);

    match actual_fetcher.fetch_json(&url, timeout_duration) {
        Ok(payload) => {
            if let Some(obj) = payload.as_object()
                && let Some(data) = obj.get("data").and_then(serde_json::Value::as_array)
            {
                return !data.is_empty();
            }
            false
        }
        Err(_) => false,
    }
}

#[derive(Debug)]
enum EndpointTargetSnapshot {
    Missing(PathBuf),
    File {
        path: PathBuf,
        content: String,
        mode: u32,
    },
    Symlink {
        path: PathBuf,
        target: PathBuf,
    },
}

fn snapshot_endpoint_target(path: &Path) -> Result<EndpointTargetSnapshot, CliProxyError> {
    match fs::symlink_metadata(path) {
        Ok(meta) => {
            if meta.is_symlink() {
                let target = fs::read_link(path)?;
                Ok(EndpointTargetSnapshot::Symlink {
                    path: path.to_path_buf(),
                    target,
                })
            } else if meta.is_file() {
                let content = fs::read_to_string(path)?;
                #[cfg(unix)]
                let mode = {
                    use std::os::unix::fs::PermissionsExt;
                    meta.permissions().mode() & 0o777
                };
                #[cfg(not(unix))]
                let mode = 0o644;
                Ok(EndpointTargetSnapshot::File {
                    path: path.to_path_buf(),
                    content,
                    mode,
                })
            } else {
                Err(CliProxyError::Io(std::io::Error::other(format!(
                    "target {} is not a file or symlink",
                    path.display()
                ))))
            }
        }
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => {
            Ok(EndpointTargetSnapshot::Missing(path.to_path_buf()))
        }
        Err(e) => Err(CliProxyError::Io(e)),
    }
}

fn restore_endpoint_snapshots(snapshots: &[EndpointTargetSnapshot]) {
    for snapshot in snapshots {
        match snapshot {
            EndpointTargetSnapshot::Missing(path) => {
                let _ = fs::remove_file(path);
            }
            EndpointTargetSnapshot::File {
                path,
                content,
                mode,
            } => {
                let _ = fs::write(path, content);
                #[cfg(unix)]
                {
                    use std::os::unix::fs::PermissionsExt;
                    let _ = fs::set_permissions(path, fs::Permissions::from_mode(*mode));
                }
            }
            EndpointTargetSnapshot::Symlink { path, target } => {
                let _ = fs::remove_file(path);
                #[cfg(unix)]
                {
                    let _ = std::os::unix::fs::symlink(target, path);
                }
            }
        }
    }
}

pub fn publish_cli_proxy_endpoint_templates(
    targets: &[CliProxyEndpointTarget],
    deployment: &CliProxyDeployment,
    fetcher: Option<&dyn EndpointFetcher>,
    options: &CliProxyEndpointSyncOptions,
) -> Result<CliProxyEndpointPublication, CliProxyError> {
    if targets.is_empty() {
        return Ok(CliProxyEndpointPublication::Published);
    }

    if !options.skip_readiness && !is_cli_proxy_target_ready(deployment, fetcher, options.timeout) {
        return Ok(CliProxyEndpointPublication::Skipped);
    }

    let mut snapshots = Vec::with_capacity(targets.len());
    for target in targets {
        snapshots.push(snapshot_endpoint_target(&target.dst)?);
    }

    for target in targets {
        if let Err(e) = sync_cli_proxy_endpoint_template(
            &target.src,
            &target.dst,
            deployment,
            &target.preserve_top_levels,
        ) {
            restore_endpoint_snapshots(&snapshots);
            return Err(e);
        }
    }

    Ok(CliProxyEndpointPublication::Published)
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;
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

    type MockResponder = Box<dyn Fn(&str) -> Result<serde_json::Value, String> + Send + Sync>;

    struct MockEndpointFetcher {
        responder: MockResponder,
    }

    impl EndpointFetcher for MockEndpointFetcher {
        fn fetch_json(&self, url: &str, _timeout: Duration) -> Result<serde_json::Value, String> {
            (self.responder)(url)
        }
    }

    #[test]
    fn cliproxy_deployment_parses_and_normalizes_endpoint_boundary() {
        let raw = json!({
            "server": { "hostname": "test-gateway" },
            "listen": { "host": "100.64.0.42", "port": 9443 },
            "client": { "baseUrl": "https://gateway.example.test:9443/v1/" }
        });

        let parsed = parse_cli_proxy_deployment(&raw).unwrap();
        assert_eq!(parsed, test_deployment());

        // Unspecified IPv4 / IPv6 addresses rejected
        for host in [
            "0.0.0.0",
            "000.000.000.000",
            "0.0.0",
            "0",
            "0x0",
            "0000000000",
            "::",
            "::0",
            "0::",
            "0:0:0:0:0:0:0:0",
            "0:0::0",
        ] {
            let bad_host = json!({
                "server": { "hostname": "test-gateway" },
                "listen": { "host": host, "port": 9443 },
                "client": { "baseUrl": "https://gateway.example.test:9443/v1" }
            });
            assert!(
                parse_cli_proxy_deployment(&bad_host).is_err(),
                "expected failure for host: {host}"
            );
        }

        // Invalid client URLs rejected
        for url in [
            "https://gateway.example.test:9443/api",
            " https://gateway.example.test:9443/v1",
            "https://gateway.example.test:9443/v1?migrate=true",
            "https://gateway.example.test:9443/v1#fragment",
        ] {
            let bad_url = json!({
                "server": { "hostname": "test-gateway" },
                "listen": { "host": "100.64.0.42", "port": 9443 },
                "client": { "baseUrl": url }
            });
            assert!(
                parse_cli_proxy_deployment(&bad_url).is_err(),
                "expected failure for url: {url}"
            );
        }

        // Unknown fields rejected
        let unknown = json!({
            "server": { "hostname": "test-gateway" },
            "listen": { "host": "100.64.0.42", "port": 9443, "typo": true },
            "client": { "baseUrl": "https://gateway.example.test:9443/v1" }
        });
        assert!(parse_cli_proxy_deployment(&unknown).is_err());
    }

    #[test]
    fn cliproxy_endpoint_template_renders_idempotently() {
        let dir = tempdir().unwrap();
        let src = dir.path().join("source.toml");
        let dst = dir.path().join("generated").join("config.toml");
        let deployment = test_deployment();

        fs::write(
            &src,
            format!("base_url = \"{CLI_PROXY_CLIENT_BASE_URL_PLACEHOLDER}\"\n"),
        )
        .unwrap();

        sync_cli_proxy_endpoint_template(&src, &dst, &deployment, &[]).unwrap();
        assert_eq!(
            fs::read_to_string(&dst).unwrap(),
            "base_url = \"https://gateway.example.test:9443/v1\"\n"
        );

        // Missing placeholder errors
        assert!(render_cli_proxy_endpoint_template("base_url = local\n", &deployment).is_err());
    }

    #[test]
    fn cliproxy_target_readiness_requires_nonempty_models_payload() {
        let deployment = test_deployment();

        let fetcher_empty = MockEndpointFetcher {
            responder: Box::new(|_| Ok(json!({ "data": [] }))),
        };
        assert!(!is_cli_proxy_target_ready(
            &deployment,
            Some(&fetcher_empty),
            None
        ));

        let fetcher_ready = MockEndpointFetcher {
            responder: Box::new(|_| Ok(json!({ "data": [{ "id": "ready" }] }))),
        };
        assert!(is_cli_proxy_target_ready(
            &deployment,
            Some(&fetcher_ready),
            None
        ));
    }

    #[test]
    fn cliproxy_endpoint_publication_requires_ready_target() {
        let dir = tempdir().unwrap();
        let src = dir.path().join("source.toml");
        let dst = dir.path().join("generated").join("config.toml");
        let deployment = test_deployment();

        fs::write(
            &src,
            format!("base_url = \"{CLI_PROXY_CLIENT_BASE_URL_PLACEHOLDER}\"\n"),
        )
        .unwrap();
        fs::create_dir_all(dst.parent().unwrap()).unwrap();
        fs::write(&dst, "base_url = \"old\"\n").unwrap();

        let fetcher_unready = MockEndpointFetcher {
            responder: Box::new(|_| Err("HTTP 503".to_string())),
        };

        let targets = vec![CliProxyEndpointTarget {
            src,
            dst: dst.clone(),
            preserve_top_levels: vec![],
        }];

        let result = publish_cli_proxy_endpoint_templates(
            &targets,
            &deployment,
            Some(&fetcher_unready),
            &CliProxyEndpointSyncOptions::default(),
        )
        .unwrap();

        assert_eq!(result, CliProxyEndpointPublication::Skipped);
        assert_eq!(fs::read_to_string(&dst).unwrap(), "base_url = \"old\"\n");
    }

    #[test]
    fn cliproxy_endpoint_replacement_preserves_top_level_tail() {
        let dir = tempdir().unwrap();
        let src = dir.path().join("source.toml");
        let dst = dir.path().join("generated").join("config.toml");
        let deployment = test_deployment();

        fs::write(
            &src,
            format!("base_url = \"{CLI_PROXY_CLIENT_BASE_URL_PLACEHOLDER}\"\n"),
        )
        .unwrap();
        fs::create_dir_all(dst.parent().unwrap()).unwrap();

        let owned_tail = "\n[hooks.state.\"orchestrator\"]\nspawn_count = 3\n\n[projects.\"~/work/example\"]\nmodel = \"gpt-5.6-sol\"\n";
        let rendered =
            render_cli_proxy_endpoint_template(&fs::read_to_string(&src).unwrap(), &deployment)
                .unwrap();
        fs::write(&dst, format!("{rendered}{owned_tail}")).unwrap();

        let targets = vec![CliProxyEndpointTarget {
            src,
            dst: dst.clone(),
            preserve_top_levels: vec!["hooks.state".to_string(), "projects".to_string()],
        }];

        let fetcher_ready = MockEndpointFetcher {
            responder: Box::new(|_| Ok(json!({ "data": [{ "id": "ready" }] }))),
        };

        let pub_res = publish_cli_proxy_endpoint_templates(
            &targets,
            &deployment,
            Some(&fetcher_ready),
            &CliProxyEndpointSyncOptions::default(),
        )
        .unwrap();

        assert_eq!(pub_res, CliProxyEndpointPublication::Published);
        assert_eq!(
            fs::read_to_string(&dst).unwrap(),
            format!("{rendered}{owned_tail}")
        );
    }
}
