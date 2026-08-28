# 本地生产拓扑发布与恢复手册

本文描述 E9/E10 的本地生产形态发布与验收。它提供可复现的容器拓扑、迁移/seed 顺序、邀请账号初始化、发布 receipt、逻辑备份和恢复验证；静态检查、原生进程演练和容器镜像验收是不同证据层，不能互相替代。

## 1. 发布边界

生产 compose 是 `infra/compose/docker-compose.production.yml`。它包含 PostgreSQL、Redis、RabbitMQ、MinIO、MinIO 外部 readiness sidecar、migration job、catalog seed job、storage bucket seed job、API、Web、chat relay、generation relay、chat worker、image-audio worker、video worker 和 artifact cleanup。只有 Web 发布主机端口；其余服务只在 Compose 网络内可达。数据卷不会随普通 `down` 删除。

bundled 拓扑使用显式的 `staging` 环境（compose env 名为 `MOSAIC_APP_ENVIRONMENT=staging`，直接运行 API 时为 `APP_ENVIRONMENT=staging`），因此允许 bundled HTTP MinIO、AMQP 和 localhost origins；它只用于本地/隔离 staging 演练。`production` 仍拒绝开发凭据、非安全 session cookie、loopback auth origin、`amqp://` RabbitMQ 和 `http://` S3 endpoint。生产覆盖必须使用外部 TLS 终结点、非默认凭据和非 loopback origin；不要把 `http://minio:9000` 或 `amqp://rabbitmq:5672` 当作 production 配置。

数据库身份分为三类：migration/catalog seed 使用 owner URL，API 使用 `NOSUPERUSER NOBYPASSRLS` 且不拥有业务表的 app URL，relay/worker 使用独立 `BYPASSRLS` worker URL。API readiness 会拒绝 superuser、`BYPASSRLS` 或表 owner 身份。`infra/postgres/init/001-runtime-roles.sh` 只在新 PostgreSQL volume 首次初始化时运行；已有 volume 必须由数据库管理员先创建同等角色和 grants，再切换三个 URL，不能继续让 API 使用 owner 连接。

执行主机缺少 Docker/Compose 时，只能生成 `BOUNDED` 静态 receipt；即使原生 PostgreSQL、Redis、RabbitMQ、MinIO 和应用进程已经演练，也不能把容器镜像 digest 或镜像启动写成通过。完整 `PASS` receipt 必须在有 Docker 的受控构建主机生成。

## 2. 准备 staging env（bundled 演练）

```powershell
$envFile = Join-Path (Get-Location) '.env.staging'
Copy-Item -LiteralPath 'infra/compose/staging.env.example' -Destination $envFile
# 替换 session pepper、metrics token 和 Provider key；不要把填写后的文件加入 Git。
$env:MOSAIC_RELEASE_HMAC_KEY = '<本地 receipt key，不要回显>'
```

`infra/compose/staging.env.example` 明确指向 bundled 服务。它不是 production 凭据模板。`MOSAIC_SESSION_TOKEN_PEPPER` 必须是至少 32 字符且跨 API 重启保持稳定的随机值；示例 Provider 占位值会被 readiness 拒绝。不要把 staging 默认密码用于外部环境，也不要使用 `docker compose config`（不带 `--quiet`）输出已解析配置，因为那会把环境值暴露到日志。

## 3. production override（外部 TLS 服务）

```powershell
$envFile = Join-Path (Get-Location) '.env.production'
Copy-Item -LiteralPath 'infra/compose/production.env.example' -Destination $envFile
# 用部署系统的 secret 注入器填写 $envFile；不要把填写后的文件加入 Git。
$env:MOSAIC_RELEASE_HMAC_KEY = '<由 secret 注入器提供，不要回显>'
```

production env 必须保持 `MOSAIC_APP_ENVIRONMENT=production`，并替换 PostgreSQL、Redis、RabbitMQ、S3、Provider、session pepper、镜像引用和 release receipt HMAC 值。RabbitMQ 使用 `amqps://`，S3 使用 `https://`，`MOSAIC_AUTH_ALLOWED_ORIGINS` 使用明确的非 loopback HTTPS origin；`MOSAIC_ARTIFACT_STORAGE_S3_SEED_ENDPOINT_URL` 必须是可从 seed job 访问的同一外部 bucket endpoint。bundled MinIO 只用于 staging 拓扑和恢复演练。带 `-RequireConfigHmac` 的 Gate 会拒绝仍含 `REPLACE_WITH` 的配置。

## 4. 静态检查、镜像与发布 receipt

无 Docker 的主机先运行静态检查；提交前允许工作树为 dirty，验收 receipt 必须在提交后生成：

```powershell
pwsh -NoProfile -File scripts/verify-release.ps1 -StaticOnly -AllowDirty `
  -ConfigPath infra/compose/staging.env.example `
  -ReceiptPath output/release/static-receipt.json

git diff --check
git add .
git commit -m "chore: add production release operations"

$providerEvidencePath = (Resolve-Path -LiteralPath '.runtime\provider-live-evidence.json').Path
pwsh -NoProfile -File scripts/verify-release.ps1 -RunTests -BuildImages `
  -RequireImageDigests -RequireConfigHmac -RequireProviderEvidence `
  -ProviderEvidencePath $providerEvidencePath `
  -ConfigPath $envFile `
  -ReceiptPath output/release/receipt.json

pwsh -NoProfile -File scripts/verify-release-receipt.ps1 `
  -ReceiptPath output/release/receipt.json
```

`verify-release.ps1` 会显式检查每个外部命令的 exit code，并把命令输出只保存为 SHA-256 摘要和行数。`-BuildImages` 会构建同一 compose 中的 Web/API/relay/chat/media/video 镜像，把每个逻辑服务解析到 Docker content digest，并真正启动 Web 镜像验证非 root 用户、根页面和登录页。完整 receipt 还会验证当前 commit 的签名 Provider evidence。receipt 的最终 HMAC 覆盖 commit、clean tree、lockfile、迁移 head、配置/compose 摘要、Provider evidence 摘要、镜像 manifest/digest、测试 evidence、limitations 和 acceptance status；不是只覆盖配置。不会写入 secret 或原始命令输出。`output/` 已加入 `.gitignore`，receipt 应作为构建/发布 artifact 保存。没有 Docker 或当前 Provider evidence 时只能生成 `BOUNDED` receipt。

有 Docker 的环境可以额外渲染 production compose：

```powershell
docker compose --env-file $envFile -f infra/compose/docker-compose.production.yml config --quiet
docker compose --env-file $envFile -f infra/compose/docker-compose.production.yml build
docker compose --env-file $envFile -f infra/compose/docker-compose.production.yml up -d
docker compose --env-file $envFile -f infra/compose/docker-compose.production.yml ps
```

正常 `seed-catalog` 每次都会把 endpoint/deployment 重置为 degraded/disabled，避免沿用旧 commit 的激活状态。只有当前镜像 revision 与签名 evidence 的 `source_commit` 一致时，才可在容器中重新激活：

```powershell
$providerEvidencePath = (Resolve-Path -LiteralPath '.runtime\provider-live-evidence.json').Path
docker compose --env-file $envFile -f infra/compose/docker-compose.production.yml run --rm --no-deps `
  --mount "type=bind,src=$providerEvidencePath,dst=/run/provider-live-evidence.json,readonly" `
  seed-catalog /app/apps/api/.venv/bin/python /app/apps/api/scripts/seed_product_catalog.py `
  --activate --live-evidence-file /run/provider-live-evidence.json
```

API 镜像把 `MOSAIC_BUILD_REVISION` 固化为 `MOSAIC_SOURCE_COMMIT`，并只在干净发布构建中标记 `MOSAIC_SOURCE_TREE_CLEAN=true`；seed job 通过 secret 注入 `MOSAIC_LIVE_EVIDENCE_HMAC_KEY`。因此容器无需复制 `.git`，但错误/占位 revision、错误 HMAC、不同 manifest 或不同 smoke 脚本仍会失败。

bundled 演练必须使用 `staging.env.example` 复制出的 env；`up` 会显式启动 MinIO `server /data`，由 `minio-ready` sidecar 通过 HTTP 探测，再由 `seed-storage` 创建并 head-verify bucket，migration/catalog seed 完成后才启动 API、relay 和 worker。

全新 volume 不创建默认账号，production 也绝不能自动 seed 通用密码。迁移和 seed 完成后，由受保护的 operator 主机通过 owner 身份创建一次性邀请凭据：

```powershell
docker compose --env-file $envFile -f infra/compose/docker-compose.production.yml run --rm --no-deps migration `
  /app/apps/api/.venv/bin/python /app/apps/api/scripts/operator_accounts.py create `
  --account 'owner@example.com' --tenant-slug 'example' --tenant-name 'Example' `
  --role owner --operator-subject 'release-operator' --reason 'initial tenant bootstrap'
```

命令只打印一次 24 小时有效的凭据；通过带外渠道交付，不写入 env、仓库或普通日志。隔离 staging 如需演示余额，可显式追加 `--initial-points-minor 100000`；production 不应自动赠送点数。首次登录必须强制改密并轮换 session；保持同一 secret-injector 中的 session pepper 后重启 API，再确认现有 session 仍可校验。凭据重置使用同一脚本的 `reset` 子命令并留下审计事件。

API `/api/v1/health/live` 是进程存活检查；`/api/v1/health/ready` 还要求 PostgreSQL、Redis、有效 Provider 配置、session token codec、两个 relay、chat worker、media worker 和 video worker 各自就绪。CI 的非 Provider 值只验证非付费配置和镜像路径；它不属于 Provider live evidence，也不激活任何路由。

启动后必须分别核对 `migration` 使用 owner、`api` 使用 app、relay/worker 使用 worker URL；不要在日志中输出 URL。若 API ready 因数据库角色失败，修复角色/grants，而不是关闭 RLS 或改回 owner。

## 5. PostgreSQL 逻辑备份/恢复

备份目标必须显式指定，且不能是仓库根目录或文件系统根目录。密码只放在 `MOSAIC_POSTGRES_PASSWORD` 进程环境中，不作为命令行参数：

```powershell
$env:MOSAIC_POSTGRES_BACKUP_DIRECTORY = 'D:\backups\mosaic\postgres\2026-08-26T120000Z'
$env:PGHOST = 'postgres.example.internal'
$env:PGDATABASE = 'mosaic'
$env:PGUSER = 'mosaic_owner'
$env:MOSAIC_POSTGRES_PASSWORD = '<由 secret 注入器提供，不要回显>'
pwsh -NoProfile -File scripts/backup-postgres.ps1
```

该脚本生成 custom-format dump 和同名 `.manifest.json`，manifest 记录目标的非敏感连接元数据、文件大小、SHA-256 和 `pg_dump` 输出摘要。已有同名文件不会被覆盖，除非显式使用针对该文件名的 `-Force`。

恢复必须指向已明确命名的目标数据库，并显式确认允许覆盖；脚本不会自动删除源库或卷：

```powershell
pwsh -NoProfile -File scripts/restore-postgres.ps1 `
  -BackupFile 'D:\backups\mosaic\postgres\2026-08-26T120000Z\mosaic-postgres-20260826T120000Z.dump' `
  -TargetDatabase 'mosaic_restore_20260826' `
  -AllowOverwrite
```

恢复前会校验旁边的 manifest 和 dump hash，并执行 `pg_restore --list`；恢复命令使用 `--exit-on-error`、`--single-transaction`、`--no-owner` 和 `--no-privileges`。不要把生产恢复目标写成 `postgres`、`template0` 或 `template1`。

## 6. MinIO mirror/restore

`mc` 凭据也只注入环境；脚本使用临时 `MC_HOST_<alias>` 环境变量，不调用 `mc alias set`，避免把 secret 放进命令行历史：

```powershell
$env:MOSAIC_MINIO_ENDPOINT = 'https://minio.example.internal'
$env:MOSAIC_MINIO_BUCKET = 'mosaic-artifacts'
$env:MOSAIC_MINIO_ACCESS_KEY_ID = '<由 secret 注入器提供，不要回显>'
$env:MOSAIC_MINIO_SECRET_ACCESS_KEY = '<由 secret 注入器提供，不要回显>'
pwsh -NoProfile -File scripts/mirror-minio.ps1 `
  -Destination 'D:\backups\mosaic\minio\2026-08-26T120000Z'
```

mirror 目标目录非空时必须显式使用 `-AllowOverwrite`。脚本生成 `minio-mirror.manifest.json`，记录 endpoint host、bucket、文件数量和 mirror 输出摘要，不记录 access key/secret key。

恢复到指定 bucket：

```powershell
pwsh -NoProfile -File scripts/restore-minio.ps1 `
  -SourceDirectory 'D:\backups\mosaic\minio\2026-08-26T120000Z' `
  -AllowOverwrite
```

## 7. 可执行恢复验证

恢复验证要求同时提供 PostgreSQL 和 MinIO 目标。它不会假设恢复成功：会校验 dump hash、`pg_restore --list`、本地 mirror 文件数量、目标数据库的 `alembic_version`，以及目标 bucket 的 object 数量。默认不写死 migration head；脚本会从当前 repo 的单一 `uv ... alembic heads` 推导。对历史 release 可显式传入 `-ExpectedMigrationHead`。

```powershell
$env:PGHOST = 'postgres-restore.example.internal'
$env:PGDATABASE = 'mosaic_restore_20260826'
$env:PGUSER = 'mosaic_owner'
$env:MOSAIC_POSTGRES_PASSWORD = '<由 secret 注入器提供，不要回显>'
$env:MOSAIC_MINIO_ENDPOINT = 'https://minio-restore.example.internal'
$env:MOSAIC_MINIO_BUCKET = 'mosaic-artifacts-restore'
$env:MOSAIC_MINIO_ACCESS_KEY_ID = '<由 secret 注入器提供，不要回显>'
$env:MOSAIC_MINIO_SECRET_ACCESS_KEY = '<由 secret 注入器提供，不要回显>'

pwsh -NoProfile -File scripts/verify-restore.ps1 `
  -BackupFile 'D:\backups\mosaic\postgres\2026-08-26T120000Z\mosaic-postgres-20260826T120000Z.dump' `
  -MirrorDirectory 'D:\backups\mosaic\minio\2026-08-26T120000Z' `
  -TargetDatabase 'mosaic_restore_20260826'
```

只有该脚本返回 `status=ok` 才能把这次恢复记为通过；缺少 `psql`、`pg_restore`、`mc`、目标服务或 secret 时应记为 `NOT_RUN_ENVIRONMENT`，不能改写为 PASS。

## 8. 故障与回滚

| 现象 | 先检查 | 处理边界 |
| --- | --- | --- |
| migration job 失败 | `docker compose logs migration`、当前 Alembic head、数据库连接 | 停止发布；不要直接手工改业务表或自动 downgrade |
| MinIO readiness 或 bucket seed 失败 | `docker compose logs minio-ready seed-storage`、seed endpoint、bucket 凭据 | 不启动 API/worker；修复 endpoint/权限后重跑 job，不删除卷 |
| API live 通过但 ready 失败 | PostgreSQL/Redis、Provider 配置、两个 relay 和 worker heartbeat | 不接流量；等待或修复依赖后重新验证 |
| relay/worker 反复重启 | RabbitMQ 健康、队列声明、Redis heartbeat、Provider 配置 | 保留 outbox/任务数据，先停止新发布，不删除卷 |
| Web 能启动但 API rewrite 失败 | `MOSAIC_API_ORIGIN`、API live、Web healthcheck | 回滚 Web/API 镜像到同一已验收 commit |
| 需要回滚应用版本 | receipt 中的 commit、lock hash、migration head | `docker compose up -d --no-deps` 指向上一已验收镜像；数据库只做向前兼容回滚，破坏性恢复走隔离库验证后再切换 |
| 需要整库恢复 | PostgreSQL dump manifest、MinIO mirror manifest、restore verification | 恢复到明确的 restore 目标，验证通过后再进行受控切换；不要使用 `docker compose down -v` |

回滚不等于删除持久卷。任何 `down -v`、删除 backup、覆盖唯一恢复目标都必须是单独、明确授权的破坏性操作。
