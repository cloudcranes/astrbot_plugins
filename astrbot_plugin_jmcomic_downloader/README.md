# AstrBot JMComic Downloader 插件

基于 `jmcomic` APP/API 客户端按 JM album id 下载漫画，使用账号密码登录，并通过 `jmcomic` 内置 `img2pdf` 插件生成 PDF。

## 功能

- 直接发送 `jm123456789` 格式下载漫画并生成 PDF。
- 同一 album 已生成过 PDF 时，会直接复用本地 PDF，不重复触发 jmcomic 下载。
- 运行时缺少 `jmcomic` / `img2pdf` 时自动安装依赖。
- `/jm dl <album_id>` 下载漫画并生成 PDF。
- `/jm clean` 清理超过保留期的下载目录、PDF 和 OpenList 文件。
- `/jm clean all` 立刻清理全部本地缓存和 OpenList `album_*` 目录。
- PDF 生成后上传到本地 OpenList，并通过 `Plain + File(url=...)` 同一消息链发送。
- 上传和发送时文件名使用 `<album_id>.pdf`，避免平台按标题风控。

## 指令

| 指令 | 权限 | 说明 |
| --- | --- | --- |
| `jm<album_id>` | 管理员或白名单 | 直接发送 `jm123456789` 格式下载 |
| `/jm help` | 所有人 | 查看帮助 |
| `/jm dl <album_id>` | 管理员或白名单 | 下载指定 album 并生成 PDF |
| `/jm clean` | 管理员或白名单 | 清理过期文件 |
| `/jm clean all` | 管理员或白名单 | 清理全部缓存和 OpenList `album_*` 目录 |

## 配置

| 配置项 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `whitelist` | list | `[]` | 下载白名单。管理员默认有权限；为空时仅管理员可下载和清理 |
| `auto_install_dependencies` | bool | `true` | 缺少 `jmcomic` / `img2pdf` 时自动安装依赖 |
| `download_dir` | string | `""` | 图片下载根目录。留空使用插件数据目录 |
| `retention_days` | int | `7` | 文件保留天数 |
| `max_send_mb` | int | `100` | 保留项。当前使用 OpenList URL 发送，不按本地大小限制 |
| `max_concurrent_downloads` | int | `1` | 最大并发下载数 |
| `app_domain` | string | `""` | 可选 JM APP/API 域名覆盖。留空使用 `jmcomic` 默认 APP 域名 |
| `jm_username` | string | `""` | JM 账号，用于 APP/API 登录 |
| `jm_password` | string | `""` | JM 密码，用于 APP/API 登录 |
| `proxy` | string | `""` | 可选代理地址 |
| `cookies` | string | `""` | 可选 Cookie |
| `openlist_base_url` | string | `""` | OpenList 站点地址，例如 `http://127.0.0.1:5244` |
| `openlist_public_base_url` | string | `""` | 公开访问地址。留空使用 `openlist_base_url` |
| `openlist_token` | string | `""` | OpenList API token，优先使用 |
| `openlist_username` | string | `""` | OpenList 用户名，token 留空时使用 |
| `openlist_password` | string | `""` | OpenList 密码，token 留空时使用 |
| `openlist_upload_dir` | string | `/jmcomic` | PDF 上传目录 |
| `openlist_cleanup_on_clean` | bool | `true` | 执行 `/jm clean` 时同步清理 OpenList 过期 `album_*` 目录 |

`jm_password`、`cookies`、`openlist_token`、`openlist_password` 都属于敏感配置，请不要上传。

## 数据位置

默认数据目录为 AstrBot 的 `StarTools.get_data_dir("astrbot_plugin_jmcomic_downloader")`：

- `downloads/`：原始图片下载目录。
- `pdf/`：生成的 PDF。
- `op.yml`：运行时自动生成的 jmcomic 配置，可能包含 Cookie。

## 依赖

```bash
pip install -r /AstrBot/data/plugins/astrbot_plugin_jmcomic_downloader/requirements.txt
```

默认也会在首次下载时自动安装缺失依赖；如需关闭，将 `auto_install_dependencies` 设为 `false`。

## 注意事项

- `album_id` 只支持纯数字。
- 真实下载依赖当前网络、JM APP/API 域名可用性、账号密码、Cookie 和代理配置。
- OpenList 上传使用 AList/OpenList 兼容接口：`/api/fs/mkdir`、`/api/fs/put`；公开 URL 按 `/d/<上传路径>` 拼接。
- OpenList 清理使用 `/api/fs/list` 和 `/api/fs/remove`，仅删除上传目录下超过保留期的 `album_*` 目录。
- 如果 URL 无法下载，请确认 OpenList 目录权限、公开访问地址和反向代理配置。
- 运行时目录和敏感配置已通过 `.gitignore` 排除。
