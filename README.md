# AstrBot Plugins

作者：`cloudcranes`

仓库：[cloudcranes/astrbot_plugins](https://github.com/cloudcranes/astrbot_plugins)

这里收录 `cloudcranes` 维护的 AstrBot 插件。其他作者插件不会纳入本仓库发布范围。

## 插件列表

| 插件目录 | 名称 | 版本 | 简介 |
| --- | --- | --- | --- |
| [`astrbot_plugin_ip_parser`](https://github.com/cloudcranes/astrbot_plugins/tree/main/astrbot_plugin_ip_parser) | IP 地址解析与归属地 | `0.2.0` | IPv4/IPv6 地址解析与运营商归属地查询插件 |
| [`astrbot_plugin_javbus_api`](https://github.com/cloudcranes/astrbot_plugins/tree/main/astrbot_plugin_javbus_api) | JavBus API 解析器 | `0.1.0` | 基于 javbus-api 的 JavBus 解析插件 |
| [`astrbot_plugin_jmcomic_downloader`](https://github.com/cloudcranes/astrbot_plugins/tree/main/astrbot_plugin_jmcomic_downloader) | JMComic Downloader | `0.1.0` | 按 JM album id 下载漫画，复用本地 PDF 缓存，上传 OpenList 后通过 URL 发送 |
| [`astrbot_plugin_loan_ledger`](https://github.com/cloudcranes/astrbot_plugins/tree/main/astrbot_plugin_loan_ledger) | 借款记录账本 | `0.1.0` | 借款记录与分段计息插件，支持自动抓取官方 1 年期 LPR |
| [`astrbot_plugin_local_plugins`](https://github.com/cloudcranes/astrbot_plugins/tree/main/astrbot_plugin_local_plugins) | 本地插件查询 | `v1.0.0` | 查询已加载插件的名称、版本、作者、描述等信息 |
| [`astrbot_plugin_magnet_preview`](https://github.com/cloudcranes/astrbot_plugins/tree/main/astrbot_plugin_magnet_preview) | Magnet Previewer | `1.2.0` | 预览磁力链接，并支持确认后下载 |
| [`astrbot_plugin_pip_manager`](https://github.com/cloudcranes/astrbot_plugins/tree/main/astrbot_plugin_pip_manager) | Pip Manager | `1.0.0` | 管理 pip 包，支持安装、卸载、查看等操作 |
| [`astrbot_plugin_video_prase`](https://github.com/cloudcranes/astrbot_plugins/tree/main/astrbot_plugin_video_prase) | 链接解析插件 | `2.0.0` | 适配 parse-video-py，支持视频、图集、live photo 统一渲染 |
| [`astrbot_plugin_wake_on_lan`](https://github.com/cloudcranes/astrbot_plugins/tree/main/astrbot_plugin_wake_on_lan) | Wake-on-LAN | `1.0.0` | 通过发送魔术包唤醒局域网内的设备 |
| [`astrbot_plugin_xyzw_box`](https://github.com/cloudcranes/astrbot_plugins/tree/main/astrbot_plugin_xyzw_box) | 咸鱼之王宝箱识别 | `1.0.1` | 通过 OCR 识别咸鱼之王游戏中的宝箱数量 |

## 安装方式

克隆仓库后，将需要的插件目录复制到 AstrBot 插件目录：

```bash
git clone https://github.com/cloudcranes/astrbot_plugins.git
cp -r astrbot_plugins/<插件目录> /AstrBot/data/plugins/
```

如果插件目录内存在 `requirements.txt`，请按需安装依赖：

```bash
pip install -r /AstrBot/data/plugins/<插件目录>/requirements.txt
```

## 注意事项

- 每个插件的具体命令、配置项和示例请查看对应目录下的 `README.md`。
- `astrbot_plugin_jmcomic_downloader` 依赖 JM 账号密码和 OpenList 配置；生成的 `op.yml`、下载目录和 PDF 缓存不会上传，`/jm clean all` 可清理本地缓存和 OpenList `album_*` 目录。
- `astrbot_plugin_wake_on_lan/devices.json` 属于本地运行配置，不会上传；仓库中仅提供 `devices.example.json` 示例。
- 上传或更新本仓库时，只发布作者为 `cloudcranes` 的插件。
