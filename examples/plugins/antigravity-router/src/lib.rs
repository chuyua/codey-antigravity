//! Declarative loopback route; lifecycle control is opt-in and scoped to a host route ID.
use codey_plugin_sdk::{
    Plugin, PluginContext,
    serde_json::{Value, json},
};
use std::{
    collections::BTreeMap,
    io::{Read, Write},
    net::{SocketAddr, TcpStream},
    time::{Duration, Instant},
};
const MARKER: &str = "x-antigravity-provider";
const DEFAULT_MODELS: &[&str] = &[
    "gemini-3.8-flash",
    "gemini-3.1-pro",
    "claude-sonnet-4-6",
    "claude-opus-4-6",
];
struct AntigravityRouter {
    lifecycle_enabled: bool,
    base_url: String,
    models: Vec<String>,
    model_contexts: BTreeMap<String, codey_plugin_sdk::provider::ModelContext>,
    model_reasoning_efforts: BTreeMap<String, Vec<String>>,
    declare_host_capabilities: bool,
    declare_websockets: bool,
    route_id: String,
    retry_once: bool,
    sync_models: bool,
    catalog_source: &'static str,
    context: PluginContext,
}
fn safe_models(models: &[String], maximum: usize) -> bool {
    let mut seen = std::collections::HashSet::new();
    !models.is_empty()
        && models.len() <= maximum
        && models.iter().all(|m| {
            !m.is_empty()
                && m.len() <= 128
                && m.bytes()
                    .all(|b| b.is_ascii_alphanumeric() || b"-_.".contains(&b))
                && !m.eq_ignore_ascii_case("codex-auto-review")
                && seen.insert(m.to_ascii_lowercase())
        })
}
// Only the already validated numeric loopback port is used. No DNS, system
// proxy, redirects or OAuth occur inside the host process.
fn cached_catalog(
    base_url: &str,
    preferred_models: &[String],
) -> Result<
    (
        Vec<String>,
        BTreeMap<String, codey_plugin_sdk::provider::ModelContext>,
        BTreeMap<String, Vec<String>>,
        usize,
        usize,
    ),
    &'static str,
> {
    let port: u16 = base_url
        .strip_prefix("http://127.0.0.1:")
        .and_then(|s| s.strip_suffix("/v1"))
        .and_then(|s| s.parse().ok())
        .ok_or("invalid_base_url")?;
    let deadline = Instant::now() + Duration::from_secs(2);
    let mut stream = TcpStream::connect_timeout(
        &SocketAddr::from(([127, 0, 0, 1], port)),
        Duration::from_millis(300),
    )
    .map_err(|_| "connect_failed")?;
    let remaining = || {
        deadline
            .checked_duration_since(Instant::now())
            .filter(|d| !d.is_zero())
            .ok_or("timeout")
    };
    stream
        .set_write_timeout(Some(remaining()?))
        .map_err(|_| "timeout_setup")?;
    write!(stream, "GET /v1/models?cached=1 HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nConnection: close\r\nAccept: application/json\r\n\r\n").map_err(|_| "write_failed")?;
    const LIMIT: usize = 1024 * 1024;
    let mut response = Vec::new();
    let mut buffer = [0; 8192];
    let mut expected = None;
    loop {
        stream
            .set_read_timeout(Some(remaining()?))
            .map_err(|_| "timeout_setup")?;
        let n = stream.read(&mut buffer).map_err(|_| "read_failed")?;
        if n == 0 {
            break;
        }
        if response.len() + n > LIMIT {
            return Err("response_too_large");
        }
        response.extend_from_slice(&buffer[..n]);
        if expected.is_none() {
            if let Some(end) = response.windows(4).position(|w| w == b"\r\n\r\n") {
                if end > 16384 {
                    return Err("headers_too_large");
                }
                let header =
                    std::str::from_utf8(&response[..end]).map_err(|_| "invalid_headers")?;
                let mut lines = header.split("\r\n");
                if !matches!(lines.next(), Some("HTTP/1.1 200 OK" | "HTTP/1.0 200 OK")) {
                    return Err("catalog_unavailable");
                }
                let mut length = None;
                for line in lines {
                    let (name, value) = line.split_once(':').ok_or("invalid_headers")?;
                    if name.eq_ignore_ascii_case("transfer-encoding") {
                        return Err("unsupported_encoding");
                    }
                    if name.eq_ignore_ascii_case("content-length") {
                        if length.is_some() {
                            return Err("invalid_headers");
                        }
                        length = Some(
                            value
                                .trim()
                                .parse::<usize>()
                                .map_err(|_| "invalid_length")?,
                        );
                    }
                }
                let total = (end + 4)
                    .checked_add(length.ok_or("missing_length")?)
                    .filter(|n| *n <= LIMIT)
                    .ok_or("response_too_large")?;
                expected = Some((end + 4, total));
            } else if response.len() > 16384 {
                return Err("headers_too_large");
            }
        }
        if expected.is_some_and(|(_, total)| response.len() >= total) {
            break;
        }
    }
    let (start, total) = expected.ok_or("invalid_response")?;
    if response.len() != total {
        return Err("invalid_length");
    }
    let catalog: Value =
        codey_plugin_sdk::serde_json::from_slice(&response[start..]).map_err(|_| "invalid_json")?;
    let data = catalog
        .get("data")
        .and_then(Value::as_array)
        .ok_or("invalid_catalog")?;
    let models = data
        .iter()
        .map(|m| {
            m.get("id")
                .and_then(Value::as_str)
                .map(str::to_owned)
                .ok_or("invalid_catalog")
        })
        .collect::<Result<Vec<_>, _>>()?;
    // Validate the complete authenticated catalog, then keep only the model IDs
    // explicitly declared in plugin configuration. The proxy retains all models.
    if !safe_models(&models, 256) {
        return Err("invalid_model_ids");
    }
    let visible = select_host_models(&models, preferred_models);
    if visible.is_empty() {
        return Err("configured_models_unavailable");
    }
    let mut contexts = BTreeMap::new();
    let mut reasoning_efforts = BTreeMap::new();
    let mut ignored_budgets = 0;
    for (model, entry) in models.iter().zip(data) {
        if visible.contains(model) {
            match catalog_context(entry) {
                Ok(Some(context)) => {
                    contexts.insert(model.clone(), context);
                }
                Ok(None) => {}
                Err(_) => {
                    // Context budgets are OPTIONAL metadata. Never let malformed
                    // upstream window/output limits block valid model IDs.
                    ignored_budgets += 1;
                }
            }
            if let Some(levels) = catalog_reasoning_efforts(entry) {
                reasoning_efforts.insert(model.clone(), levels);
            }
        }
    }
    let total = models.len();
    Ok((visible, contexts, reasoning_efforts, total, ignored_budgets))
}

// models is the plugin declaration/allow-list. Synchronization validates that
// each declared id still exists in the authenticated account catalog; it does
// not append unrelated upstream models.
fn select_host_models(catalog: &[String], configured: &[String]) -> Vec<String> {
    configured
        .iter()
        .filter(|model| catalog.contains(model))
        .cloned()
        .collect()
}

fn catalog_reasoning_efforts(entry: &Value) -> Option<Vec<String>> {
    const ALLOWED: &[&str] = &["low", "medium", "high", "xhigh", "max", "ultra"];
    let levels = entry.get("reasoning_efforts")?.as_array()?;
    let mut result = Vec::new();
    for value in levels {
        let level = value.as_str()?;
        if ALLOWED.contains(&level) && !result.iter().any(|existing| existing == level) {
            result.push(level.to_string());
        }
    }
    (!result.is_empty()).then_some(result)
}

fn catalog_context(
    entry: &Value,
) -> Result<Option<codey_plugin_sdk::provider::ModelContext>, &'static str> {
    let token = |key: &str| -> Result<Option<u64>, &'static str> {
        entry
            .get(key)
            .map(|v| v.as_u64().filter(|n| *n > 0).ok_or("invalid_model_budget"))
            .transpose()
    };
    let snake = token("context_window")?;
    let camel = token("contextWindow")?;
    if snake.zip(camel).is_some_and(|(a, b)| a != b) {
        return Err("conflicting_model_budget");
    }
    let reserve = token("max_output_tokens")?;
    let Some(window) = snake.or(camel) else {
        // An unknown window cannot be inferred from a model name or output limit.
        return Ok(None);
    };
    if !(1_024..=10_000_000).contains(&window)
        || reserve.is_some_and(|n| n >= window || (window - n) * 100 / window == 0)
    {
        return Err("invalid_model_budget");
    }
    // Match the host's percent-rounded effective window and preserve upstream
    // output headroom. Remote compression capability is a separate contract.
    let effective = window * ((window - reserve.unwrap_or(0)) * 100 / window) / 100;
    Ok(Some(codey_plugin_sdk::provider::ModelContext {
        context_window: window,
        auto_compact_token_limit: effective.min(window * 9 / 10),
        reserve_output_tokens: reserve,
    }))
}
impl Plugin for AntigravityRouter {
    fn create(config: Value, context: PluginContext) -> Result<Self, String> {
        let object = config
            .as_object()
            .ok_or("configuration must be an object")?;
        for key in object.keys() {
            if ![
                "lifecycleEnabled",
                "enabled",
                "baseUrl",
                "models",
                "routeId",
                "retryOnce",
                "syncModels",
                "declareHostCapabilities",
                "declareWebsockets",
                "_comments",
            ]
            .contains(&key.as_str())
            {
                return Err(format!("unknown configuration field: {key}"));
            }
        }
        let bool_field = |name: &str, default: bool| -> Result<bool, String> {
            match config.get(name) {
                None => Ok(default),
                Some(v) => v
                    .as_bool()
                    .ok_or_else(|| format!("{name} must be a boolean")),
            }
        };
        let legacy_enabled = bool_field("enabled", true)?;
        let lifecycle_enabled = bool_field("lifecycleEnabled", legacy_enabled)?;
        if config.get("enabled").is_some()
            && config.get("lifecycleEnabled").is_some()
            && lifecycle_enabled != legacy_enabled
        {
            return Err(
                "enabled and lifecycleEnabled disagree; remove the deprecated enabled field".into(),
            );
        }
        let retry_once = bool_field("retryOnce", false)?;
        let sync_models = bool_field("syncModels", true)?;
        // Both default off. A stock Codey host uses `deny_unknown_fields`, so any
        // capability field it does not recognize blocks route registration.
        // `declareHostCapabilities` enables `modelContexts`; `declareWebsockets`
        // additionally enables the Responses WebSocket capability flag. Remote
        // compaction and native Web Search are never declared true.
        let declare_host_capabilities = bool_field("declareHostCapabilities", false)?;
        let declare_websockets = bool_field("declareWebsockets", false)?;
        if declare_websockets && !declare_host_capabilities {
            return Err(
                "declareWebsockets requires declareHostCapabilities: the host must already accept the capability fields".into(),
            );
        }
        let base_url = config
            .get("baseUrl")
            .map(|v| v.as_str().ok_or("baseUrl must be a string"))
            .transpose()?
            .unwrap_or("http://127.0.0.1:28787/v1")
            .to_string();
        let port = base_url
            .strip_prefix("http://127.0.0.1:")
            .and_then(|v| v.strip_suffix("/v1"))
            .ok_or("baseUrl must be http://127.0.0.1:<port>/v1")?;
        let parsed = port.parse::<u16>().map_err(|_| "invalid loopback port")?;
        if parsed == 0 || parsed.to_string() != port {
            return Err("invalid loopback port".into());
        }
        let models: Vec<String> = match config.get("models") {
            None => DEFAULT_MODELS.iter().map(|s| s.to_string()).collect(),
            Some(value) => value
                .as_array()
                .ok_or("models must be an array")?
                .iter()
                .map(|v| {
                    v.as_str()
                        .map(str::to_owned)
                        .ok_or("models must contain strings")
                })
                .collect::<Result<_, _>>()?,
        };
        if !safe_models(&models, 32) {
            return Err("models require 1..32 distinct safe IDs".into());
        }
        let route_id = config
            .get("routeId")
            .map(|v| v.as_str().ok_or("routeId must be a string"))
            .transpose()?
            .unwrap_or("")
            .to_string();
        if route_id.len() > 128
            || route_id
                .bytes()
                .any(|b| !b.is_ascii_alphanumeric() && !b"-_.".contains(&b))
        {
            return Err("invalid routeId".into());
        }
        if retry_once && route_id.is_empty() {
            return Err("retryOnce requires an explicit routeId".into());
        }
        context.log("antigravity_router_created")?;
        Ok(Self {
            lifecycle_enabled,
            base_url,
            models,
            model_contexts: BTreeMap::new(),
            model_reasoning_efforts: BTreeMap::new(),
            declare_host_capabilities,
            declare_websockets,
            route_id,
            retry_once,
            sync_models,
            catalog_source: "configuration",
            context,
        })
    }
    fn invoke(&mut self, method: &str, params: Value) -> Result<Value, String> {
        let ours = self.lifecycle_enabled
            && !self.route_id.is_empty()
            && params.pointer("/metadata/routeId").and_then(Value::as_str)
                == Some(self.route_id.as_str());
        match method {
            "provider.describe" => {
                if self.sync_models {
                    match cached_catalog(&self.base_url, &self.models) {
                        Ok((models, contexts, reasoning_efforts, available, ignored_budgets)) => {
                            if ignored_budgets > 0 {
                                let _ = self.context.log(&format!(
                                    "antigravity_invalid_optional_model_budgets:{ignored_budgets}"
                                ));
                            }
                            if available > models.len() {
                                let _ = self.context.log(&format!(
                                    "antigravity_catalog_filtered: showing {} configured of {available} authenticated models",
                                    models.len()
                                ));
                            }
                            self.models = models;
                            self.model_contexts = contexts;
                            self.model_reasoning_efforts = reasoning_efforts;
                            self.catalog_source = "proxy-cache";
                        }
                        Err(code) => {
                            let _ = self
                                .context
                                .log(&format!("antigravity_catalog_unavailable:{code}"));
                            if self.catalog_source != "proxy-cache" {
                                return Err(format!(
                                    "Antigravity model catalog unavailable ({code}); start the proxy and refresh its authenticated model catalog before enabling the plugin. Set syncModels=false only to deliberately use a maintained manual model list."
                                ));
                            }
                        }
                    }
                }
                // Stock Codey cannot read these fields and rejects the whole
                // descriptor, so nothing is advertised unless the user opts in.
                // Remote compaction and native Web Search are never declared.
                let mut route = json!({
                    "name": "Antigravity",
                    "baseUrl": self.base_url,
                    "upstreamProtocol": "openaiResponses",
                    "models": self.models,
                    "headers": [{"name": MARKER, "value": "codey-antigravity"}],
                });
                if !self.model_reasoning_efforts.is_empty() {
                    route.as_object_mut().expect("route object").insert(
                        "modelReasoningEfforts".into(),
                        codey_plugin_sdk::serde_json::to_value(&self.model_reasoning_efforts)
                            .map_err(|error| error.to_string())?,
                    );
                }
                if self.declare_host_capabilities {
                    let object = route.as_object_mut().expect("route object");
                    object.insert(
                        "modelContexts".into(),
                        codey_plugin_sdk::serde_json::to_value(&self.model_contexts)
                            .map_err(|error| error.to_string())?,
                    );
                    object.insert("supportsRemoteCompaction".into(), json!(false));
                    object.insert("supportsNativeWebSearch".into(), json!(false));
                    object.insert("supportsWebsockets".into(), json!(self.declare_websockets));
                }
                Ok(route)
            }
            "request.beforeSend" => {
                if ours {
                    Ok(
                        json!({"action":"continue","headers":[{"name":MARKER,"value":"codey-antigravity"}]}),
                    )
                } else {
                    Ok(json!({"action":"continue"}))
                }
            }
            "request.afterHeaders" => {
                if !ours || params.pointer("/response/status").and_then(Value::as_u64) != Some(429)
                {
                    return Ok(json!({"action":"continue"}));
                }
                if self.retry_once && params.get("attempt").and_then(Value::as_u64) == Some(0) {
                    return Ok(json!({"action":"retry"}));
                }
                Ok(
                    json!({"action":"abort","status":429,"code":"antigravity_quota_exhausted","message":"Antigravity quota exhausted. Try later or select another Google account."}),
                )
            }
            "request.completed" | "request.failed" | "request.cancelled" => Ok(json!({})),
            "ping" => Ok(
                json!({"plugin":"antigravity-router","version":"0.10.0","lifecycleEnabled":self.lifecycle_enabled,"syncModels":self.sync_models,"declareHostCapabilities":self.declare_host_capabilities,"declareWebsockets":self.declare_websockets,"catalogSource":self.catalog_source}),
            ),
            _ => Err(format!("unknown method: {method}")),
        }
    }
}
codey_plugin_sdk::export_plugin!(AntigravityRouter);

#[cfg(test)]
mod tests {
    use super::*;

    fn router(config: Value) -> (AntigravityRouter, tempfile::TempDir) {
        let dir = tempfile::tempdir().unwrap();
        let context = PluginContext {
            plugin_id: "codey.antigravity-router".into(),
            plugin_dir: dir.path().into(),
            data_dir: dir.path().into(),
            log_dir: dir.path().into(),
        };
        (AntigravityRouter::create(config, context).unwrap(), dir)
    }

    #[test]
    fn stock_route_omits_capability_fields_and_does_not_intercept_lifecycle_requests() {
        let (mut router, _dir) = router(json!({"syncModels":false}));
        let route = router.invoke("provider.describe", json!({})).unwrap();
        assert_eq!(route["upstreamProtocol"], "openaiResponses");
        // Stock Codey rejects unknown descriptor fields, so the default output
        // must stay within the released schema.
        for field in [
            "supportsWebsockets",
            "supportsRemoteCompaction",
            "supportsNativeWebSearch",
            "modelContexts",
        ] {
            assert!(
                route.get(field).is_none(),
                "{field} must not be default-visible"
            );
        }
        let _: codey_plugin_sdk::provider::RouteDescriptor =
            codey_plugin_sdk::serde_json::from_value(route.clone()).unwrap();
        assert_eq!(route["headers"][0]["name"], MARKER);
        assert_eq!(route["headers"][0]["value"], "codey-antigravity");
        assert_eq!(
            router
                .invoke(
                    "request.beforeSend",
                    json!({"metadata":{"routeId":"other"}})
                )
                .unwrap(),
            json!({"action":"continue"})
        );
        assert!(router.invoke("unknown.method", json!({})).is_err());
    }

    #[test]
    fn opting_into_host_capabilities_advertises_only_contexts_and_no_native_claims() {
        let (mut router, _dir) = router(json!({"syncModels":false,"declareHostCapabilities":true}));
        let route = router.invoke("provider.describe", json!({})).unwrap();
        assert!(route["modelContexts"].is_object());
        // Remote compaction, native search and WebSocket stay off by default.
        assert_eq!(route["supportsRemoteCompaction"], false);
        assert_eq!(route["supportsNativeWebSearch"], false);
        assert_eq!(route["supportsWebsockets"], false);
        let _: codey_plugin_sdk::provider::RouteDescriptor =
            codey_plugin_sdk::serde_json::from_value(route).unwrap();
        assert_eq!(
            router.invoke("ping", json!({})).unwrap()["declareHostCapabilities"],
            true
        );
    }

    #[test]
    fn websockets_require_an_explicit_opt_in_with_host_capabilities() {
        let (mut router, _dir) = router(
            json!({"syncModels":false,"declareHostCapabilities":true,"declareWebsockets":true}),
        );
        let route = router.invoke("provider.describe", json!({})).unwrap();
        assert_eq!(route["supportsWebsockets"], true);
        assert_eq!(
            router.invoke("ping", json!({})).unwrap()["declareWebsockets"],
            true
        );
        // Enabling WebSocket transport without the descriptor contract is rejected.
        let dir = tempfile::tempdir().unwrap();
        let context = PluginContext {
            plugin_id: "codey.antigravity-router".into(),
            plugin_dir: dir.path().into(),
            data_dir: dir.path().into(),
            log_dir: dir.path().into(),
        };
        let error = AntigravityRouter::create(
            json!({"syncModels":false,"declareWebsockets":true}),
            context,
        )
        .err()
        .expect("WebSocket declaration requires a compatible host");
        assert!(error.contains("declareHostCapabilities"), "{error}");
    }

    #[test]
    fn scoped_headers_and_retry_are_limited_to_selected_route_and_attempt() {
        let (mut router, _dir) = router(json!({"routeId":"ours","retryOnce":true}));
        assert_eq!(
            router
                .invoke("request.beforeSend", json!({"metadata":{"routeId":"ours"}}))
                .unwrap()["headers"][0]["name"],
            MARKER
        );
        for (route, status, attempt, action) in [
            ("other", 429, 0, "continue"),
            ("ours", 200, 0, "continue"),
            ("ours", 429, 0, "retry"),
            ("ours", 429, 1, "abort"),
        ] {
            assert_eq!(router.invoke("request.afterHeaders", json!({"metadata":{"routeId":route},"response":{"status":status},"attempt":attempt})).unwrap()["action"], action);
        }
    }

    fn catalog_server(body: Value) -> (String, std::thread::JoinHandle<()>) {
        let listener = std::net::TcpListener::bind(("127.0.0.1", 0)).unwrap();
        let base = format!(
            "http://127.0.0.1:{}/v1",
            listener.local_addr().unwrap().port()
        );
        let task = std::thread::spawn(move || {
            let (mut stream, _) = listener.accept().unwrap();
            stream
                .set_read_timeout(Some(Duration::from_secs(3)))
                .unwrap();
            let mut input = Vec::new();
            let mut byte = [0; 1];
            while !input.ends_with(b"\r\n\r\n") {
                stream.read_exact(&mut byte).unwrap();
                input.push(byte[0]);
            }
            assert!(input.starts_with(b"GET /v1/models?cached=1 HTTP/1.1\r\n"));
            let body = body.to_string();
            write!(
                stream,
                "HTTP/1.1 200 OK\r\nContent-Length: {}\r\n\r\n{body}",
                body.len()
            )
            .unwrap();
        });
        (base, task)
    }

    #[test]
    fn cached_model_sync_keeps_exact_declaration_and_last_good_fallback() {
        let (base, task) = catalog_server(json!({"data":[
            {"id":"unrelated-model","reasoning_efforts":["xhigh"]},
            {"id":"gemini-future","reasoning_efforts":["low","high"]}
        ]}));
        let (mut router, _dir) = router(json!({"baseUrl":base,"models":["gemini-future"]}));
        let route = router.invoke("provider.describe", json!({})).unwrap();
        assert_eq!(route["models"], json!(["gemini-future"]));
        assert_eq!(
            route["modelReasoningEfforts"]["gemini-future"],
            json!(["low", "high"])
        );
        assert!(
            route["modelReasoningEfforts"]
                .get("unrelated-model")
                .is_none()
        );
        task.join().unwrap();
        assert_eq!(
            router.invoke("ping", json!({})).unwrap()["catalogSource"],
            "proxy-cache"
        );
        assert_eq!(
            router.invoke("provider.describe", json!({})).unwrap()["models"],
            json!(["gemini-future"])
        );
    }

    #[test]
    fn known_catalog_budgets_sync_without_inventing_unknown_windows() {
        let (base, task) = catalog_server(json!({"data":[
            {"id":"gemini-known","context_window":524288,"contextWindow":524288,"max_output_tokens":12345},
            {"id":"unknown","max_output_tokens":8192}
        ]}));
        let (mut router, _dir) = router(json!({
            "baseUrl":base,
            "models":["gemini-known","unknown"],
            "declareHostCapabilities":true
        }));
        let route = router.invoke("provider.describe", json!({})).unwrap();
        task.join().unwrap();
        let context = &route["modelContexts"]["gemini-known"];
        assert_eq!(context["contextWindow"], 524288);
        assert_eq!(context["reserveOutputTokens"], 12345);
        assert_eq!(context["autoCompactTokenLimit"], 524288 * 9 / 10);
        assert!(route["modelContexts"].get("unknown").is_none());
        assert_eq!(
            router.invoke("provider.describe", json!({})).unwrap()["modelContexts"],
            route["modelContexts"]
        );
        let _: codey_plugin_sdk::provider::RouteDescriptor =
            codey_plugin_sdk::serde_json::from_value(route).unwrap();
    }

    #[test]
    fn budgets_reserve_output_headroom_and_reject_invalid_metadata() {
        let context = catalog_context(&json!({"contextWindow":200000,"max_output_tokens":100000}))
            .unwrap()
            .unwrap();
        assert_eq!(context.auto_compact_token_limit, 100000);
        assert!(catalog_context(&json!({})).unwrap().is_none());
        for value in [
            json!({"contextWindow":0}),
            json!({"contextWindow":"200000"}),
            json!({"contextWindow":1023}),
            json!({"contextWindow":10000001}),
            json!({"contextWindow":200000,"context_window":100000}),
            json!({"contextWindow":200000,"max_output_tokens":200000}),
            json!({"contextWindow":200000,"max_output_tokens":199999}),
            json!({"contextWindow":200000,"max_output_tokens":0}),
        ] {
            assert!(catalog_context(&value).is_err(), "{value}");
        }
    }

    #[test]
    fn malformed_optional_budgets_do_not_block_authenticated_models() {
        let (base, task) = catalog_server(json!({"data":[
            {"id":"gemini-valid","context_window":200000,"max_output_tokens":12000},
            {"id":"gemini-overstated","context_window":1048576,"max_output_tokens":1048576},
            {"id":"claude-overstated","context_window":200000,"max_output_tokens":250000}
        ]}));
        let (mut router, _dir) = router(json!({
            "baseUrl":base,
            "models":["gemini-valid","gemini-overstated","claude-overstated"],
            "declareHostCapabilities":true
        }));
        let route = router.invoke("provider.describe", json!({})).unwrap();
        task.join().unwrap();
        assert_eq!(route["models"].as_array().unwrap().len(), 3);
        assert!(route["modelContexts"].get("gemini-valid").is_some());
        assert!(route["modelContexts"].get("gemini-overstated").is_none());
        assert!(route["modelContexts"].get("claude-overstated").is_none());
        let _: codey_plugin_sdk::provider::RouteDescriptor =
            codey_plugin_sdk::serde_json::from_value(route).unwrap();
    }

    #[test]
    fn invalid_catalog_never_reintroduces_configured_models_when_syncing() {
        for body in [
            json!({"data":[]}),
            json!({"data":[{"id":"bad\nheader"}]}),
            json!({"data":[{"id":"A"},{"id":"a"}]}),
        ] {
            let (base, task) = catalog_server(body);
            let (mut router, _dir) = router(json!({"baseUrl":base,"models":["gemini-fallback"]}));
            assert!(router.invoke("provider.describe", json!({})).is_err());
            assert_eq!(
                router.invoke("ping", json!({})).unwrap()["catalogSource"],
                "configuration"
            );
            task.join().unwrap();
        }
    }

    #[test]
    fn large_catalog_exposes_only_declared_live_models() {
        let mut entries: Vec<Value> = (0..35)
            .map(|i| json!({"id": format!("model-{i}")}))
            .collect();
        entries.push(json!({
            "id":"gemini-important",
            "context_window":524288,
            "reasoning_efforts":["low","medium","high"]
        }));
        let (base, task) = catalog_server(json!({"data":entries}));
        let (mut router, _dir) = router(json!({
            "baseUrl":base,
            "models":["gemini-important","model-34","model-0"],
            "declareHostCapabilities":true
        }));
        let route = router.invoke("provider.describe", json!({})).unwrap();
        task.join().unwrap();
        let visible = route["models"].as_array().unwrap();
        assert_eq!(
            visible,
            &vec![
                json!("gemini-important"),
                json!("model-34"),
                json!("model-0")
            ]
        );
        assert_eq!(
            route["modelContexts"]["gemini-important"]["contextWindow"],
            524288
        );
        assert_eq!(
            route["modelReasoningEfforts"]["gemini-important"],
            json!(["low", "medium", "high"])
        );
        let _: codey_plugin_sdk::provider::RouteDescriptor =
            codey_plugin_sdk::serde_json::from_value(route).unwrap();
    }

    #[test]
    fn synchronized_models_must_remain_in_current_authenticated_catalog() {
        let models = vec!["gemini-live".into(), "claude-live".into()];
        let preferred = vec!["retired-model".into(), "claude-live".into()];
        assert_eq!(select_host_models(&models, &preferred), vec!["claude-live"]);
    }

    #[test]
    fn missing_proxy_requires_explicit_manual_catalog_opt_out() {
        let listener = std::net::TcpListener::bind(("127.0.0.1", 0)).unwrap();
        let base = format!(
            "http://127.0.0.1:{}/v1",
            listener.local_addr().unwrap().port()
        );
        drop(listener);
        let (mut synced, _dir) = router(json!({"baseUrl":base,"models":["retired-model"]}));
        assert!(synced.invoke("provider.describe", json!({})).is_err());
        let (mut manual, _dir) =
            router(json!({"baseUrl":base,"syncModels":false,"models":["maintained-model"]}));
        assert_eq!(
            manual.invoke("provider.describe", json!({})).unwrap()["models"],
            json!(["maintained-model"])
        );
    }
}
