from __future__ import annotations

from typing import Any
import re
import urllib.parse

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.message_components import Image, Node, Nodes, Plain
from astrbot.api.star import Context, Star

from .service import (
    JavBusAuthError,
    JavBusClient,
    JavBusError,
    JavBusNotFoundError,
    JavBusRequestError,
    JavBusResponseError,
    JavBusTimeoutError,
    MissingMagnetParamsError,
    normalize_movie_id,
    try_normalize_movie_id,
)


DEFAULT_BASE_URL = "https://javbus-api-from-ovnrain-git-main-cloudcranes-projects-58ddcac5.vercel.app"
DEFAULT_PAGE_SIZE = 10
DEFAULT_IMAGE_PROXY_BASE = "http://javbus.img.master.us.kg"
_NODES_SUPPORTED_PLATFORMS = {"aiocqhttp", "satori"}
_MOVIE_SHORTCUT_RE = re.compile(r"(?i)^[a-z]{2,10}-?\d{2,6}$")


class Main(Star):
    def __init__(self, context: Context, config: AstrBotConfig | None = None) -> None:
        super().__init__(context, config)
        self.config = config or {}

    @filter.command_group("bus")
    def bus(self) -> None:
        """JavBus API 指令组。"""

    @filter.permission_type(filter.PermissionType.ADMIN)
    @bus.command("help")
    async def bus_help(self, event: AstrMessageEvent):
        lines = [
            "JavBus API 解析插件",
            "",
            "命令：",
            "1) /bus list [page]",
            "2) /bus search <keyword> [page]",
            "3) /bus detail <movie_id>",
            "4) /bus magnets <movie_id> [sortBy] [sortOrder]",
            "5) /bus star <star_id>",
            "6) /bus help",
            "",
            "快捷：直接发送番号（例如 SSIS-960 / IPX585）",
            "",
            "默认参数：",
            f"- base_url={DEFAULT_BASE_URL}",
            f"- default_page_size={DEFAULT_PAGE_SIZE}",
            f"- image_proxy_base={DEFAULT_IMAGE_PROXY_BASE}",
        ]
        yield self._build_message(event, "JavBus 使用说明", ["\n".join(lines)])

    @filter.permission_type(filter.PermissionType.ADMIN)
    @bus.command("list")
    async def bus_list(self, event: AstrMessageEvent, page: str = "1"):
        client = self._build_client()
        page_no = self._safe_page(page)
        try:
            data = client.list_movies(page=page_no)
            movies = data.get("movies", []) if isinstance(data, dict) else []
            page_size = self._get_int_config("default_page_size", DEFAULT_PAGE_SIZE, 1, 50)
            show_movies = movies[:page_size]

            summary = [f"第 {page_no} 页，返回 {len(movies)} 条，展示 {len(show_movies)} 条"]
            yield self._build_movie_cards_message(
                event=event,
                title="影片列表",
                movies=show_movies,
                summary_lines=summary,
                pagination_line=self._pagination_line(data),
                force_cover=True,
            )
        except Exception as exc:
            logger.exception("[JavBus] /bus list 失败")
            yield event.plain_result(f"查询失败：{self._render_error(exc)}")

    @filter.permission_type(filter.PermissionType.ADMIN)
    @bus.command("search")
    async def bus_search(self, event: AstrMessageEvent, keyword: str = "", page: str = "1"):
        kw = (keyword or "").strip()
        if not kw:
            yield event.plain_result("参数错误：请提供搜索关键词，例如 /bus search 三上 1")
            return

        client = self._build_client()
        page_no = self._safe_page(page)
        try:
            data = client.search_movies(keyword=kw, page=page_no)
            movies = data.get("movies", []) if isinstance(data, dict) else []
            page_size = self._get_int_config("default_page_size", DEFAULT_PAGE_SIZE, 1, 50)
            show_movies = movies[:page_size]

            summary = [f"关键词：{kw}", f"第 {page_no} 页，返回 {len(movies)} 条，展示 {len(show_movies)} 条"]
            yield self._build_movie_cards_message(
                event=event,
                title="影片搜索",
                movies=show_movies,
                summary_lines=summary,
                pagination_line=self._pagination_line(data),
            )
        except Exception as exc:
            logger.exception("[JavBus] /bus search 失败")
            yield event.plain_result(f"查询失败：{self._render_error(exc)}")

    @filter.permission_type(filter.PermissionType.ADMIN)
    @bus.command("detail")
    async def bus_detail(self, event: AstrMessageEvent, movie_id: str = ""):
        if not movie_id:
            yield event.plain_result("参数错误：请提供番号，例如 /bus detail SSIS-960")
            return

        client = self._build_client()
        try:
            normalized = normalize_movie_id(movie_id)
            detail = client.movie_detail(normalized)
            title = str(detail.get("title", normalized))
            sections = self._detail_sections(detail)
            cover = str(detail.get("img", "") or "")
            yield self._build_message(
                event,
                f"影片详情 | {normalized}",
                sections,
                cover_url=cover if self._get_bool_config("send_cover", True) else None,
            )
        except Exception as exc:
            logger.exception("[JavBus] /bus detail 失败")
            yield event.plain_result(f"查询失败：{self._render_error(exc)}")

    @filter.permission_type(filter.PermissionType.ADMIN)
    @bus.command("magnets")
    async def bus_magnets(
        self,
        event: AstrMessageEvent,
        movie_id: str = "",
        sort_by: str = "",
        sort_order: str = "",
    ):
        if not movie_id:
            yield event.plain_result("参数错误：请提供番号，例如 /bus magnets SSIS-960 size desc")
            return

        client = self._build_client()
        try:
            normalized = normalize_movie_id(movie_id)
            sort_by_text = self._normalize_sort_by(sort_by)
            sort_order_text = self._normalize_sort_order(sort_order)
            detail, magnets, context = client.magnets_by_movie_auto(
                movie_id=normalized,
                sort_by=sort_by_text,
                sort_order=sort_order_text,
            )

            page_size = self._get_int_config("default_page_size", DEFAULT_PAGE_SIZE, 1, 50)
            show_magnets = magnets[:page_size]
            sections = self._magnets_sections(show_magnets, context.gid, context.uc)
            cover = str(detail.get("img", "") or "")
            yield self._build_message(
                event,
                f"磁力链接 | {context.movie_id}",
                sections,
                cover_url=cover if self._get_bool_config("send_cover", True) else None,
            )
        except Exception as exc:
            logger.exception("[JavBus] /bus magnets 失败")
            yield event.plain_result(f"查询失败：{self._render_error(exc)}")

    @filter.permission_type(filter.PermissionType.ADMIN)
    @bus.command("star")
    async def bus_star(self, event: AstrMessageEvent, star_id: str = ""):
        sid = (star_id or "").strip()
        if not sid:
            yield event.plain_result("参数错误：请提供演员 ID，例如 /bus star 2xi")
            return

        client = self._build_client()
        try:
            detail = client.star_detail(sid)
            sections = self._star_sections(detail)
            cover = str(detail.get("avatar", "") or "")
            yield self._build_message(
                event,
                f"演员详情 | {sid}",
                sections,
                cover_url=cover if self._get_bool_config("send_cover", True) else None,
            )
        except Exception as exc:
            logger.exception("[JavBus] /bus star 失败")
            yield event.plain_result(f"查询失败：{self._render_error(exc)}")

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.regex(r"(?i)^[a-z]{2,10}-?\d{2,6}$")
    async def bus_shortcut(self, event: AstrMessageEvent):
        if not self._get_bool_config("auto_shortcut", True):
            return

        raw = (event.get_message_str() or "").strip()
        if not _MOVIE_SHORTCUT_RE.fullmatch(raw):
            return
        normalized = try_normalize_movie_id(raw)
        if not normalized:
            return

        client = self._build_client()
        try:
            detail, magnets, _ = client.magnets_by_movie_auto(movie_id=normalized)
            page_size = self._get_int_config("default_page_size", DEFAULT_PAGE_SIZE, 1, 50)
            show_magnets = magnets[:page_size]

            sections = self._detail_sections(detail)
            sections.extend(self._magnets_sections(show_magnets, str(detail.get("gid", "")), str(detail.get("uc", ""))))
            cover = str(detail.get("img", "") or "")
            yield self._build_message(
                event,
                f"番号快捷解析 | {normalized}",
                sections,
                cover_url=cover if self._get_bool_config("send_cover", True) else None,
            )
        except Exception as exc:
            logger.exception("[JavBus] 快捷解析失败")
            yield event.plain_result(f"查询失败：{self._render_error(exc)}")

    def _build_client(self) -> JavBusClient:
        return JavBusClient(
            base_url=self._get_str_config("base_url", DEFAULT_BASE_URL),
            auth_token=self._get_str_config("auth_token", ""),
            timeout_sec=self._get_int_config("timeout_sec", 20, 1, 120),
        )

    @staticmethod
    def _safe_page(text: str) -> int:
        try:
            value = int(str(text).strip())
        except (TypeError, ValueError):
            value = 1
        return max(1, value)

    @staticmethod
    def _normalize_sort_by(text: str) -> str | None:
        value = str(text or "").strip().lower()
        if value in {"date", "size"}:
            return value
        return None

    @staticmethod
    def _normalize_sort_order(text: str) -> str | None:
        value = str(text or "").strip().lower()
        if value in {"asc", "desc"}:
            return value
        return None

    @staticmethod
    def _movie_line(index: int, movie: dict[str, Any]) -> str:
        movie_id = str(movie.get("id", "-") or "-")
        title = str(movie.get("title", "-") or "-").replace("\n", " ").strip()
        date = str(movie.get("date", "-") or "-")
        tags = movie.get("tags", [])
        tag_text = ""
        if isinstance(tags, list) and tags:
            tag_text = f" | 标签: {', '.join(str(t) for t in tags[:5])}"
        return f"{index}. [{movie_id}] {title} | 日期: {date}{tag_text}"

    def _build_movie_cards_message(
        self,
        event: AstrMessageEvent,
        title: str,
        movies: list[dict[str, Any]],
        summary_lines: list[str],
        pagination_line: str,
        force_cover: bool = False,
    ):
        # 约定：列表/搜索结果优先图文卡片，便于快速浏览并减少二次查询。
        page_size = self._get_int_config("default_page_size", DEFAULT_PAGE_SIZE, 1, 50)
        send_cover = force_cover or self._get_bool_config("send_cover", True)

        if self._supports_nodes(event):
            node_uin = event.get_self_id() or event.get_sender_id() or "0"
            node_name = "JavBus"
            nodes: list[Node] = [
                Node(content=[Plain("\n".join([title] + summary_lines))], name=node_name, uin=node_uin)
            ]

            if movies:
                for idx, movie in enumerate(movies[:page_size], start=1):
                    content = [Plain(self._movie_line(idx, movie))]
                    cover_url = self._proxy_image_url(str(movie.get("img", "") or ""))
                    if send_cover and cover_url.startswith(("http://", "https://")):
                        try:
                            content.append(Image.fromURL(cover_url))
                        except Exception:
                            content.append(Plain(f"封面: {cover_url}"))
                    elif cover_url:
                        content.append(Plain(f"封面: {cover_url}"))
                    nodes.append(Node(content=content, name=node_name, uin=node_uin))
            else:
                nodes.append(Node(content=[Plain("当前页无数据。")], name=node_name, uin=node_uin))

            nodes.append(Node(content=[Plain(pagination_line)], name=node_name, uin=node_uin))
            return event.chain_result([Nodes(nodes)])

        # 非 Nodes 平台回退：尽量用链式消息保留图文效果。
        chain: list[Any] = [Plain("\n".join([title] + summary_lines))]
        if movies:
            for idx, movie in enumerate(movies[:page_size], start=1):
                chain.append(Plain("\n\n" + self._movie_line(idx, movie)))
                cover_url = self._proxy_image_url(str(movie.get("img", "") or ""))
                if send_cover and cover_url.startswith(("http://", "https://")):
                    try:
                        chain.append(Image.fromURL(cover_url))
                    except Exception:
                        chain.append(Plain(f"\n封面: {cover_url}"))
                elif cover_url:
                    chain.append(Plain(f"\n封面: {cover_url}"))
        else:
            chain.append(Plain("\n\n当前页无数据。"))
        chain.append(Plain(f"\n\n{pagination_line}"))
        return event.chain_result(chain)

    @staticmethod
    def _pagination_line(data: dict[str, Any]) -> str:
        pagination = data.get("pagination", {})
        if not isinstance(pagination, dict):
            return "分页：无"
        current_page = pagination.get("currentPage", "-")
        has_next = pagination.get("hasNextPage", False)
        next_page = pagination.get("nextPage", "-")
        return f"分页：current={current_page}, hasNext={has_next}, next={next_page}"

    @staticmethod
    def _detail_sections(detail: dict[str, Any]) -> list[str]:
        directors = detail.get("director", {}) or {}
        producer = detail.get("producer", {}) or {}
        publisher = detail.get("publisher", {}) or {}
        series = detail.get("series", {}) or {}
        stars = detail.get("stars", []) or []
        genres = detail.get("genres", []) or []
        samples = detail.get("samples", []) or []
        similar = detail.get("similarMovies", []) or []

        star_names = [str(item.get("name", "")) for item in stars if isinstance(item, dict)]
        genre_names = [str(item.get("name", "")) for item in genres if isinstance(item, dict)]

        base = [
            f"番号: {detail.get('id', '-')}",
            f"标题: {detail.get('title', '-')}",
            f"日期: {detail.get('date', '-')}",
            f"时长: {detail.get('videoLength', '-')} 分钟",
            f"导演: {directors.get('name', '-')}",
            f"制作商: {producer.get('name', '-')}",
            f"发行商: {publisher.get('name', '-')}",
            f"系列: {series.get('name', '-') if isinstance(series, dict) else '-'}",
            f"演员: {', '.join(star_names) if star_names else '-'}",
            f"类型: {', '.join(genre_names[:12]) if genre_names else '-'}",
            f"样品图数量: {len(samples) if isinstance(samples, list) else 0}",
            f"gid: {detail.get('gid', '-')}",
            f"uc: {detail.get('uc', '-')}",
        ]

        similar_lines = ["同类影片："]
        if isinstance(similar, list) and similar:
            for idx, item in enumerate(similar[:8], start=1):
                if not isinstance(item, dict):
                    continue
                similar_lines.append(
                    f"{idx}. [{item.get('id', '-')}] {item.get('title', '-')}"
                )
        else:
            similar_lines.append("无")
        return ["\n".join(base), "\n".join(similar_lines)]

    @staticmethod
    def _magnets_sections(magnets: list[dict[str, Any]], gid: str, uc: str) -> list[str]:
        header = [
            "磁力查询参数：",
            f"gid={gid}",
            f"uc={uc}",
            f"返回磁力数量: {len(magnets)}",
        ]
        lines = ["磁力列表："]
        if magnets:
            for idx, item in enumerate(magnets, start=1):
                title = str(item.get("title", "-"))
                size = str(item.get("size", "-"))
                date = str(item.get("shareDate", "-"))
                is_hd = "是" if bool(item.get("isHD", False)) else "否"
                subtitle = "是" if bool(item.get("hasSubtitle", False)) else "否"
                link = str(item.get("link", "-"))
                lines.extend(
                    [
                        f"{idx}. {title}",
                        f"   大小: {size} | 日期: {date} | 高清: {is_hd} | 字幕: {subtitle}",
                        f"   {link}",
                    ]
                )
        else:
            lines.append("无可用磁力。")
        return ["\n".join(header), "\n".join(lines)]

    @staticmethod
    def _star_sections(detail: dict[str, Any]) -> list[str]:
        lines = [
            f"演员ID: {detail.get('id', '-')}",
            f"姓名: {detail.get('name', '-')}",
            f"生日: {detail.get('birthday', '-')}",
            f"年龄: {detail.get('age', '-')}",
            f"身高: {detail.get('height', '-')}",
            f"胸围: {detail.get('bust', '-')}",
            f"腰围: {detail.get('waistline', '-')}",
            f"臀围: {detail.get('hipline', '-')}",
            f"出生地: {detail.get('birthplace', '-')}",
            f"爱好: {detail.get('hobby', '-')}",
        ]
        return ["\n".join(lines)]

    def _build_message(
        self,
        event: AstrMessageEvent,
        title: str,
        sections: list[str],
        cover_url: str | None = None,
    ):
        cover_url = self._proxy_image_url(cover_url or "") if cover_url else None
        if not self._supports_nodes(event):
            blocks = [title] + [section for section in sections if section]
            text = "\n\n".join(blocks)
            if cover_url:
                text += f"\n\n封面: {cover_url}"
            return event.plain_result(text)

        node_uin = event.get_self_id() or event.get_sender_id() or "0"
        node_name = "JavBus"
        nodes: list[Node] = []

        header_content = [Plain(title)]
        if cover_url and cover_url.startswith(("http://", "https://")):
            try:
                header_content.append(Image.fromURL(cover_url))
            except Exception:
                header_content.append(Plain(f"封面: {cover_url}"))
        elif cover_url:
            header_content.append(Plain(f"封面: {cover_url}"))
        nodes.append(Node(content=header_content, name=node_name, uin=node_uin))

        for section in sections:
            if not section:
                continue
            nodes.append(Node(content=[Plain(section)], name=node_name, uin=node_uin))
        return event.chain_result([Nodes(nodes)])

    def _proxy_image_url(self, image_url: str) -> str:
        """
        将 JavBus 图片地址重写为代理地址。
        支持两种模式：
        - replace: http://javbus.img.master.us.kg/pics/thumb/xxx.jpg
        - query:   http://javbus.img.master.us.kg?url=https://www.javbus.com/pics/thumb/xxx.jpg
        """
        raw = (image_url or "").strip()
        if not raw:
            return raw
        if not self._get_bool_config("image_proxy_enable", True):
            return raw

        proxy_base = self._get_str_config("image_proxy_base", DEFAULT_IMAGE_PROXY_BASE).rstrip("/")
        if not proxy_base:
            return raw
        mode = self._get_str_config("image_proxy_mode", "replace").lower()
        if mode not in {"replace", "query"}:
            mode = "replace"

        try:
            parsed = urllib.parse.urlparse(raw)
            proxy_parsed = urllib.parse.urlparse(proxy_base)
            if not parsed.scheme or not parsed.netloc:
                return raw
            if parsed.netloc.lower() == proxy_parsed.netloc.lower():
                return raw

            # 仅代理 javbus 站点图片链接，避免误改其他资源。
            source_host = parsed.netloc.lower()
            if source_host not in {"www.javbus.com", "javbus.com"}:
                return raw
            if not parsed.path.startswith("/pics/"):
                return raw

            if mode == "query":
                query = urllib.parse.urlencode({"url": raw})
                return f"{proxy_base}?{query}"

            path = parsed.path or "/"
            new_url = proxy_base + path
            if parsed.query:
                new_url += f"?{parsed.query}"
            return new_url
        except Exception:
            return raw

    def _supports_nodes(self, event: AstrMessageEvent) -> bool:
        if not self._get_bool_config("use_nodes", True):
            return False
        platform_name = (event.get_platform_name() or "").lower()
        return platform_name in _NODES_SUPPORTED_PLATFORMS

    def _get_config_value(self, key: str, default: Any) -> Any:
        if hasattr(self.config, "get"):
            try:
                return self.config.get(key, default)
            except Exception:
                return default
        return default

    def _get_bool_config(self, key: str, default: bool) -> bool:
        value = self._get_config_value(key, default)
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            text = value.strip().lower()
            if text in {"1", "true", "yes", "on"}:
                return True
            if text in {"0", "false", "no", "off"}:
                return False
        return bool(value)

    def _get_str_config(self, key: str, default: str) -> str:
        value = self._get_config_value(key, default)
        return str(value).strip() if value is not None else default

    def _get_int_config(self, key: str, default: int, min_value: int, max_value: int) -> int:
        value = self._get_config_value(key, default)
        try:
            value_int = int(value)
        except (TypeError, ValueError):
            value_int = default
        return max(min_value, min(max_value, value_int))

    @staticmethod
    def _render_error(exc: Exception) -> str:
        if isinstance(exc, JavBusAuthError):
            return "鉴权失败，请检查 auth_token 配置。"
        if isinstance(exc, JavBusNotFoundError):
            return "资源不存在。"
        if isinstance(exc, JavBusTimeoutError):
            return "请求超时，请稍后重试。"
        if isinstance(exc, MissingMagnetParamsError):
            return str(exc)
        if isinstance(exc, JavBusResponseError):
            return str(exc)
        if isinstance(exc, JavBusRequestError):
            return str(exc)
        if isinstance(exc, JavBusError):
            return str(exc)
        return f"未知错误：{exc}"
