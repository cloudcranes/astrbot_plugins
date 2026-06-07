# astrbot-plugin-magnet-preview

基于 whatslink API 的磁力链接预览与下载管理插件，自动解析磁链并展示名称、类型、大小、文件数量与预览截图，可对接 aria2pro / qBittorrent 添加和管理下载。

## 功能

- 自动识别并解析消息中的 magnet 链接
- 显示文件关键信息（类型/大小/数量）
- 支持截图预览（可配置最大数量）
- 支持图片域名替换（优先于解析 API 域名）
- 内置短时缓存（默认 10 分钟）
- 解析后回复确认下载：`yes` / `no` / `y` / `n` / `是` / `否`

## 使用

直接发送磁链：

```text
magnet:?xt=urn:btih:A736FE3DE765B2601A52C6ACC166F75A5EE9B0A6&dn=SSNI730
```

解析成功后可回复：

```text
yes / y / 是   # 使用默认下载器
no / n / 否    # 放弃本次下载
```

## 配置项

| 配置项 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `IMAGE_DOMAIN_REPLACEMENT` | string | `""` | 图片 URL 域名替换地址（最高优先级） |
| `WHATSLINK_URL` | string | `https://whatslink.info` | 磁链解析 API 地址（主地址） |
| `MAX_IMAGES` | int | `9` | 最大返回图片数，最大 9 |
| `USE_FORWARD_MESSAGE` | bool | `true` | 非 `aiocqhttp` 平台是否使用合并转发 |
| `CACHE_TTL_SECONDS` | int | `600` | 解析结果缓存秒数 |
| `PENDING_TTL_SECONDS` | int | `600` | 等待用户确认下载的秒数 |
| `DEFAULT_DOWNLOADER` | string | `qbittorrent` | 默认下载器，支持 `qbittorrent` / `aria2` |
| `ARIA2_RPC_URL` | string | `""` | aria2 JSON-RPC 地址，如 `http://127.0.0.1:6800/jsonrpc` |
| `ARIA2_TOKEN` | string | `""` | aria2 RPC token |
| `ARIA2_DIR` | string | `""` | aria2 下载目录 |
| `QB_URL` | string | `""` | qBittorrent WebUI 地址，如 `http://127.0.0.1:8080` |
| `QB_USERNAME` | string | `""` | qBittorrent 用户名 |
| `QB_PASSWORD` | string | `""` | qBittorrent 密码 |
| `QB_SAVE_PATH` | string | `""` | qBittorrent 保存路径 |
| `QB_CATEGORY` | string | `""` | qBittorrent 分类 |

## 行为优先级

1. 解析回退：先 `WHATSLINK_URL`，失败后回退 `https://whatslink.info`。
2. 图片域名替换：`IMAGE_DOMAIN_REPLACEMENT` 优先于 `WHATSLINK_URL`。
3. 发送策略：
   - `aiocqhttp`：默认使用合并转发。
   - 其他平台：由 `USE_FORWARD_MESSAGE` 控制。

## 缓存说明

- 缓存 Key：规范化后的完整磁链
- 缓存 Value：原始 API 解析结果
- 默认 TTL：600 秒（10 分钟）
- 缓存仅存在于进程内，重启后清空

## 下载器说明

- aria2pro 使用 aria2 JSON-RPC 的 `aria2.addUri` 添加磁链。
- qBittorrent 使用 WebUI API 登录并通过 `/api/v2/torrents/add` 添加磁链。
- 插件只负责解析后确认添加下载，不提供暂停、恢复、删除、状态查询命令。
