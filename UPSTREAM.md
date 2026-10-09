# 上游来源与移植记录

此独立插件仓库是 [chuyua/codey-antigravity](https://github.com/chuyua/codey-antigravity)。**Antigravity 代理的实际上游为 [Rahularya01/pi-antigravity](https://github.com/Rahularya01/pi-antigravity)**；Codey 宿主项目为 [SuperGness/codey](https://github.com/SuperGness/codey)，两者职责与来源不同。

## 迁移基准

- 原始迁移基准：`main` / `v0.9.0`，[`a3d8caba1b10263420060406de57112ce16490d0`](https://github.com/Rahularya01/pi-antigravity/commit/a3d8caba1b10263420060406de57112ce16490d0)。
- 本次选择性同步目标：`main` / `v0.10.0`，[`d59d22bfebd9e44f2fd4a31bf5954a23fb9b043a`](https://github.com/Rahularya01/pi-antigravity/commit/d59d22bfebd9e44f2fd4a31bf5954a23fb9b043a)。2026-10-09 通过 GitHub connector 读取固定 SHA 的 `src/utils/util.ts`、`src/image/image.ts`、`src/search/search.ts`、`src/stream/stream.ts`，compare 显示比原基准 ahead 12 commits。
- 本地实现：Rust 代理；这是协议与行为迁移，不能用 Git 提交关系推断已同步所有上游变化。
- 上游代理许可：MIT，保留 Rahul Arya 的署名，见 [proxy-rust/LICENSE](examples/plugins/antigravity-router/proxy-rust/LICENSE)。

## 0.10.0 下游版本与完整性边界

本项目把**下游发行版本**对齐到 `0.10.0`，表示基于上游 `v0.10.0` 的 Codey 兼容发行，不代表 Pi 插件源码或全部 Pi 专用 API 已原样合并。与上游发行说明逐项核对后的结论：

- 已适配核心协议：UTF-8 引用、signed-int64 会话 ID、`image_gen` 请求格式、搜索候选回退、流式错误识别；`v0.10.0` 中 Google 搜索默认推理预算 `0` 与简洁证据摘要也已对齐。
- Codey 的插件注册、能力声明和本地 Rust HTTP 图片代理使用不同于 Pi 的宿主 API；Pi 原生 `generateImages`、Pi `config` 扩展资源开关和 Pi footer 的 `(sub)` 标记**不是** Codey 插件现有功能，不可宣称全部功能移植。
- Google 账号出现 `VALIDATION_REQUIRED` 时携带受限验证 URL 的用户提示尚待 Codey 侧安全移植与测试。Codey 原生搜索和远程加密压缩尚未验证/实现，相关宿主能力保持默认关闭。真实 Google 账号及 Codey UI 仍须独立验收。
- 旧 `v0.9.0-rc.1` 是历史候选包，仍保留供溯源；`0.10.0` 必须通过对应新提交的完整 CI、实际二进制验收并重新打包，不以旧包换版本标签。

## 选择性移植

| 上游变更 | 使用的提交 | 本仓库处理 |
| --- | --- | --- |
| [PR #78: Fix UTF-8 inline citations in Google Search results](https://github.com/Rahularya01/pi-antigravity/pull/78) | `06cdbaa891d7527bf9578f3ff91ac1a8fe448b56` | 移植 UTF-8 字节引用、原始 part/source 索引与重复引用处理，并加入对应 Rust 回归测试源码。 |
| [PR #77: signed-int64 session IDs](https://github.com/Rahularya01/pi-antigravity/pull/77) / `src/utils/util.ts` | `d59d22bfebd9e44f2fd4a31bf5954a23fb9b043a` | 显式 Codey `session_id` 保留合法 signed-int64 字符串；其它非空 seed 使用与上游相同的 SHA-256 前 8 字节小端 signed-int64。无显式 ID 时沿用本项目 first-user-text 前 64 字符的稳定 seed，跨轮次复用；缺少 seed 则随机 signed-int64。conversation/trajectory UUID、labels 和 last_execution_id 保留。 |
| [PR #81: image protocol](https://github.com/Rahularya01/pi-antigravity/pull/81) / `src/image/image.ts` | `d59d22bfebd9e44f2fd4a31bf5954a23fb9b043a` | image 请求使用 `requestType=image_gen` 与 `image_gen/.../1` requestId，移除强制 systemInstruction 和非官方 `_session`；默认模型 `gemini-3.1-flash-image` 与上游 fallback 对齐。保留现有 HTTP API 和工具拦截。 |
| `src/search/search.ts` 搜索候选 | `d59d22bfebd9e44f2fd4a31bf5954a23fb9b043a` | 优先顺序为 `gemini-3.5-flash-lite`、`gemini-3.1-flash-lite`、`gemini-3-flash`，每个候选仍必须存在于当前账号目录且未明确关闭 grounding；随后保留其它当前可用 Gemini 模型。保留 PR #78 引用与 Codey 搜索桥接定制。 |
| `src/stream/stream.ts` 裸 JSON error / 提前 EOS | `d59d22bfebd9e44f2fd4a31bf5954a23fb9b043a` | 补齐可跨网络块和多行的裸 JSON error；无 finishReason 时返回失败，完整末行允许缺少换行。已有晚到 SSE error、UTF-8 分块、大小上限和单终态处理保留。 |

以上记录仅表示指定 SHA 的选择性协议移植，不能解释为 v0.10.0 全功能移植或所有 PR 均已移植。新增 Rust 回归测试和 mock E2E 断言；本次本地仅运行格式/语法检查，编译与测试执行由 CI 和下载的 CI 二进制验证。Google 原生搜索结果与 Codey 的完整契约仍需验证，引用修复不会自动开启宿主原生搜索能力。

未移植 Pi 的原生 image API 注册、Pi UI/工具呈现与 Pi context 结构，也未开启宿主 WebSocket、原生搜索、远程压缩默认能力。上游 image 输入图片/原生图片 API 等新增能力不在本次有界迁移中；当前图片生成保持既有 prompt/aspect ratio 契约。无显式 session_id 的首条用户文本 seed 可能在相同开头的不同会话间重合，历史裁剪/压缩也可能改变 seed；不保证 provider 缓存命中。Codey 显式 session_id 是可靠的稳定身份入口。

## Codey 适配与保留的定制

原生插件和 SDK 适配采用 Codey 的线路与请求生命周期接口。当前定制包括代理缓存模型同步、账号/项目模型校验、真实窗口元数据、Codey Responses WebSocket 转换、独立代理运行和 Windows 便携打包。宿主需要另行接入能力声明、窗口预算及线路模型刷新，见 [HOST_COMPATIBILITY.md](docs/HOST_COMPATIBILITY.md)。

未确认上游有满足 Codey `/responses/compact` 加密内容契约的原生远程压缩实现，因此保持 `supportsRemoteCompaction=false`；普通摘要不能冒充原生加密压缩。

## 许可边界

代理、mock E2E 和便携运行脚本依各自 MIT 声明分发；原生插件、Codey SDK 与仓库打包工具为 AGPL-3.0-only，完整边界见 [NOTICE.md](examples/plugins/antigravity-router/NOTICE.md)。对应源码、第三方许可及校验和随便携包一起提供。不要把整个仓库或整个混合插件包改标为 MIT。

此项目不是 Google 官方插件。Google OAuth 账号、模型、配额和协议由 Google 控制；源码不附带可用于真实登录的客户端凭据或账号文件。
