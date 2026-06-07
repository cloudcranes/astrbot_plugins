from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
from astrbot.api import logger
from astrbot.core.star.star_handler import star_handlers_registry, StarHandlerMetadata
from astrbot.core.star.filter.command import CommandFilter
from astrbot.core.star.filter.command_group import CommandGroupFilter

@register(
    "astrbot_plugin_local_plugins",
    "cloudcranes",
    "查询已加载插件的名称、版本、作者、描述、命令等信息",
    "1.2.0",
    "https://github.com/cloudcranes/astrbot_plugins/astrbot_plugin_local_plugins",
)
class LocalPluginsQuery(Star):
    def __init__(self, context: Context, config: dict = None):
        super().__init__(context)
        self.config = config or {}
        self.exclude_plugins = set(self.config.get("exclude_plugins", []))
        self._last_list: dict[str, list] = {}

    def _get_session_id(self, event: AstrMessageEvent) -> str:
        gid = event.get_group_id()
        if gid:
            return f"group:{gid}"
        return f"user:{event.get_sender_id()}"

    def _get_stars(self):
        try:
            all_stars = self.context.get_all_stars()
            return [s for s in all_stars if s.activated]
        except Exception as e:
            logger.error(f"获取插件列表失败：{e}")
            return []

    def _build_list(self):
        stars = self._get_stars()
        if not stars:
            return [], []
        result = []
        lines = []
        idx = 1
        for star in stars:
            name = getattr(star, "name", "未知")
            if name == "astrbot_plugin_local_plugins" or name in self.exclude_plugins:
                continue
            version = getattr(star, "version", "?")
            result.append(star)
            lines.append(f"{idx}. 【{name}】v{version}")
            idx += 1
        return result, lines

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("plugins")
    async def plugins(self, event: AstrMessageEvent, subcommand: str = "", arg: str = ""):
        subcommand = subcommand.strip().lower()

        if not subcommand or subcommand == "list":
            stars, lines = self._build_list()
            if not lines:
                yield event.plain_result("没有找到其他已激活的插件")
                return
            sid = self._get_session_id(event)
            self._last_list[sid] = stars
            yield event.plain_result(
                f"📦 已加载插件（共 {len(lines)} 个）：\n"
                + "\n".join(lines)
                + "\n\n<发送 /plugins 序号> 查看详情"
            )
            return

        if subcommand == "info":
            if not arg:
                yield event.plain_result("用法：/plugins info <插件名称或序号>")
                return
            yield event.plain_result(self._get_detail(event, arg.strip()))
            return

        if subcommand.isdigit():
            yield event.plain_result(self._get_detail_by_index(event, int(subcommand)))
            return

        yield event.plain_result(self._get_detail_by_name(subcommand))

    def _get_detail(self, event: AstrMessageEvent, query: str) -> str:
        if query.isdigit():
            return self._get_detail_by_index(event, int(query))
        return self._get_detail_by_name(query)

    def _get_detail_by_index(self, event: AstrMessageEvent, idx: int) -> str:
        sid = self._get_session_id(event)
        stars = self._last_list.get(sid, [])
        if not stars:
            return "请先执行 /plugins list 刷新列表"
        if idx < 1 or idx > len(stars):
            return f"序号越界，请输入 1-{len(stars)} 之间的数字"
        return self._format_detail(stars[idx - 1])

    def _get_detail_by_name(self, query: str) -> str:
        stars = self._get_stars()
        if not stars:
            return "没有找到任何已激活的插件"
        matched = None
        q = query.lower()
        for star in stars:
            name = getattr(star, "name", "")
            if name.lower() == q or name == query:
                matched = star
                break
        if not matched:
            for star in stars:
                name = getattr(star, "name", "")
                if name.lower().startswith(q):
                    matched = star
                    break
        if not matched:
            return f"未找到名称包含「{query}」的已激活插件"
        return self._format_detail(matched)

    def _get_commands(self, module_path: str) -> list[str]:
        cmds = []
        seen = set()
        for handler in star_handlers_registry:
            if not isinstance(handler, StarHandlerMetadata):
                continue
            if handler.handler_module_path != module_path:
                continue
            cmd = None
            for flt in handler.event_filters:
                if isinstance(flt, CommandFilter):
                    cmd = flt.command_name
                    break
                if isinstance(flt, CommandGroupFilter):
                    cmd = flt.group_name
                    break
            if cmd and cmd not in seen:
                seen.add(cmd)
                cmds.append(cmd)
        return cmds

    def _format_detail(self, star) -> str:
        name = getattr(star, "name", "未知")
        version = getattr(star, "version", "未知")
        author = getattr(star, "author", "未知")
        desc = getattr(star, "desc", "无描述")
        module_path = getattr(star, "module_path", "")
        cmds = self._get_commands(module_path) if module_path else []

        lines = [
            f"📋 插件详情",
            f"名称：{name}",
            f"版本：{version}",
            f"作者：{author}",
            f"描述：{desc}",
        ]
        if cmds:
            lines.append(f"命令：{', '.join(cmd for cmd in cmds)}")
        if module_path:
            lines.append(f"路径：{module_path}")
        return "\n".join(lines)

    async def terminate(self):
        pass
