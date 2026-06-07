# astrbot_plugin_javbus_api

基于 [`ovnrain/javbus-api`](https://github.com/ovnrain/javbus-api#readme) 的 AstrBot 解析插件。

## 功能

- 影片列表：`/bus list [page]`
- 搜索影片：`/bus search <keyword> [page]`
- 影片详情：`/bus detail <movie_id>`
- 磁力查询：`/bus magnets <movie_id> [sortBy] [sortOrder]`
- 演员详情：`/bus star <star_id>`
- 帮助：`/bus help`
- 快捷番号：直接发送 `SSIS-960` / `IPX585` 自动触发“详情 + 磁力摘要”

## 行为说明

- 所有命令与快捷触发均为管理员权限。
- 磁力查询默认自动串联：
  1. 查 `GET /api/movies/{movieId}` 获取 `gid/uc`
  2. 再查 `GET /api/magnets/{movieId}?gid=...&uc=...`
- 输出优先 `Nodes`，平台不支持时回退纯文本。
- `list/search` 结果默认图文混排（每条尽量附带封面图）。
- 详情默认发送封面图（可配置关闭）。
- JavBus 图片默认走代理，支持两种格式：
  - 域名替换：`http://javbus.img.master.us.kg/pics/thumb/c674.jpg`
  - query 透传：`http://javbus.img.master.us.kg?url=https://www.javbus.com/pics/thumb/c674.jpg`

## 默认配置

- `base_url`: `https://javbus-api-from-ovnrain-git-main-cloudcranes-projects-58ddcac5.vercel.app`
- `timeout_sec`: `20`
- `auto_shortcut`: `true`
- `default_page_size`: `10`
- `send_cover`: `true`
- `image_proxy_enable`: `true`
- `image_proxy_base`: `http://javbus.img.master.us.kg`
- `image_proxy_mode`: `replace`（可改 `query`）
- `use_nodes`: `true`

## 备注

- 该插件直连上游 API，不做本地持久缓存。
- 如果上游接口开启 `j-auth-token` 鉴权，请在 `auth_token` 中配置。
