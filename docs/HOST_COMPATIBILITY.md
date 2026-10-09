# Codey 宿主兼容说明

本仓库只发布原生插件、SDK 与独立代理。插件默认只输出已发布 Codey 能识别的线路描述字段，因此**不依赖任何宿主 PR** 即可注册线路。`declareHostCapabilities` 控制是否输出 `modelContexts` 与（恒为 `false` 的）压缩/原生搜索标志；`declareWebsockets` 单独控制是否声明 `supportsWebsockets=true`，且必须先打开前者。

已发布 Codey 的 `RouteDescriptor` 使用 `deny_unknown_fields`；描述中出现未识别字段会让 `provider.describe` 失败，从而阻止线路注册。默认省略这些字段可兼容现有宿主。[SuperGness/codey#67](https://github.com/SuperGness/codey/pull/67) 已关闭，本插件默认路径不依赖该 PR。增强字段仅用于明确实现相应契约的其他宿主版本。

## 默认（不依赖宿主改动）

| 行为 | 默认值 |
| --- | --- |
| 线路描述字段 | 仅 `name`、`baseUrl`、`upstreamProtocol`、`models`、`headers`，与已发布宿主一致。 |
| WebSocket | 默认不声明，宿主新建第三方线路与代理握手均默认关闭。增强声明开关及代理 `ANTIGRAVITY_ENABLE_WEBSOCKETS=1` 均需显式开启。 |
| 远程压缩 / 原生搜索 | 默认不声明，宿主新建第三方线路默认关闭；即使打开增强字段也声明为 `false`。代理不提供 compact，模型侧搜索仅 `ANTIGRAVITY_NO_SEARCH_TOOL=0` 启用。 |
| 模型上下文窗口 | 不声明 `modelContexts`；宿主使用其内置窗口。 |
| 模型目录同步 | 依赖 Codey 现有“同步模型”能力：读取代理 `/v1/models`，更新当前线路模型列表。 |

默认描述遵循已发布 Codey 的线路注册接口。升级已有线路时，宿主可能保留用户曾开启的开关；请在这条 Antigravity 线路编辑器中关闭 WebSocket、远程压缩和原生搜索并保存，按界面提示重启。插件不能用额外描述字段覆盖旧宿主配置。模型列表使用宿主现有同步功能；窗口预算下发仍需要下面契约。

## 宿主需要接入的契约

| 契约 | 宿主行为 |
| --- | --- |
| `supportsWebsockets` | 仅对兼容的标准 HTTP Responses 线路接入声明；保留用户能力开关，协议变更时清除不兼容能力。 |
| `supportsRemoteCompaction` / `supportsNativeWebSearch` | 默认 `false`，按线路协议与 transport 校验；Antigravity 当前均声明 `false`。 |
| `modelContexts` | 验证模型键、窗口、输出预留与压缩阈值；接入实际窗口预算并保留用户覆盖优先。未知窗口不声明。 |
| 模型刷新 | 同步上游模型后重新读取插件描述，复核线路 ownership 和 revision；只更新当前线路模型、窗口与能力，保留连接设置。 |
| 过时模型清理 | 删除已过时的插件声明模型，保留独立手动模型及空选择；同步期间防止实例被启停或配置替换。 |

启用 `declareHostCapabilities=true` 前必须先让 Codey 宿主识别这些 SDK/线路描述字段。未识别这些字段的宿主会直接拒绝整份描述。

## 插件与代理的配合

1. 单独启动代理并使用已授权 OAuth 客户端登录。模型目录来自实际 Google 账号和项目，任意 API Key 不能替代该认证。
2. 初次启用前刷新代理 `/v1/models?refresh=1`；默认原生插件只读取 `/v1/models?cached=1`，不在宿主内进行 Google OAuth。
3. 首次目录失败时拒绝线路注册；同一实例已有成功目录后可保留最后目录。模型数量超过 32 时明确报错，不静默截断。
4. 代理 `/v1/models` 提供实际窗口和输出限制；只有打开 `declareHostCapabilities` 时插件才把可确认的元数据写成 `modelContexts`。
5. 新宿主模型同步完成后应移除过时插件模型，并更新当前线路窗口。需在线上 CI 及新宿主中验证完整链路。

## 尚未声明支持的功能

- **Codey 原生 Google 搜索：** `supportsNativeWebSearch=false`。代理显式 `/v1/search` 与 Responses `web_search` 转换已有代码，但 grounding URL annotations 和混合工具完整契约尚未验证。
- **原生远程压缩：** `supportsRemoteCompaction=false`。代理没有提供满足 Codey 要求的 `/responses/compact`（非空 `encrypted_content` 的 compaction 项）实现；保留客户端已有的本地压缩方式。

即使打开 `declareHostCapabilities`，以上两项仍声明 `false`；搜索结果契约与远程压缩实现完成前不会声明为支持。

## 验证与发布边界

独立仓库 CI 验证代理单元测试、mock E2E、SDK、原生 ABI、Windows/Linux/macOS 两种架构的打包和隔离安装；预编译产物另做 ABI、配置拒绝、目录刷新与故障测试。上述 CI 无真实 Google 凭据，真实账号和已发布 Codey 的导入、模型同步与 HTTP 对话需要本地验证。

迁移代码与当前机器已安装的旧二进制是不同状态。只有明确下载并安装对应 CI 产物后，才能开始新插件实测；不要把源码更新或 CI 作业创建当成已安装成功。
