# Codey Antigravity

为 [Codey](https://github.com/SuperGness/codey) 提供 Antigravity 原生线路插件和独立 Rust OAuth 代理。公开源码仓库为 [chuyua/codey-antigravity](https://github.com/chuyua/codey-antigravity)。**代理的实际上游是 [Rahularya01/pi-antigravity](https://github.com/Rahularya01/pi-antigravity)**，迁移基准和选择性移植记录见 [UPSTREAM.md](UPSTREAM.md)。

插件负责向 Codey 声明线路、模型及能力；代理负责 Google 登录、模型发现、协议转换和多账号配额切换。代理需要单独启动，导入 `.codey-plugin` 不会自动安装或启动代理。

## 当前状态

本仓库包含模型目录同步、按账号和项目校验模型、真实窗口元数据以及 Responses WebSocket 能力声明的代码。发布前仍需本仓库线上 CI 通过，并在配合改动后的 Codey 宿主中实测；源码存在不等于已完成安装或真实 Google 验证。

| 功能 | 当前边界 |
| --- | --- |
| 模型同步 | 默认读取已登录代理的真实缓存目录；首次目录不可用时拒绝线路注册，避免回填过时静态模型。 |
| 窗口与输出限制 | 使用上游实际目录元数据；未知窗口不伪造默认值，宿主接入需要配套 PR。 |
| Responses WebSocket | 插件声明 `supportsWebsockets=true`；需要宿主识别该字段，仍待新宿主实测。 |
| Google 搜索 | 代理提供显式 `/v1/search` 和 Responses 搜索转换；Codey 原生搜索声明 `supportsNativeWebSearch=false`，引用与工具契约尚未完整验证。 |
| 原生远程压缩 | 声明 `supportsRemoteCompaction=false`；没有实现 Codey 所需的 `/responses/compact` 加密压缩契约。 |
| 二进制分发 | 当前打包目标为 Windows x64；其他平台只有源码，不声明安装验证已通过。 |

宿主能力、窗口与模型刷新链路单独提交给 Codey，兼容条件及待补充的 PR 链接见 [宿主兼容说明](docs/HOST_COMPATIBILITY.md)。

## 获取和安装

构建、测试与打包由 [GitHub Actions](https://github.com/chuyua/codey-antigravity/actions/workflows/ci.yml) 执行，不要求在本机编译。选择对应提交且 Linux、Windows 两个作业均通过的运行，下载 `antigravity-windows-x64` artifact；排队或运行中的任务不代表可用发布包。

Windows artifact 包含：

- `antigravity-router-0.9.0-windows-x64.codey-plugin`：Codey 原生插件包。
- `codey-antigravity-0.9.0-windows-x64.zip`：代理、原生包、安装脚本、许可、对应源码及校验和。
- `SHA256SUMS`：完整性校验，不替代对发布者的信任判断。

解压便携 ZIP 后按 [INSTALL.md](examples/plugins/antigravity-router/INSTALL.md) 配置授权的 OAuth 客户端、登录、启动代理，再在 Codey 中导入并启用原生插件。初次启用前刷新代理模型目录。线路不需要真实 Google API Key；任意字符串 Key 不能替代 Google 登录。

## 源码与线上验证

| 路径 | 内容 |
| --- | --- |
| `examples/plugins/antigravity-router/src/` | 原生插件。 |
| `examples/plugins/antigravity-router/proxy-rust/` | 独立 Rust 代理及其锁文件。 |
| `crates/codey-plugin-sdk/` | 此插件使用的 SDK 源码；不包含 Codey 宿主程序。 |
| `examples/plugins/antigravity-router/scripts/` | 安装、运行、打包与校验脚本。 |
| `.github/workflows/ci.yml` | Linux 代理测试和 mock E2E；Windows SDK、原生 ABI、代理 E2E、打包与隔离安装测试。 |

CI 只使用临时 mock 账号与随机端口，不需要真实 Google 凭据；因此不能证明账号资格、真实模型配额、Google 网络连通或 Codey UI 行为。构建脚本及对应源码说明见 [BUILDING.md](examples/plugins/antigravity-router/BUILDING.md)。

## 凭据与许可

`ANTIGRAVITY_CLIENT_ID` 和 `ANTIGRAVITY_CLIENT_SECRET` 由当前进程环境传给代理。仓库和发布包不应包含真实客户端凭据、OAuth 回调、API Key、账号文件或用户本机配置；发布包不会复用维护者的登录状态。真实 refresh token 必须与签发它的 OAuth 客户端匹配。

Rust 代理采用 MIT，保留上游作者署名；Codey 原生插件、SDK 和仓库打包工具采用 AGPL-3.0-only。整个插件包不能统一标为 MIT。组件和第三方依赖声明见 [NOTICE.md](examples/plugins/antigravity-router/NOTICE.md) 及构建产物中的许可证目录；根 [LICENSE](LICENSE) 为 AGPL-3.0-only。
