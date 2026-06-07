# astrbot_plugin_ip_parser

用于解析 IPv4 / IPv6 地址，并查询运营商、归属地等画像信息。

## 命令

- `/ip <地址>`
- `/ip help`

可选快捷解析：
- 直接发送纯 IP 文本（需配置 `auto_parse_plain=true`）。

## 当前输出（已精简）

- 输入地址、标准地址、IP 版本
- 运营商与归属地画像
  - 数据源、国家/地区/城市、邮编、时区
  - 运营商 ISP、组织、ASN/AS 名称
  - 坐标、移动网络/代理/机房标记（数据源支持时）

## 画像数据源

- `ip-api`（HTTP）
- `ipinfo`（HTTPS）
- `auto` 模式自动回退：`ip-api -> ipinfo`
