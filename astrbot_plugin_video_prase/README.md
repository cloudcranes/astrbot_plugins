# astrbot_plugin_video_prase

基于 [parse-video-py](https://github.com/wujunwei928/parse-video-py) 的 AstrBot 链接解析插件。

插件会自动识别聊天中的分享链接，调用 `parse-video-py` 接口解析，并以图文/视频方式回传结果。

## 功能特性

- 适配 `parse-video-py` 返回结构：优先 `{code,msg,data}`，兼容扁平 `VideoInfo`。
- 支持多平台链接识别：`douyin / x / twitter / bilibili / xiaohongshu / kuaishou / weibo ...`。
- 支持 QQ JSON 卡片提取真实链接。
- 支持视频、图集、live photo（按视频发送）统一渲染。
- 支持两种发送模式：`yield`（普通消息）与 `nodes`（合并转发）。

## 依赖

- AstrBot 运行环境
- Python 3.10+
- `aiohttp`

`requirements.txt`：

```txt
aiohttp
```

## 上游接口约定

默认请求：

```http
GET /video/share/url/parse?url=<分享链接>
```

主返回结构（推荐）：

```json
{
  "code": 200,
  "msg": "ok",
  "data": {
    "author": {"uid": "", "name": "", "avatar": ""},
    "title": "",
    "video_url": "",
    "cover_url": "",
    "music_url": "",
    "images": [
      {"url": "", "live_photo_url": ""}
    ],
    "source_platform": ""
  }
}
```

说明：

- 当 `code != 200` 时，插件直接返回 `msg` 作为错误文案。
- 当 `data` 缺失或字段不完整时，插件会给出“解析成功但数据不完整”的提示并尽量输出已有内容。

## 配置项

| 配置项 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `api_base_url` | string | `http://127.0.0.1:8000` | `parse-video-py` 服务基地址 |
| `api_parse_path` | string | `/video/share/url/parse` | 解析接口路径 |
| `timeout` | int | `30` | 请求超时（秒） |
| `send_method` | string | `yield` | 发送模式：`yield` 或 `nodes` |
| `image_proxy_prefix` | string | `""` | 媒体代理前缀（常用于 X/Twitter） |
| `MAX_MEDIA` | int | `6` | 图集与 live photo 最大发送数量 |
| `SEND_LIVE_PHOTO_AS_VIDEO` | bool | `true` | 是否将 `live_photo_url` 作为视频发送 |
| `SHOW_AUTHOR_AVATAR` | bool | `false` | `nodes` 模式下是否附加作者头像 |

## 消息发送行为

### `yield` 模式

按以下顺序发送：

1. 文本摘要（作者/标题/类型/来源/UID 等）
2. 封面图（如有）
3. 图集图片（最多 `MAX_MEDIA`）
4. 主视频（如有）
5. live photo 视频（开启开关时，最多 `MAX_MEDIA`）

### `nodes` 模式

将上述内容组装为合并转发节点发送。

## 破坏性变更（2.0.0）

本版本进行了配置重构：

- 移除旧配置：`api_url`
- 新增并替代：`api_base_url + api_parse_path`

若从旧版本升级，请同步更新插件配置。

## 故障排查

- 解析无响应：确认 `api_base_url` 与 `api_parse_path` 可访问。
- 返回失败：检查上游接口 `code/msg` 与日志输出。
- 图/视频发送异常：检查平台对外链媒体的支持与代理配置。

## 许可证

遵循本仓库插件的许可证约定。

