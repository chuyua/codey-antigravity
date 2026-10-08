# Codey 宿主兼容说明

本仓库只发布原生插件、SDK 与独立代理。Codey 宿主的配合改动单独向 [SuperGness/codey](https://github.com/SuperGness/codey) 提交，不把整个 Antigravity 代理加入宿主仓库。

**宿主 PR 链接：[SuperGness/codey#67](https://github.com/SuperGness/codey/pull/67)。** 在 PR 的相关代码合入或用于测试构建前，不声明现有稳定版 Codey 已支持以下增强，也不依据插件包版本猜测宿主兼容性。

## 宿主需要接入的契约

| 契约 | 宿主行为 |
| --- | --- |
| `supportsWebsockets` | 仅对兼容的标准 HTTP Responses 线路接入声明；保留用户能力开关，协议变更时清除不兼容能力。 |
| `supportsRemoteCompaction` / `supportsNativeWebSearch` | 默认 `false`，按线路协议与 transport 校验；Antigravity 当前均声明 `false`。 |
| `modelContexts` | 验证模型键、窗口、输出预留与压缩阈值；接入实际窗口预算并保留用户覆盖优先。未知窗口不声明。 |
| 模型刷新 | 同步上游模型后重新读取插件描述，复核线路 ownership 和 revision；只更新当前线路模型、窗口与能力，保留连接设置。 |
| 过时模型清理 | 删除已过时的插件声明模型，保留独立手动模型及空选择；同步期间防止实例被启停或配置替换。 |

Codey 宿主必须能够识别这些 SDK/线路描述字段。旧宿主对新字段的处理尚未验证，不能保证仅导入新插件就能获得模型窗口或 WS 开关。

## 插件与代理的配合

1. 单独启动代理并使用已授权 OAuth 客户端登录。模型目录来自实际 Google 账号和项目，任意 API Key 不能替代该认证。
2. 初次启用前刷新代理 `/v1/models?refresh=1`；默认原生插件只读取 `/v1/models?cached=1`，不在宿主内进行 Google OAuth。
3. 首次目录失败时拒绝线路注册；同一实例已有成功目录后可保留最后目录。模型数量超过 32 时明确报错，不静默截断。
4. 代理 `/v1/models` 提供实际窗口和输出限制，插件只对可确认的元数据声明 `modelContexts`。
5. 新宿主模型同步完成后应移除过时插件模型，并更新当前线路窗口。需在线上 CI 及新宿主中验证完整链路。

## 尚未声明支持的功能

- **Codey 原生 Google 搜索：** `supportsNativeWebSearch=false`。代理显式 `/v1/search` 与 Responses `web_search` 转换已有代码，但 grounding URL annotations 和混合工具完整契约尚未验证。
- **原生远程压缩：** `supportsRemoteCompaction=false`。代理没有提供满足 Codey 要求的 `/responses/compact`（非空 `encrypted_content` 的 compaction 项）实现；保留客户端已有的本地压缩方式。

## 验证与发布边界

独立仓库 CI 验证代理单元测试、mock E2E、SDK、原生 ABI、Windows 打包和隔离安装。宿主 PR 需要运行宿主相关测试。上述 CI 无真实 Google 凭据，不能替代新宿主中实际模型同步、窗口预算、WS 对话和真实账号的验证。

迁移代码与当前机器已安装的旧二进制是不同状态。只有明确下载并安装对应 CI 产物后，才能开始新插件实测；不要把源码更新或 CI 作业创建当成已安装成功。
