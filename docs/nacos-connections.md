# Nacos 2.x 与数据库连接管理

平台支持 Nacos 2.x，每个数据库使用一份 JSON。配置管理入口为「左下角管理员菜单 → 平台设置 → 连接与依赖 → 数据库连接」，页面分为“业务数据库”“平台数据库”“Nacos 连接”。本次不改变平台库类型，平台继续使用 GaussDB/DWS；业务库支持 MySQL、PostgreSQL、GaussDB/DWS 和 ClickHouse。

## 1. 配置 Nacos 服务

由内置管理员（`WFS_ADMIN_USERNAME`，默认 `admin`）打开“Nacos 连接”，填写服务地址（例如 `http://nacos.internal:8848/nacos`）、账号、密码、请求超时和缓存时间。使用 HTTPS 时默认校验证书，可指定服务器上的 CA 文件。

点击“测试连接”后保存。启用鉴权时测试验证登录；填写探测配置后还会检查该配置的读取权限。未启用鉴权时必须提供探测配置。测试不会发布或修改任何 Nacos 文档；真正的发布权限会在保存数据库连接时检验。

密码留空表示保留原密码；更换服务地址时，必须明确重新输入密码。设置加密保存于 `data/nacos-connection.enc`，可用 `WFS_NACOS_CONFIG_FILE` 指定其他位置。加密使用固定的 `WFS_CONNECTIONS_KEY`，未设置时使用 `WFS_SECRET_KEY`。须单独保管密钥，不能随意更换。

没有页面配置文件时，兼容 `WFS_NACOS_URL`、`WFS_NACOS_USERNAME`、`WFS_NACOS_PASSWORD` 和 `WFS_NACOS_CONFIG_TTL_SECONDS` 环境变量。服务连接设置保存后对后续配置读取生效；修改全局 Nacos 服务地址前，应确保新的服务包含所有已登记的数据库配置。平台当前连接和已启动任务仍保持原来的凭据快照。

## 2. 读取一份数据库配置

在业务数据库或平台数据库中选择“Nacos”来源，填写：

- Namespace：命名空间 ID；公共命名空间留空。
- Group：配置分组，默认 `DEFAULT_GROUP`。
- Data ID：配置文件名，例如 `orders.json`。
- 密码编码：`plain` 或 `base64`，必须与已有 JSON 一致。
- 字段映射：可为现有 JSON 的顶层字段指定对应关系。

默认对应如下：

| 连接字段 | JSON 字段 |
| --- | --- |
| 主机 | `host` |
| 端口 | `port` |
| 数据库 | `db` |
| 账号 | `user` |
| 密码 | `password` |
| 平台 Schema | `schema` |

例如：

```json
{
  "host": "database.internal",
  "port": 8000,
  "db": "workflow",
  "schema": "wfs",
  "user": "workflow_user",
  "password": "replace-with-your-password",
  "description": "保留给其他使用方的说明"
}
```

使用普通字符串密码时选 `plain`；Base64 只是兼容编码，并非加密。业务配置可以不提供 `schema`。本版支持 JSON 顶层字段映射，不支持嵌套路径或 YAML。Nacos 负责连接地址、库名、账号、密码及平台 Schema；业务连接标识、驱动、连接池、TLS、用途、任务授权等仍由平台管理。

点击“读取配置”会回填连接字段和版本；密码只显示“已设置”，不会回传到浏览器。修改定位或字段映射后必须重新读取。页面只编辑已存在的 JSON，不自动创建、删除整个 Nacos 配置。

## 3. 修改与回写

读取后编辑字段，再测试或保存：

1. 重新读取文档并比较版本，确认没有被其他人修改。
2. 使用候选连接进行只读连接测试；平台库还检查表结构，不自动建表或迁移数据。
3. 保存时使用 Nacos 的 CAS 版本检查回写；只改受管字段，保留其他 JSON 字段。
4. 读取确认写入结果，再保存平台中的连接登记或待重启配置。

回写会影响其他使用这份 Nacos JSON 的应用，请在页面确认前核对。检测到文档版本或 Nacos 服务设置变化时返回冲突，必须重新读取；不会覆盖其他人的更新，也不会把旧服务的凭据发布到新服务。网络中断时不会盲目重试发布；若无法读回确认，页面会明确提示结果尚未确认。

Nacos 和平台本地登记无法组成同一个数据库事务。如果 Nacos 已更新而本地登记失败，页面会明确报告“已更新，但本地保存失败”；重新读取并核对后再保存。不要将此情况理解为远端已经回滚。

只有内置管理员可以读取远端预览、测试或修改 Nacos 来源连接。其他管理员可查看登记信息，并继续管理直接配置的业务连接。删除平台业务连接登记不会删除 Nacos 文档。

## 4. 配置何时生效

| 配置 | 生效方式 |
| --- | --- |
| Nacos 服务地址、认证设置 | 后续 Nacos 读取立即使用新设置 |
| 业务数据库连接 | 新任务启动时重新读取并冻结授权连接；运行中的任务不切换 |
| 平台数据库连接 | 完整服务重启时读取并冻结实际凭据；单独替换 Web worker 不切换 |

外部直接修改 Nacos 时也遵守上述规则。平台配置保存后不会自动重启、切换数据库或迁移业务数据。完整重启生产服务使用 `systemctl restart wfs.service`；先安排好正在运行的任务和维护窗口。

旧的“服务配置”来源在生产仍兼容 `gauss.<database>.<schema>.json`、`group=gauss`、公共命名空间、Base64 密码规则，并在启动时固定解析结果。若需要从页面编辑该文档，请改选显式“Nacos”来源并填写对应定位和编码。

任务只接收被授权业务连接的快照，不接收 Nacos 登录凭据。远端不可用或配置无效时，新的连接解析会失败，不静默回退到旧密码。

## 5. 备份与开发用法

平台备份包含加密的 Nacos 引导配置和平台启动配置证据，不包含解密密钥。恢复时先核对目录、服务地址和独立保管的原密钥；备份解包不会自动替换正在使用的连接，也不包含远端 Nacos 文档的完整备份。

增删改查、批量操作、事务和异步调用见 [数据库使用说明](database-usage.md)。业务任务统一使用 `NewDB`，可复制示例位于「左下角管理员菜单 → 任务示例与文档 → 任务中的统一用法」，直接配置与 Nacos 来源使用相同写法。平台内部 `GaussDB` 示例仍位于「平台设置 → 连接与依赖 → 数据库连接 → 平台数据库」，不能用于业务任务访问平台库；示例页面均不执行 SQL。

接口依据：[Nacos 2.x Open API](https://nacos.io/en/docs/v2/open-api/)、[Nacos 2.4.3 ConfigController](https://github.com/alibaba/nacos/blob/2.4.3/config/src/main/java/com/alibaba/nacos/config/server/controller/ConfigController.java)。当前使用 2.x 兼容的 `/v1/auth/login`、`/v1/cs/configs` 与 `casMd5` 请求头。上线仍需用实际 Nacos 版本、账号权限及数据库驱动完成验收。
