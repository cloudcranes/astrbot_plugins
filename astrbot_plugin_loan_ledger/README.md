# astrbot_plugin_loan_ledger

借款记录插件，支持：
- 自动从官网获取 1 年期 LPR（人行优先，拆借中心兜底）
- 借款分层记录（同借款人自动合并到同一账户）
- 还款按 FIFO 冲抵本金
- 按天单利、含起息日不含还款日
- 权限控制（管理员或白名单）

## 命令

1. `/loan help`
2. `/loan add <借款人> <金额> [借款日期] [计息开关]`
3. `/loan repay <借款人> <金额> [还款日期]`
4. `/loan show <借款人> [截止日期]`
5. `/loan list [截止日期]`

## 日期格式

- `YYYY-MM-DD`
- `M月D日`（默认当前年份）
- 借款日期与还款日期都可省略；省略时默认当天

## 计息开关

- 支持：`interest/nointerest/yes/no/true/false/计息/不计息/是/否`
- 不填时按配置 `default_interest_enabled`（默认 `true`）

## 权限规则

- 命令统一按“管理员 OR 白名单”放行
- 若非管理员且不在白名单，会返回：`无权限：你不在白名单且非管理员`
- 白名单按“全局用户ID”匹配，通过配置维护，不提供命令动态修改

## 数据存储

账本数据保存在：
`data/plugin_data/astrbot_plugin_loan_ledger/ledger.json`

写入方式为原子写入（先写临时文件再替换）。

## 配置项（_conf_schema.json）

- `pboc_index_url`：人行 LPR 公告列表页地址（默认已内置）
- `chinamoney_api_url`：拆借中心官网 LPR API（兜底）
- `enable_chinamoney_fallback`：是否启用兜底源，默认 `true`
- `http_timeout_sec`：官网请求超时秒数，默认 `15`
- `default_interest_enabled`：新增借款默认是否计息，默认 `true`
- `enable_user_whitelist`：是否启用白名单，默认 `true`；关闭后仅管理员可用
- `user_whitelist`：白名单用户ID字符串，支持逗号/换行分隔

示例：

```text
enable_user_whitelist = true
user_whitelist = "10001,10002
10003"
```
