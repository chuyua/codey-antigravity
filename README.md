# Codey Antigravity

[![CI](https://github.com/chuyua/codey-antigravity/actions/workflows/ci.yml/badge.svg)](https://github.com/chuyua/codey-antigravity/actions/workflows/ci.yml) [![Release](https://img.shields.io/github/v/release/chuyua/codey-antigravity?include_prereleases&label=release)](https://github.com/chuyua/codey-antigravity/releases) ![Platforms](https://img.shields.io/badge/platform-Windows%20%7C%20Linux%20%7C%20macOS-blue)

**Native Antigravity provider for Codey · Local Rust OAuth bridge · Multi-platform portable releases.**

为 [Codey](https://github.com/SuperGness/codey) 提供 Antigravity 原生线路插件和独立 Rust OAuth 代理。公开源码仓库为 [chuyua/codey-antigravity](https://github.com/chuyua/codey-antigravity)。**代理的实际上游是 [Rahularya01/pi-antigravity](https://github.com/Rahularya01/pi-antigravity)**，迁移基准和选择性移植记录见 [UPSTREAM.md](UPSTREAM.md)。

插件负责向 Codey 声明线路、模型及能力；代理负责 Google 登录、模型发现、协议转换和多账号配额切换。代理需要单独启动，导入 `.codey-plugin` 不会自动安装或启动代理。

## 为什么选择 Codey Antigravity？

**Codey Antigravity** 为 [Codey](https://github.com/SuperGness/codey) 提供可导入的原生 Antigravity 线路插件，并通过本机 Rust 代理对接 Google Cloud Code Assist / Antigravity 模型。它不是 Pi 插件的直接重命名：本项目采用 Codey 线路接口，按需移植 [pi-antigravity](https://github.com/Rahularya01/pi-antigravity) 的协议行为。

- **本地 OAuth 代理**：浏览器登录、自动刷新及多账号管理；Google 令牌保留在本机，而不是写进 Codey 的 OpenAI Key。
- **模型发现与路由**：从当前已登录账号获取模型目录，按账号/项目校验，并把 Responses 请求转换给上游。
- **工具与诊断**：支持显式搜索、图片生成、用量查询与健康检查；敏感能力默认为关闭或受控启用。
- **多平台**：Windows x64、Linux x64、macOS Apple Silicon (arm64)；**不提供 macOS Intel 包**。

[**下载 Releases**](https://github.com/chuyua/codey-antigravity/releases) · [CI 构建](https://github.com/chuyua/codey-antigravity/actions/workflows/ci.yml) · [安装说明](examples/plugins/antigravity-router/INSTALL.md) · [参考插件设计对比](docs/PLUGIN_REFERENCE_REVIEW.md) · [上游移植记录](UPSTREAM.md) · [问题反馈](https://github.com/chuyua/codey-antigravity/issues)

> **非官方集成。** 与 Google、Codey 上游、pi-antigravity 作者不存在官方隶属或背书关系。OAuth 能否使用取决于账号资格、授权客户端、地区与上游政策；CI 的模拟测试并不代表真实 Google 账号或 GUI 已通过验证。

## 快速开始（Windows）

1. 从 [Releases](https://github.com/chuyua/codey-antigravity/releases) 下载 `codey-antigravity-0.10.0-windows-x64.zip`，校验同平台 `SHA256SUMS`，解压。
2. 在解压目录打开 PowerShell；通过**当前会话环境变量**提供你有权使用的 Google OAuth 客户端凭据（不要把真实值提交到 GitHub）：

```powershell
$env:ANTIGRAVITY_CLIENT_ID = '<authorized-client-id>'
$env:ANTIGRAVITY_CLIENT_SECRET = '<authorized-client-secret>'
.\scripts\install.ps1 -Destination "$env:LOCALAPPDATA\CodeyAntigravity"
Set-Location "$env:LOCALAPPDATA\CodeyAntigravity"
.\bin\antigravity-proxy.exe login --manual
.\start-proxy.ps1
Invoke-RestMethod 'http://127.0.0.1:28787/v1/models?refresh=1'
```

3. 在 **Codey → 插件管理** 中导入 Windows 的 `antigravity-router-0.10.0-windows-x64.codey-plugin`，核对插件 ID 为 `codey.antigravity-router` 及信任提示后**手动启用**。在线路列表选择 Antigravity 模型。代理默认只监听 `127.0.0.1:28787`。
4. 插件导入不会自动启动代理，也不会自动登录。停用插件亦不会自动结束代理进程。


**macOS / Linux：** 使用对应的 arm64 / x64 发行包；解压后按 [安装指南中的 POSIX 流程](examples/plugins/antigravity-router/INSTALL.md#macos--linux) 运行 `./scripts/install.sh`、`./bin/antigravity-proxy login --manual` 和 `./start-proxy.sh`。macOS 发行包未进行 Apple 签名或公证。

## 常用命令和排查

| 操作 | 命令或入口 |
| --- | --- |
| 查看账号 | `antigravity-proxy accounts list` |
| 刷新模型目录 | `GET http://127.0.0.1:28787/v1/models?refresh=1` |
| 查看配额 | `antigravity-proxy usage` |
| 检查代理 | `GET http://127.0.0.1:28787/health` |
| 显式搜索 | `POST http://127.0.0.1:28787/v1/search` |
| 停止 Windows 代理 | `./stop-proxy.ps1` |

上面 `antigravity-proxy` 命令在发行包安装目录下使用 `./bin/antigravity-proxy.exe`（Windows）或 `./bin/antigravity-proxy`（macOS / Linux）。如果模型列表为空，先检查 OAuth 客户端、账号资格和代理模型目录，**不要**用占位 API Key 代替 Google 登录。

## 功能与兼容边界速览

| 模块 | 当前边界 |
| --- | --- |
| 模型同步与多账号切换 | Rust 代理实现，已通过 mock E2E；真实账号需单独验证 |
| Google 搜索 | 显式接口可用；模型侧/宿主原生搜索默认关闭 |
| 图片生成 | 当前 HTTP 与 prompt/aspect-ratio 契约可用；未移植 Pi 原生 image API |
| Responses WebSocket | 代理与宿主均需显式启用，默认关闭 |
| 原生远程压缩 | 不支持 `/responses/compact` 加密压缩协议 |
| 支持平台 | Windows x64、Linux x64、macOS arm64 |

完整限制、宿主兼容性及本次移植范围请阅读 [HOST_COMPATIBILITY.md](docs/HOST_COMPATIBILITY.md) 和 [UPSTREAM.md](UPSTREAM.md)。

## 构建与安全说明

最新代码需通过 [CI](https://github.com/chuyua/codey-antigravity/actions/workflows/ci.yml) 的 Rust、SDK、ABI、mock E2E 与预编译产物隔离安装测试，才能用对应提交的 artifacts 发布。**CI 不验证真实 Google 账号、配额或 Codey UI**。发行包附对应源码、分组件许可和 SHA256 校验。

许可不是统一 MIT：Rust 上游代理部分保留 MIT 署名，Codey 原生插件、SDK 与仓库工具为 AGPL-3.0-only，详见 [NOTICE.md](examples/plugins/antigravity-router/NOTICE.md) 与 [LICENSE](LICENSE)。账号令牌、OAuth 客户端密钥以及用户本机配置绝不可上传到 Issues、提交或发行包。

---

## 当前状态

当前下游代码版本为 **0.10.0**，以 [pi-antigravity v0.10.0](https://github.com/Rahularya01/pi-antigravity/releases/tag/v0.10.0) 作为选择性协议适配基准。版本对齐**不等于 Pi 全部专用能力移植**；详细差异及尚未实现项见 [UPSTREAM.md](UPSTREAM.md#0100-下游版本与完整性边界)。

本仓库包含模型目录同步、按账号和项目校验模型、真实窗口元数据以及可选的 Responses WebSocket 能力声明。插件默认只输出已发布 Codey 能识别的描述字段，不依赖任何宿主 PR 即可注册线路；增强字段需显式打开。每次发布需通过本仓库线上 CI；真实账号、Google 服务连通及 Codey GUI 行为需另行实测，源码存在和 mock CI 通过均不等于已完成真实环境验证。

| 功能 | 当前边界 |
| --- | --- |
| 模型同步 | 默认读取已登录代理的真实缓存目录；Codey 线路上限为 32 个模型，优先保留有效配置模型并按真实目录补齐；完整目录仍在代理 API。首次目录不可用时拒绝注册，不回填过时模型。 |
| 窗口与输出限制 | 默认不声明 `modelContexts`，宿主沿用内置窗口；仅 `declareHostCapabilities=true` 时使用上游真实目录元数据，未知窗口不伪造默认值。 |
| Responses WebSocket | 宿主新建线路与代理握手均默认关闭。代理仅 `ANTIGRAVITY_ENABLE_WEBSOCKETS=1` 时启用；增强字段也需显式开启。升级已有线路需在宿主中关闭曾开启的开关。 |
| Google 搜索 | 宿主原生搜索与代理模型侧搜索默认关闭；增强字段也声明 `false`。代理保留显式 `/v1/search`，模型侧搜索需 `ANTIGRAVITY_NO_SEARCH_TOOL=0` 才启用。 |
| 原生远程压缩 | 宿主默认关闭；增强字段也声明 `false`。没有实现 Codey 所需的 `/responses/compact` 加密压缩契约。 |
| 二进制分发 | 线上 CI 打包 Windows x64、macOS arm64 与 Linux x64；不提供 macOS Intel 包。真实账号与宿主验证另行记录。 |

默认路径与已发布 Codey 兼容，不依赖已关闭的宿主 PR #67。宿主窗口下发属于可选增强，限制与已有线路升级步骤见 [宿主兼容说明](docs/HOST_COMPATIBILITY.md)。

## 获取和安装

构建、测试与打包由 [GitHub Actions](https://github.com/chuyua/codey-antigravity/actions/workflows/ci.yml) 执行，不要求在本机编译。选择对应提交且 Linux、Windows、macOS 作业均通过的运行，下载对应 artifact；排队或运行中的任务不代表可用发布包。

各平台 artifact 包含：

- `antigravity-router-0.10.0-<platform>-<arch>.codey-plugin`：Codey 原生插件包。
- `codey-antigravity-0.10.0-<platform>-<arch>.zip`：代理、原生包、安装脚本、许可、对应源码及校验和。
- `SHA256SUMS`：完整性校验，不替代对发布者的信任判断。

解压便携 ZIP 后按 [INSTALL.md](examples/plugins/antigravity-router/INSTALL.md) 配置授权的 OAuth 客户端、登录、启动代理，再在 Codey 中导入并启用原生插件。初次启用前刷新代理模型目录。线路不需要真实 Google API Key；任意字符串 Key 不能替代 Google 登录。

## 源码与线上验证

| 路径 | 内容 |
| --- | --- |
| `examples/plugins/antigravity-router/src/` | 原生插件。 |
| `examples/plugins/antigravity-router/proxy-rust/` | 独立 Rust 代理及其锁文件。 |
| `crates/codey-plugin-sdk/` | 此插件使用的 SDK 源码；不包含 Codey 宿主程序。 |
| `examples/plugins/antigravity-router/scripts/` | 安装、运行、打包与校验脚本。 |
| `.github/workflows/ci.yml` | Linux 代理测试与 mock E2E；Windows x64、Linux x64、macOS arm64 分别执行 SDK、原生 ABI、代理 E2E、打包与隔离安装测试。 |

CI 只使用临时 mock 账号与随机端口，不需要真实 Google 凭据；因此不能证明账号资格、真实模型配额、Google 网络连通或 Codey UI 行为。构建脚本及对应源码说明见 [BUILDING.md](examples/plugins/antigravity-router/BUILDING.md)。

下载 CI artifact、核对外层 `SHA256SUMS` 并解压便携 ZIP 后，可运行 `python examples/plugins/antigravity-router/scripts/test-artifact.py <解压后的便携目录>`。该入口使用包内实际二进制检查 C ABI、默认描述、配置拒绝、模型刷新与故障回退，执行完整 mock E2E 和隔离安装/启停防护；全程不运行 Cargo 或本地编译器。各平台 CI 使用同一入口。真实宿主和账号的验证另行记录，不能由 mock 测试代替。

## 凭据与许可

`ANTIGRAVITY_CLIENT_ID` 和 `ANTIGRAVITY_CLIENT_SECRET` 由当前进程环境传给代理。仓库和发布包不应包含真实客户端凭据、OAuth 回调、API Key、账号文件或用户本机配置；发布包不会复用维护者的登录状态。真实 refresh token 必须与签发它的 OAuth 客户端匹配。

Rust 代理采用 MIT，保留上游作者署名；Codey 原生插件、SDK 和仓库打包工具采用 AGPL-3.0-only。整个插件包不能统一标为 MIT。组件和第三方依赖声明见 [NOTICE.md](examples/plugins/antigravity-router/NOTICE.md) 及构建产物中的许可证目录；根 [LICENSE](LICENSE) 为 AGPL-3.0-only。
