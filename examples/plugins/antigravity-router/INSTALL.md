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

在 Codey 的插件管理中导入 `antigravity-router-0.9.0-windows-x64.codey-plugin`，核对来源后显式启用，并在线路列表选择 Antigravity 及所需模型。导入默认停用，原生插件不受沙箱隔离。无需给此本地线路添加真实 Google API Key；模型目录通过代理已登录的 Google 账号取得，任意字符串 Key 不能替代 Google 登录。

默认 `syncModels=true`：启用前先运行代理并刷新其模型目录（`GET http://127.0.0.1:8787/v1/models?refresh=1`）。原生插件只读取代理缓存，不在宿主进程中发起 Google OAuth 请求。首次读取失败会阻止线路注册并显示错误，避免重新添加配置中的过时模型；同一运行实例随后读取失败时保留最后成功目录。原生线路清单上限为 32 个模型；目录超出时返回 `catalog_too_many_models`，不会静默截断。以后在线路设置中同步模型。只有明确维护手动目录时才设 `syncModels=false`；配置中的 `models` 此时才作为注册目录。

默认情况下插件只输出已发布 Codey 能识别的描述字段，不需要任何宿主补丁即可注册线路。已发布 Codey 会对未知字段直接拒绝整份描述，所以能力字段默认全部关闭：`declareHostCapabilities=true` 才输出 `modelContexts` 和固定为 `false` 的 `supportsRemoteCompaction` / `supportsNativeWebSearch`；`declareWebsockets=true`（需先打开前者）才额外声明 `supportsWebsockets=true`。代理未实现 `/v1/responses/compact`，也没有验证 Codey 原生搜索结果与引用契约，因此这两项不会声明为支持。

新建 Antigravity 线路的三项能力默认关闭。升级已有线路时，在宿主线路设置中关闭曾开启的 WebSocket、远程压缩和原生搜索并保存，按界面提示重启。宿主 PR #67 已关闭，本插件不依赖它。旧宿主无法接受 `modelContexts`，窗口沿用其内置值；代理仍返回上游确认的窗口元数据，插件不伪造窗口。

代理默认关闭模型侧搜索工具；需要显式搜索时可调用 `POST /v1/search`。只有设置 `ANTIGRAVITY_NO_SEARCH_TOOL=0` 并重新启动代理，才启用模型侧搜索工具；`=1` 强制关闭，不影响这个显式接口：

```powershell
Invoke-RestMethod -Uri 'http://127.0.0.1:8787/v1/search' -Method Post -ContentType 'application/json' -Body '{"query":"最新 Rust stable 版本"}'
```

代理默认仅监听 `127.0.0.1:8787`。自定义端口时用 `start-proxy.ps1 -Port <端口>`，并同步修改插件配置的 `baseUrl` 后重新启用。插件 `routeId` 默认为空，只注册线路；生命周期处理需填写准确线路 ID。`retryOnce` 默认关闭，重放可能重复工具执行或计费，只有明确需要时才开启。

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
curl -fsS 'http://127.0.0.1:8787/v1/models?refresh=1'
./stop-proxy.sh
```

在代理运行期间导入对应平台 `.codey-plugin`。自定义启动参数为 `--port`、`--auth`、`--state-dir`；账号、目录预热、能力默认与升级步骤同 Windows。Apple 产物仅提供 arm64 包，未做 Apple 签名或公证；不提供 macOS Intel 包。
