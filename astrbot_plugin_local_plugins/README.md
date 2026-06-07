# astrbot_plugin_local_plugins

查询已加载插件的名称、版本、作者、描述等信息。

## 命令

| 命令 | 说明 |
|------|------|
| `/plugins` 或 `/plugins list` | 列出所有已激活插件（带序号） |
| `/plugins <序号>` | 查看对应序号的插件详情 |
| `/plugins info <名称或序号>` | 查看指定插件详情 |

## 权限

仅管理员可执行。

## 配置

- `exclude_plugins`：列表中隐藏的插件名列表。
