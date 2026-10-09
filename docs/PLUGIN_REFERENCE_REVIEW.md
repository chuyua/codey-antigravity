# Antigravity Reference Plug-in Review

## Scope and provenance

Reference supplied as `codey-Antigravity.zip`. Contains a v0.1.0 Windows/macOS compiled native Codey plugin, sample `config.json`, MIT notice, usage/build/development documentation and a Python 3.9+ stdlib helper. The native Rust source is **not present** in the archive: implementation internals described in its docs cannot be source-audited and compiled DLL/dylib must not be merged into this repository. This is an architectural comparison, not a binary reuse or permission to copy client secrets.

## Design comparison

| Topic | Reference 0.1.0 | This project v0.10.0 | Decision |
| --- | --- | --- | --- |
| Lifecycle | Native plug-in starts an in-process loopback HTTP bridge and stops it with host lifetime | Separate Rust proxy; plugin only describes a Codey route | Keep isolated proxy boundary; document persistent service management to avoid background process dying when terminal closes |
| Credentials | Google refresh token(s) pasted into Codey route key; Base64 multi-account bundle is explicitly not encryption | OAuth tokens saved to a local Pi agent account file and consumed by the Rust proxy, not Codey's API-key field | Retain current isolation and do not copy the reference's embedded desktop OAuth client credentials |
| Config | Single JSON with port, projectId, 8 models, maxConcurrentRequests and requestTimeoutSeconds | JSON route config plus proxy CLI / environment | Set high-port default 28787 consistently; avoid adding unsupported config fields merely to mirror the sample |
| Model catalog | Explicit 8 model list (1 to 32 allowed), manual updates | Authenticated, cached dynamic catalog from Google | Keep authentic discovery; deterministically register up to 32 Codey models, prioritizing valid configured IDs; full catalog stays accessible from proxy API |
| Bounded resources | Documented max 16 concurrent requests, timeout and signature-cache eviction | Rust resource/time limits implemented independently | Preserve limits; no claims of matching their exact internal behavior without source |
| Auxiliary tools | Standard-library Python login, models, usage, search, image and edit CLI | Native proxy CLI and HTTP endpoints | Keep built-in Rust CLI; improve instructions, do not add an unnecessary Python dependency |
| Network | Fixed HTTPS upstream endpoints, no redirects, loopback proxy | Loopback bind plus upstream address / token redaction checks | Preserve URL restrictions and no credential forwarding to arbitrary hosts |
| Platform | Windows x64, macOS arm64 binaries | Windows x64, macOS arm64, Linux x64 CI | Keep Linux support and artifact attestation |

## Configuration contract

```json
{
  "baseUrl": "http://127.0.0.1:28787/v1",
  "models": ["gemini-3.8-flash", "gemini-3.1-pro", "claude-sonnet-4-6", "claude-opus-4-6"],
  "syncModels": true,
  "lifecycleEnabled": true,
  "declareHostCapabilities": false,
  "declareWebsockets": false,
  "routeId": "",
  "retryOnce": false
}
```

Start and authenticate the Rust proxy on this loopback port, then refresh `GET /v1/models?refresh=1` and confirm `GET /v1/models?cached=1` succeeds *before* enabling the native plug-in. Do not disable `syncModels` to mask a broken proxy or an OAuth failure. When the real catalog has more than 32 entries, only 32 can be shown in the native Codey route descriptor; all remain accessible through the proxy API. The chosen 32 are stable while their IDs remain available in the authenticated account catalog. If the account changes and an ID disappears, it is not retained as a phantom model.

## Security and deployment notes

* Bind only 127.0.0.1; protect token files. Do not expose the proxy or its credentials to the LAN or any public endpoint.
* The reference contains a sample OAuth desktop client ID and secret. These are not imported or published by this repo.
* `v0.10.0-rc.1` used legacy port 8787; existing installations do not update just by changing GitHub code. The new Codey native plugin must be re-imported, or its installed configuration changed, and restarted to pick up the new base URL.
* On Windows, use a managed interactive-user scheduled task if the proxy must survive the invoking terminal; do not silently install a privileged service or overwrite an existing task.
* Old 0.9.0 startup tasks and binaries should only be retired after verifying exact executable path, version, port ownership, and a functioning replacement. Never delete Pi agent account files or user data as part of the migration.

## Validation gates

New regression tests cover a 36-item model directory, priority retention, host's 32-model limit, no phantom models, and the high-port default. CI must pass proxy, native ABI, package and isolated installation tests for all available platforms. CI tests do not prove live Google account entitlement or Codey GUI operation.
