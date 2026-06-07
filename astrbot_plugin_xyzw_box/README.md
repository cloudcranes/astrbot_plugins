# AstrBot 咸鱼之王宝箱识别插件

 *示例图片*

<img src="https://upyun.alanmaster.top//picgo202506142142270.png" width="150">
<img src="https://upyun.alanmaster.top//picgo202506142143282.png" width="245">

## 功能亮点

- 🖼 **智能截图识别** - 自动识别游戏截图中的宝箱数量和预设积分
- 🧮 **精确积分计算** - 实时计算宝箱积分和可完成轮数
- ⏱ **60秒超时控制** - 自动取消长时间未响应的识别请求
- 📊 **策略建议** - 提供下一轮所需积分和闯关推荐
- 🔄 **异步处理** - 高效处理并发请求，确保响应速度

## 安装指南

### 1. 克隆插件仓库
```bash
git clone https://github.com/cloudcranes/astrbot_plugins.git
cp -r astrbot_plugin_xyzw_box /AstrBot/data/plugins/
```

### 2. 安装依赖
```bash
pip install -r /AstrBot/data/plugins/astrbot_plugin_xyzw_box/requirements.txt
```

### 3. 配置插件
安装后在后台添加
```yaml
ocr_url: "https://api.ocr.space/parse/image"  # OCR服务地址
ocr_key: "your_ocr_api_key_here"              # OCR API密钥
```

### 4. 重启AstrBot
```bash
docker restart astrbot
```

## 使用教程

1. **触发识别流程**  
   在QQ聊天中发送命令：
   ```
   xyzw
   ```
   
2. **发送游戏截图**  
   在60秒内发送清晰的游戏界面截图：
   ```
   🖼️ 请发送宝箱截图（60秒内）
   ```

3. **获取分析结果**  
   等待5-10秒后获取详细分析：
   ```
   🔍 开始处理图片...
   ✅ 识别完成
   📦 木头箱: 12
   🥈 白银箱: 8
   🥇 黄金箱: 5
   💎 铂金箱: 3
   🔄 可完成轮数: 2
   🎯 当前积分: 328
   🚧 下一轮还需: 156
   ⚔️ 推荐闯关数: 62.4
   ```

## 配置选项

| 配置项     | 必需 | 默认值                             | 描述                     |
|------------|------|------------------------------------|--------------------------|
| `ocr_url`  | 是   | 无                                 | OCR服务API地址           |
| `ocr_key`  | 是   | 无                                 | OCR服务API密钥           |

## 截图要求

1. 完整包含游戏界面顶部的预设积分区域
2. 清晰显示底部的四种宝箱数量
3. 避免界面元素遮挡
4. 推荐使用游戏内截图功能（非拍照）

 *截图区域示意*

## 常见问题解决

### OCR识别失败
**错误信息**：`OCR服务错误: 400 - Invalid API key`  
**解决方案**：
1. 检查OCR服务API密钥是否正确
2. 确认OCR服务账户有足够额度
3. 尝试更换OCR服务提供商

### 图片处理失败
**错误信息**：`图片处理失败，请确保发送的是有效的游戏截图`  
**解决方案**：
1. 确保截图包含完整的游戏界面
2. 检查截图是否清晰无模糊
3. 确认截图格式为JPG或PNG

### 超时问题
**问题**：60秒内未发送截图导致超时  
**解决方案**：
1. 提前准备好截图再发送命令
2. 使用游戏内截图功能加速操作
3. 网络不佳时尝试重发

## 开发者信息

- **作者**：cloudcranes
- **版本**：1.0.1
- **更新日期**：2025-06-14
- **GitHub仓库**：[https://github.com/cloudcranes/astrbot_plugins/tree/main/astrbot_plugin_xyzw_box](https://github.com/cloudcranes/astrbot_plugins/tree/main/astrbot_plugin_xyzw_box)
- **问题反馈**：[Issues](https://github.com/cloudcranes/astrbot_plugins/issues)

## 开源协议

本项目采用 [MIT 开源协议](LICENSE) - 自由使用、修改和分发，需保留原始作者信息。

```
Copyright (c) 2025 cloudcranes

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.
```
