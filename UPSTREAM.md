# 上游来源与移植记录

此独立插件仓库是 [chuyua/codey-antigravity](https://github.com/chuyua/codey-antigravity)。**Antigravity 代理的实际上游为 [Rahularya01/pi-antigravity](https://github.com/Rahularya01/pi-antigravity)**；Codey 宿主项目为 [SuperGness/codey](https://github.com/SuperGness/codey)，两者职责与来源不同。

## 迁移基准

- 上游分支/版本：`main` / `v0.9.0`。
- 基准提交：[`a3d8caba1b10263420060406de57112ce16490d0`](https://github.com/Rahularya01/pi-antigravity/commit/a3d8caba1b10263420060406de57112ce16490d0)。
- 本地实现：Rust 代理；这是协议与行为迁移，不能用 Git 提交关系推断已同步所有上游变化。
- 上游代理许可：MIT，保留 Rahul Arya 的署名，见 [proxy-rust/LICENSE](examples/plugins/antigravity-router/proxy-rust/LICENSE)。

## 选择性移植

| 上游变更 | 使用的提交 | 本仓库处理 |
| --- | --- | --- |
| [PR #78: Fix UTF-8 inline citations in Google Search results](https://github.com/Rahularya01/pi-antigravity/pull/78) | `06cdbaa891d7527bf9578f3ff91ac1a8fe448b56` | 移植 UTF-8 字节引用、原始 part/source 索引与重复引用处理，并加入对应 Rust 回归测试源码。 |

以上记录表示对指定 head 的选择性移植，不表示上游 PR 已合并，也不表示已合并全部开放 PR。后续上游状态以链接中的实时信息为准。Google 原生搜索结果与 Codey 的完整契约仍需验证，PR #78 的引用修复不会自动开启宿主原生搜索能力。

## Codey 适配与保留的定制

原生插件和 SDK 适配采用 Codey 的线路与请求生命周期接口。当前定制包括代理缓存模型同步、账号/项目模型校验、真实窗口元数据、Codey Responses WebSocket 转换、独立代理运行和 Windows 便携打包。宿主需要另行接入能力声明、窗口预算及线路模型刷新，见 [HOST_COMPATIBILITY.md](docs/HOST_COMPATIBILITY.md)。

未确认上游有满足 Codey `/responses/compact` 加密内容契约的原生远程压缩实现，因此保持 `supportsRemoteCompaction=false`；普通摘要不能冒充原生加密压缩。

## 许可边界

代理、mock E2E 和便携运行脚本依各自 MIT 声明分发；原生插件、Codey SDK 与仓库打包工具为 AGPL-3.0-only，完整边界见 [NOTICE.md](examples/plugins/antigravity-router/NOTICE.md)。对应源码、第三方许可及校验和随便携包一起提供。不要把整个仓库或整个混合插件包改标为 MIT。

此项目不是 Google 官方插件。Google OAuth 账号、模型、配额和协议由 Google 控制；源码不附带可用于真实登录的客户端凭据或账号文件。
