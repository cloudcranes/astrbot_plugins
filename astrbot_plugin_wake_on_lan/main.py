import asyncio
import json
import socket
import re
from pathlib import Path
from typing import Dict, Optional
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
from astrbot.api import logger, AstrBotConfig

try:
    import redis
except ImportError:
    redis = None


@register("Wake-on-LAN", "cloudcranesss", "通过发送魔术包唤醒局域网内的设备", "1.0.0",
          "https://github.com/cloudcranesss/astrbot_plugins/astrbot_plugin_wake_on_lan")
class WakeOnLan(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config
        self.whitelist = self.config.get("whitelist", [])
        self._storage_path = Path(__file__).parent / "devices.json"
        self._storage_type = self.config.get("storage_type", "redis")
        self._redis_enabled = True
        self._redis_client = None
        self._init_redis()
        self.devices = self._load_devices()
        logger.info(f"Wake-on-LAN 插件初始化完成，已加载 {len(self.devices)} 个设备")

    def _is_allowed(self, user_id: str) -> bool:
        if not self.whitelist:
            return True
        return user_id in self.whitelist

    def _init_redis(self):
        storage_type = self.config.get("storage_type", "local")
        self._storage_type = storage_type
        
        if storage_type != "redis":
            logger.info(f"存储类型为 {storage_type}，跳过 Redis 初始化")
            return
        
        redis_host = self.config.get("redis_host") or self.config.get("redis-host", "")
        redis_port = self.config.get("redis_port") or self.config.get("redis-port", 6379)
        redis_password = self.config.get("redis_password") or self.config.get("redis-password", "")
        redis_db = self.config.get("redis_db") or self.config.get("redis-db", 0)
        
        logger.info(f"尝试连接 Redis: host={redis_host}, port={redis_port}, db={redis_db}")
        
        if not redis:
            logger.error("redis 库未安装，请运行: pip install redis")
            yield event.plain_result("❌ Redis 库未安装，请运行 pip install redis")
            return
            
        if redis_host:
            try:
                self._redis_client = redis.Redis(
                    host=redis_host,
                    port=redis_port,
                    password=redis_password if redis_password else None,
                    db=redis_db,
                    decode_responses=True
                )
                self._redis_client.ping()
                self._redis_enabled = True
                logger.info(f"Redis 连接成功: {redis_host}:{redis_port}")
            except Exception as e:
                logger.error(f"Redis 连接失败: {e}")
                self._redis_enabled = False
        elif not redis_host:
            logger.warning("存储类型设为 redis 但未配置 redis_host")

    def _load_devices(self) -> Dict[str, Dict[str, str]]:
        if self._storage_type == "redis" and self._redis_enabled and self._redis_client:
            try:
                data = self._redis_client.get("wake_on_lan:devices")
                if data:
                    devices = json.loads(data)
                    if isinstance(devices, dict):
                        logger.info(f"从 Redis 加载了 {len(devices)} 个设备")
                        return devices
            except Exception as e:
                logger.error(f"从 Redis 加载设备失败: {e}")
        
        if self._storage_path.exists():
            try:
                with open(self._storage_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        logger.info(f"从本地文件加载了 {len(data)} 个设备")
                        return data
            except Exception as e:
                logger.error(f"加载本地设备文件失败: {e}")
        
        devices = {}
        devices_config = self.config.get("devices", [])
        for device in devices_config:
            name = device.get("name", "")
            mac = device.get("mac", "").upper()
            broadcast = device.get("broadcast", "255.255.255.255")
            port = device.get("port", 9)
            if name and mac:
                devices[name] = {"mac": mac, "broadcast": broadcast, "port": port}
        
        if devices:
            self._save_devices(devices)
        return devices

    def _save_devices(self, devices: Dict[str, Dict[str, str]] = None):
        if devices is None:
            devices = self.devices
        
        if self._storage_type == "redis" and self._redis_enabled and self._redis_client:
            try:
                self._redis_client.set("wake_on_lan:devices", json.dumps(devices, ensure_ascii=False))
                logger.info("设备已保存到 Redis")
                return
            except Exception as e:
                logger.error(f"保存设备到 Redis 失败: {e}")
        
        try:
            with open(self._storage_path, "w", encoding="utf-8") as f:
                json.dump(devices, f, ensure_ascii=False, indent=2)
            logger.info(f"设备已保存到本地文件: {self._storage_path}")
        except Exception as e:
            logger.error(f"保存设备到本地文件失败: {e}")

    def _validate_mac(self, mac: str) -> bool:
        pattern = r'^([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$'
        return bool(re.match(pattern, mac))

    def _mac_to_bytes(self, mac: str) -> bytes:
        mac_clean = mac.replace(":", "").replace("-", "").replace(" ", "")
        return bytes.fromhex(mac_clean)

    async def _wake_device(self, mac: str, broadcast: str = "255.255.255.255", port: int = 9) -> bool:
        try:
            mac_bytes = self._mac_to_bytes(mac)
            magic_packet = b'\xff' * 6 + mac_bytes * 16

            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            sock.sendto(magic_packet, (broadcast, port))
            sock.close()
            logger.info(f"成功发送 Wake-on-LAN 魔术包到 {mac}")
            return True
        except Exception as e:
            logger.error(f"发送 Wake-on-LAN 魔术包失败: {e}")
            return False

    def _get_help(self) -> str:
        return """Wake-on-LAN 使用指南:
/wake on <设备名> - 唤醒指定设备
/wake ls - 查看已配置的设备
/wake add <设备名> <MAC> [广播] [端口] - 添加设备 (管理员)
/wake del <设备名> - 删除设备 (管理员)"""

    @filter.command("wake")
    async def wake_command(self, event: AstrMessageEvent, action: str = "", name: str = "", mac: str = "", broadcast: str = "255.255.255.255", port: int = 9):
        user_id = event.get_sender_id()
        action = action.strip().lower() if action else ""
        
        if not action or action == "help":
            yield event.plain_result(self._get_help())
            return

        if action == "ls" or action == "list":
            if not self.devices:
                yield event.plain_result("暂无已配置的设备，请使用 /wake add 添加")
                return
            result = ["已配置的设备:"]
            for dev_name, info in self.devices.items():
                result.append(f"• {dev_name}: {info['mac']} (广播: {info['broadcast']}, 端口: {info['port']})")
            yield event.plain_result("\n".join(result))
            return

        if action == "on":
            if not name:
                yield event.plain_result("用法: /wake on <设备名>")
                return
            if not self._is_allowed(user_id):
                yield event.plain_result("❌ 你没有权限执行此操作")
                return
            name = name.strip()
            if name not in self.devices:
                available = ", ".join(self.devices.keys()) if self.devices else "无"
                yield event.plain_result(f"未找到设备: {name}\n可用设备: {available}")
                return
            device = self.devices[name]
            yield event.plain_result(f"正在唤醒设备: {name} ({device['mac']}) ...")
            success = await self._wake_device(device['mac'], device['broadcast'], device['port'])
            if success:
                yield event.plain_result(f"✅ 设备 {name} 唤醒信号已发送！")
            else:
                yield event.plain_result(f"❌ 设备 {name} 唤醒失败")
            return

        if action == "add":
            if not name or not mac:
                yield event.plain_result("用法: /wake add <设备名> <MAC地址> [广播地址] [端口]\n示例: /wake add 客厅电脑 AA:BB:CC:DD:EE:FF")
                return
            if not self._is_allowed(user_id):
                yield event.plain_result("❌ 你没有权限执行此操作")
                return
            mac = mac.upper()
            if not self._validate_mac(mac):
                yield event.plain_result(f"MAC 地址格式错误: {mac}\n正确格式: AA:BB:CC:DD:EE:FF")
                return
            self.devices[name] = {"mac": mac, "broadcast": broadcast, "port": port}
            self._save_devices()
            logger.info(f"添加设备: {name} - {mac}")
            yield event.plain_result(f"✅ 设备 {name} (MAC: {mac}) 添加成功！")
            return

        if action == "del" or action == "delete" or action == "remove":
            if not name:
                yield event.plain_result("用法: /wake del <设备名称>")
                return
            if not self._is_allowed(user_id):
                yield event.plain_result("❌ 你没有权限执行此操作")
                return
            if name in self.devices:
                del self.devices[name]
                self._save_devices()
                logger.info(f"删除设备: {name}")
                yield event.plain_result(f"✅ 设备 {name} 已删除")
            else:
                yield event.plain_result(f"未找到设备: {name}")
            return

        yield event.plain_result(f"未知指令: {action}\n" + self._get_help())

    async def terminate(self):
        pass