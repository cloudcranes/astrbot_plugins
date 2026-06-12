# AstrBot Wake-on-LAN 插件

通过发送魔术包（Magic Packet）唤醒局域网内的设备。

## 功能

- 唤醒已配置的设备
- 支持添加/删除设备
- 支持用户白名单限制
- 查看设备列表
- 支持本地 JSON 或 Redis 存储

## 指令

| 指令 | 说明 |
|------|------|
| `/wake` | 显示帮助信息 |
| `/wake ls` | 查看已配置的设备（MAC 会脱敏显示） |
| `/wake on <设备名>` | 唤醒指定设备 |
| `/wake add <设备名> <MAC> [广播地址] [端口]` | 添加新设备 |
| `/wake del <设备名>` | 删除设备 |

## 配置

在插件配置页面添加以下配置：

### 白名单（可选）

```
whitelist: [123456789, 987654321]
```
留空则允许所有人使用。

白名单会限制 `/wake ls`、`/wake on`、`/wake add`、`/wake del`。

### 存储方式

默认使用本地文件：

```yaml
storage_type: local
```

本地数据文件为插件目录下的 `devices.json`，这是运行时配置文件，请勿上传公开仓库。

如需使用 Redis：

```yaml
storage_type: redis
redis_host: 127.0.0.1
redis_port: 6379
redis_password: ""
redis_db: 0
```

### 设备列表

```json
{
  "name": "客厅电脑",
  "mac": "AA:BB:CC:DD:EE:FF",
  "broadcast": "255.255.255.255",
  "port": 9
}
```

- **name**: 设备名称
- **mac**: MAC 地址（格式：AA:BB:CC:DD:EE:FF）
- **broadcast**: 广播地址（默认 255.255.255.255）
- **port**: 端口号（默认 9）

## 安装

1. 将插件文件夹放入 AstrBot 插件目录
2. 重启 AstrBot
3. 在配置页面添加设备

## 依赖

本地文件存储无需额外依赖。

使用 Redis 存储时需要安装：

```bash
pip install "redis>=4.0.0"
```
