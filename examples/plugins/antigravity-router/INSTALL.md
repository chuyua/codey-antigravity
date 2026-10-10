# 安装与使用

从对应提交的 GitHub Actions 获取 Windows x64、Linux x64 或 macOS arm64 artifact，校验 `SHA256SUMS` 后解压便携 ZIP。编译在 CI 完成。Windows 解压后执行：

```powershell
.\scripts\install.ps1 -Destination "$env:LOCALAPPDATA\CodeyAntigravity"
```

安装脚本校验所有文件及代理版本，只复制到空目录。它不会修改 Codey 的插件或账号配置。发布包不附带 OAuth 应用凭据；先在当前终端通过 `ANTIGRAVITY_CLIENT_ID` 与 `ANTIGRAVITY_CLIENT_SECRET` 配置你已获授权的 Google OAuth 客户端，再进入安装目录登录并启动代理。客户端需支持 Google Cloud Code/Antigravity scope 与本地回调；不能保证任意新建 OAuth 应用均被 Google 接受。已有 Pi 登录的 refresh token 必须使用同一个签发客户端配置。

不要把真实值写入插件配置、脚本或 Git；它们只由当前进程环境传给代理，未配置时登录/刷新会明确失败。以下值是占位符，运行前在本机替换：

```powershell
Set-Location "$env:LOCALAPPDATA\CodeyAntigravity"
$env:ANTIGRAVITY_CLIENT_ID = '<authorized-oauth-client-id>'
$env:ANTIGRAVITY_CLIENT_SECRET = '<authorized-oauth-client-secret>'
.\bin\antigravity-proxy.exe login --manual
.\start-proxy.ps1
```

`login --manual` 提供登录 URL；在同一个仍运行的终端粘贴登录完成后的回调 URL，不要把回调、令牌或账号文件发给别人。也可运行 `login` 使用本地回调。Google OAuth 属于代理，不使用 Codey 保存的 OpenAI 账号。



在 Codey 的插件管理中导入 `antigravity-router-0.10.0-windows-x64.codey-plugin`，核对插件 ID 为 `codey.antigravity-router` 及来源后显式启用，并在线路列表选择 Antigravity 及所需模型。导入默认停用，原生插件不受沙箱隔离。无需给此本地线路添加真实 Google API Key；模型目录通过代理已登录的 Google 账号取得，任意字符串 Key 不能替代 Google 登录。

默认 `syncModels=true`：启用前先运行代理并刷新其模型目录（`GET http://127.0.0.1:28787/v1/models?refresh=1`）。`models` 始终是插件向 Codey 声明的模型列表，最多 32 个；同步只验证这些模型当前账号确实可用，并同步上游提供的思考档位和窗口等元数据，不会把代理目录中的其他模型自动追加进线路。首次读取失败会阻止线路注册；同一运行实例随后读取失败时保留最后成功结果。代理 `/v1/models` 仍保留完整真实目录。只有明确不需要目录校验和能力同步时才设 `syncModels=false`。


**Windows 无窗口后台启动（可选）**：安装 Python 3 后，双击 `background_proxy.pyw` 可无控制台启动代理；或运行 `py -3 background_proxy.py start|status|stop|restart` 管理。脚本复用已校验 PID、进程创建时间和端口归属的 PowerShell 启停逻辑，不保存令牌、不增加 Python 后端服务。`py -3 background_proxy.py autorun-on` 可自愿启用当前用户登录后无窗口启动，`autorun-off` 可关闭；它只写入当前用户的 HKCU Run 项，不创建计划任务。**若已有针对 28787 的登录计划任务，应在确认新方式可用后停用旧任务，避免两种自启动方式冲突。**

**Windows 代理连接检查**：首次安装先确认 `http://127.0.0.1:28787/health` 正常，再调用 `http://127.0.0.1:28787/v1/models?refresh=1` 预热，并通过 `http://127.0.0.1:28787/v1/models?cached=1` 确认模型目录可用。导入插件后检查 `baseUrl=http://127.0.0.1:28787/v1` 和 `syncModels=true`。如果启动终端退出会使代理停止，可选择手动运行或配置当前用户的后台启动方式；计划任务不是插件必需项。

默认情况下插件只输出已发布 Codey 能识别的描述字段，不需要任何宿主补丁即可注册线路。已发布 Codey 会对未知字段直接拒绝整份描述，所以能力字段默认全部关闭：`declareHostCapabilities=true` 才输出 `modelContexts` 和固定为 `false` 的 `supportsRemoteCompaction` / `supportsNativeWebSearch`；`declareWebsockets=true`（需先打开前者）才额外声明 `supportsWebsockets=true`。代理未实现 `/v1/responses/compact`，也没有验证 Codey 原生搜索结果与引用契约，因此这两项不会声明为支持。

新建 Antigravity 线路的三项能力默认关闭。升级已有线路时，在宿主线路设置中关闭曾开启的 WebSocket、远程压缩和原生搜索并保存，按界面提示重启。宿主 PR #67 已关闭，本插件不依赖它。旧宿主无法接受 `modelContexts`，窗口沿用其内置值；代理仍返回上游确认的窗口元数据，插件不伪造窗口。

代理默认关闭模型侧搜索工具；需要显式搜索时可调用 `POST /v1/search`。只有设置 `ANTIGRAVITY_NO_SEARCH_TOOL=0` 并重新启动代理，才启用模型侧搜索工具；`=1` 强制关闭，不影响这个显式接口：

```powershell
Invoke-RestMethod -Uri 'http://127.0.0.1:28787/v1/search' -Method Post -ContentType 'application/json' -Body '{"query":"最新 Rust stable 版本"}'
```

代理默认仅监听 `127.0.0.1:28787`。自定义端口时用 `start-proxy.ps1 -Port <端口>`，并同步修改插件配置的 `baseUrl` 后重新启用。插件 `routeId` 默认为空，只注册线路；生命周期处理需填写准确线路 ID。`retryOnce` 默认关闭，重放可能重复工具执行或计费，只有明确需要时才开启。

启动脚本继承当前进程的 `HTTP_PROXY` / `HTTPS_PROXY`，并为回环请求补充 `NO_PROXY`；需要读取 Windows 当前用户的手动代理时使用 `-UseSystemProxy`。PAC 和代理认证不自动处理，请显式设置环境变量。启动失败时可直接运行 `bin/antigravity-proxy.exe serve` 查看错误。

```powershell
.\bin\antigravity-proxy.exe accounts list
.\bin\antigravity-proxy.exe usage
.\stop-proxy.ps1
```

启动和停止脚本检查可执行路径、PID 创建时间、端口归属及健康服务标识；遇到占用端口会拒绝操作。它们不会创建开机任务。默认账号及模型缓存位于 `~/.pi/agent`，启动脚本生成的图片与进程记录位于安装目录 `.runtime`；自定义 `-AuthPath` 时代理缓存放在该账号文件所在目录。账号文件含可刷新令牌，限制本地访问并保留备份。停用或卸载原生插件不会停止代理，也不会删除代理账号、图片或 Codey 保留的数据与日志。

代理默认使用 HTTP/SSE；WebSocket 握手默认拒绝，仅 `ANTIGRAVITY_ENABLE_WEBSOCKETS=1` 时启用，宿主开关和插件声明也需明确兼容。代理保留显式搜索、图片、模型、usage 与 doctor 接口；拒绝带 Origin 的浏览器调用。远程图片只允许公有地址，图片镜像默认关闭；只有显式设置 `AG_IMAGE_MIRROR=1` 和 `HFSY_API_KEY` 才会上传。`AG_DEBUG` 只记录脱敏计数。可用 `ANTIGRAVITY_NO_EXTRA_TOOLS=1` 关闭全部模型侧额外工具，或 `ANTIGRAVITY_NO_IMAGE_TOOL=1` 单独关闭图片工具；显式搜索和图片命令仍可使用。

## macOS / Linux

选择与 CPU 架构一致的包。POSIX 运行脚本需要 Bash、Python 3、curl、lsof；macOS 可用系统自带 lsof，Linux 按发行版安装。按用户授权的 OAuth 客户端设置相同环境变量后执行：

```bash
./scripts/install.sh --destination "$HOME/CodeyAntigravity"
cd "$HOME/CodeyAntigravity"
./bin/antigravity-proxy login --manual
./start-proxy.sh
curl -fsS 'http://127.0.0.1:28787/v1/models?refresh=1'
./stop-proxy.sh
```

### macOS 原生后台运行（Apple Silicon，可选）

macOS 版便携包提供 `macos_proxy.py`，使用系统的 **LaunchAgent（launchd）** 在当前用户登录后无 Terminal 窗口地运行。Python 从用户登录钥匙串读取已授权 OAuth 客户端 ID 与 Secret，然后直接以 Rust 代理取代自身进程；没有第二个常驻 Python 服务。端口仍是 `127.0.0.1:28787`，账号路径为 `~/.pi/agent/auth.json`。登录项位于 `~/Library/LaunchAgents/com.chuyua.codey-antigravity.proxy.plist`，不使用 root、sudo 或系统级 Daemon。

**首次启用**：先完成上面的手动 Google 登录。在 macOS「钥匙串访问」的**登录钥匙串**新建两个「密码项目」，账户名称均为 `id -un` 返回的 macOS 用户短名，项目名称分别为 `com.chuyua.codey-antigravity.oauth-client-id` 和 `com.chuyua.codey-antigravity.oauth-client-secret`，密码分别填自己的已授权 OAuth Client ID 和 Secret。首次读取可能弹出钥匙串授权提示。不要将密钥写进 plist、命令行、Git 或 Codey API Key。

先关闭当前手动启动的同端口代理（按需使用 `./stop-proxy.sh`），然后在 Mac 安装目录运行：

```bash
python3 macos_proxy.py autorun-on     # 配置并加载用户 LaunchAgent
python3 macos_proxy.py status         # 检查 launchd 和 /health
python3 macos_proxy.py restart        # 重启代理
python3 macos_proxy.py stop           # 本次停止，下次登录仍自动启动
python3 macos_proxy.py start          # 手动恢复
python3 macos_proxy.py autorun-off    # 取消登录自动启动，保留 OAuth 数据
```

此工具依赖 `launchctl bootstrap gui/$(id -u)`：必须处于当前用户的 macOS 图形登录会话，不支持仅 SSH 或 root 环境。出现错误检查 `~/Library/Application Support/CodeyAntigravity/runtime/launchd.stderr.log`。如果钥匙串项目缺失则拒绝启用，不会把凭据降级写入明文配置。移动安装目录或更换 Python 解释器前，先执行 `autorun-off`，再重新安装。真实 Mac 登录及 Keychain 解锁仍需在目标电脑上最终测试。

在代理运行期间导入对应平台 `.codey-plugin`。手动 Shell 启动可使用 `--port`、`--auth`、`--state-dir` 自定义；**LaunchAgent 当前固定使用 28787 和默认账号路径**。Apple 产物仅提供 arm64 包，未做 Apple 签名或公证；不提供 macOS Intel 包。
