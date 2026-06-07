import asyncio
import subprocess
import shutil
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
from astrbot.api import logger, AstrBotConfig


@register("Pip Manager", "cloudcranes", "管理 pip 包，支持安装、卸载、查看等操作", "1.0.0",
          "https://github.com/cloudcranes/astrbot_plugins/astrbot_plugin_pip_manager")
class PipManager(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config
        self.whitelist = self.config.get("whitelist", [])
        self.mirror = self.config.get("mirror", "default")
        self._mirror_urls = {
            "default": None,
            "tsinghua": "https://pypi.tuna.tsinghua.edu.cn/simple",
            "aliyun": "https://mirrors.aliyun.com/pypi/simple",
            "ustc": "https://pypi.mirrors.ustc.edu.cn/simple",
            "douban": "https://pypi.douban.com/simple",
            "huawei": "https://mirrors.huaweicloud.com/repository/pypi/simple"
        }
        logger.info(f"Pip Manager 插件初始化完成，当前软件源: {self.mirror}")

    def _is_allowed(self, user_id: str) -> bool:
        if not self.whitelist:
            return True
        return user_id in self.whitelist

    def _run_pip(self, args: list, use_mirror: bool = True) -> tuple[str, int]:
        pip_path = shutil.which("pip") or shutil.which("pip3") or "pip"
        full_args = [pip_path] + args
        
        if use_mirror and self.mirror != "default":
            mirror_url = self._mirror_urls.get(self.mirror)
            if mirror_url:
                full_args.extend(["-i", mirror_url])
        
        try:
            result = subprocess.run(
                full_args,
                capture_output=True,
                text=True,
                timeout=300
            )
            output = result.stdout + result.stderr
            return output, result.returncode
        except subprocess.TimeoutExpired:
            return "命令执行超时", 1
        except Exception as e:
            return f"执行失败: {e}", 1

    def _get_help(self) -> str:
        return """Pip 管理器使用指南:
/pip install <包名> - 安装包 (管理员)
/pip install <包名>==<版本> - 安装指定版本 (管理员)
/pip uninstall <包名> - 卸载包 (管理员)"""

    @filter.command("pip")
    async def pip_command(self, event: AstrMessageEvent, action: str = "", arg1: str = "", arg2: str = ""):
        user_id = event.get_sender_id()
        
        if not action or action == "help":
            yield event.plain_result(self._get_help())
            return

        action = action.strip().lower()

        if action == "install":
            if not arg1:
                yield event.plain_result("用法: /pip install <包名> [==版本]")
                return
            if not self._is_allowed(user_id):
                yield event.plain_result("❌ 你没有权限执行此操作")
                return
            pkg_name = arg1.strip()
            if arg2:
                pkg_name = f"{pkg_name}{arg2}"
            yield event.plain_result(f"正在安装: {pkg_name} ...")
            args = ["install", pkg_name, "--upgrade"]
            output, code = self._run_pip(args)
            if code == 0:
                yield event.plain_result(f"✅ 安装成功:\n{output[:1500]}")
            else:
                yield event.plain_result(f"❌ 安装失败:\n{output[:1500]}")
            return

        if action == "uninstall" or action == "remove":
            if not arg1:
                yield event.plain_result("用法: /pip uninstall <包名>")
                return
            if not self._is_allowed(user_id):
                yield event.plain_result("❌ 你没有权限执行此操作")
                return
            yield event.plain_result(f"正在卸载: {arg1} ...")
            args = ["uninstall", arg1.strip(), "-y"]
            output, code = self._run_pip(args, use_mirror=False)
            if code == 0:
                yield event.plain_result(f"✅ 卸载成功:\n{output}")
            else:
                yield event.plain_result(f"❌ 卸载失败:\n{output}")
            return

        yield event.plain_result(f"未知指令: {action}\n" + self._get_help())

    async def terminate(self):
        pass
