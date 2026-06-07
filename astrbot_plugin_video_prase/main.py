import asyncio



import aiohttp

from aiohttp import ClientSession, ClientTimeout

from astrbot.api import logger

from astrbot.api.event import AstrMessageEvent, filter

from astrbot.api.star import Context, Star, register

import astrbot.api.message_components as Comp



from .constants import HEADERS, MAX_RETRIES, RETRY_DELAY

from .utils import (

    NormalizedVideoInfo,

    _extract_from_raw_message,

    _try_parse_json,

    apply_image_proxy,

    extract_first_supported_url,

    normalize_response,

    should_apply_proxy,

)



DEFAULT_TIMEOUT = ClientTimeout(total=15)





@register(

    "video_parse",

    "cloudcranes",

    "解析多平台分享链接，提取视频/图集信息",

    "2.0.0",

    "https://github.com/cloudcranes/astrbot_plugins/astrbot_plugin_video_prase",

)

class VideoParsePlugin(Star):

    def __init__(self, context: Context, config):

        super().__init__(context)

        self.config = config



        self.timeout = int(self.config.get("timeout", 30))

        self.api_base_url = str(self.config.get("api_base_url", "http://127.0.0.1:8000")).rstrip("/")

        self.api_parse_path = str(self.config.get("api_parse_path", "/video/share/url/parse"))

        if not self.api_parse_path.startswith("/"):

            self.api_parse_path = f"/{self.api_parse_path}"

        self.api_url = f"{self.api_base_url}{self.api_parse_path}"



        self.image_proxy_prefix = self.config.get("image_proxy_prefix", "")

        self.send_method = self.config.get("send_method", "yield")

        self.max_media = max(1, min(int(self.config.get("MAX_MEDIA", 6)), 12))

        self.send_live_photo_as_video = self._parse_bool(

            self.config.get("SEND_LIVE_PHOTO_AS_VIDEO", True), True

        )

        self.show_author_avatar = self._parse_bool(

            self.config.get("SHOW_AUTHOR_AVATAR", False), False

        )



        self.trust_env = False

        self._session: aiohttp.ClientSession | None = None



    @staticmethod

    def _parse_bool(value, default: bool) -> bool:

        if isinstance(value, bool):

            return value

        if isinstance(value, str):

            norm = value.strip().lower()

            if norm in {"true", "1", "yes", "on"}:

                return True

            if norm in {"false", "0", "no", "off"}:

                return False

        return default



    async def _get_session(self) -> ClientSession:

        if self._session is None or self._session.closed:

            self._session = ClientSession(

                trust_env=self.trust_env,

                headers=HEADERS,

                timeout=DEFAULT_TIMEOUT,

            )

        return self._session



    @filter.event_message_type(filter.EventMessageType.ALL)

    async def on_message(self, event: AstrMessageEvent):

        text = (event.message_str or "").strip()



        json_url = ""

        if event.message_obj:

            json_url = _extract_from_raw_message(event.message_obj.raw_message)

            if not json_url and event.message_obj.message:

                for comp in event.message_obj.message:

                    raw = getattr(comp, "raw", None) or getattr(comp, "data", None)

                    if raw:

                        json_url = _extract_from_raw_message(raw)

                        if json_url:

                            break



        if not json_url and text.startswith("{"):

            json_url = _try_parse_json(text)



        if json_url:

            logger.info(f"[VideoParse] URL extracted from JSON card: {json_url}")

            text = json_url



        if not text:

            return



        url = extract_first_supported_url(text)

        if not url:

            return



        logger.info(f"[VideoParse] Detected share URL: {url}")



        try:

            session = await self._get_session()

            payload = await self.fetch_parse_info_with_retry(session, url)

            if not payload:

                yield event.plain_result("解析失败，请稍后重试")

                return



            normalized = normalize_response(payload)

            if normalized.error_message:

                yield event.plain_result(normalized.error_message)

                return



            info = normalized.info

            if info is None:

                yield event.plain_result("解析失败：返回数据为空")

                return



            info_text = self.build_info_text(info, normalized.warning_message)



            if self.send_method == "nodes":

                result = self.build_nodes_message(event, info, info_text, url)

                yield event.chain_result(result)

            else:

                async for msg in self.send_yield_message(event, info, info_text, url):

                    yield msg



        except Exception as exc:

            logger.error(f"[VideoParse] Parse error: {exc}")

            yield event.plain_result(f"解析出错：{str(exc)}")



    def build_info_text(self, info: NormalizedVideoInfo, warning: str = "") -> str:

        media_type = "video" if info.video_url else "gallery"

        if info.video_url and info.images:

            media_type = "video+gallery"



        platform = info.source_platform or "unknown"

        lines = [

            f"Author: {info.author_name}",

            f"Title: {info.title}",

            f"Type: {media_type}",

            f"Source: {platform}",

        ]



        if info.author_uid:

            lines.append(f"UID: {info.author_uid}")



        if info.music_url:

            lines.append("Music: yes")



        if warning:

            lines.append(f"Warning: {warning}")



        return "\n".join(lines)



    async def send_yield_message(

        self,

        event: AstrMessageEvent,

        info: NormalizedVideoInfo,

        info_text: str,

        source_url: str,

    ):

        proxy_enabled = should_apply_proxy(info.source_platform, source_url)



        # 按测试计划：文本 -> 图 -> 视频

        yield event.chain_result([Comp.Plain(info_text)])



        for image_url in info.images[: self.max_media]:

            final_image = apply_image_proxy(image_url, self.image_proxy_prefix, proxy_enabled)

            yield event.chain_result([Comp.Image.fromURL(final_image)])



        if info.video_url:

            video = apply_image_proxy(info.video_url, self.image_proxy_prefix, proxy_enabled)

            yield event.chain_result([Comp.Video.fromURL(video)])



        if self.send_live_photo_as_video:

            for live_photo in info.live_photos[: self.max_media]:

                live_video = apply_image_proxy(live_photo, self.image_proxy_prefix, proxy_enabled)

                yield event.chain_result([Comp.Video.fromURL(live_video)])



    def build_nodes_message(

        self,

        event: AstrMessageEvent,

        info: NormalizedVideoInfo,

        info_text: str,

        source_url: str,

    ) -> list:

        uin = event.get_self_id()

        bot_name = "链接解析"

        proxy_enabled = should_apply_proxy(info.source_platform, source_url)

        messages = []



        text_node_content = [Comp.Plain(info_text)]

        if self.show_author_avatar and info.author_avatar:

            avatar_url = apply_image_proxy(info.author_avatar, self.image_proxy_prefix, proxy_enabled)

            text_node_content.append(Comp.Image.fromURL(avatar_url))



        messages.append(

            Comp.Node(

                uin=uin,

                name=bot_name,

                content=text_node_content,

            )

        )



        for image_url in info.images[: self.max_media]:

            final_image = apply_image_proxy(image_url, self.image_proxy_prefix, proxy_enabled)

            messages.append(

                Comp.Node(

                    uin=uin,

                    name=bot_name,

                    content=[Comp.Image.fromURL(final_image)],

                )

            )



        if info.video_url:

            video = apply_image_proxy(info.video_url, self.image_proxy_prefix, proxy_enabled)

            messages.append(

                Comp.Node(

                    uin=uin,

                    name=bot_name,

                    content=[Comp.Video.fromURL(video)],

                )

            )



        if self.send_live_photo_as_video:

            for live_photo in info.live_photos[: self.max_media]:

                live_video = apply_image_proxy(live_photo, self.image_proxy_prefix, proxy_enabled)

                messages.append(

                    Comp.Node(

                        uin=uin,

                        name=bot_name,

                        content=[Comp.Video.fromURL(live_video)],

                    )

                )



        return [Comp.Nodes(messages)]



    async def fetch_parse_info_with_retry(self, session: ClientSession, url: str) -> dict | None:

        params = {"url": url}



        for attempt in range(MAX_RETRIES):

            try:

                async with session.get(

                    self.api_url,

                    params=params,

                    timeout=aiohttp.ClientTimeout(total=self.timeout),

                ) as response:

                    if response.status != 200:

                        logger.warning(

                            f"[VideoParse] Request attempt {attempt + 1} failed: HTTP {response.status}"

                        )

                    else:

                        data = await response.json(content_type=None)

                        if isinstance(data, dict):

                            return data

                        logger.warning(f"[VideoParse] Request attempt {attempt + 1} returned non-JSON object")

            except Exception as exc:

                logger.warning(f"[VideoParse] Request attempt {attempt + 1} exception: {exc}")



            if attempt < MAX_RETRIES - 1:

                await asyncio.sleep(RETRY_DELAY)



        return None



    async def terminate(self):

        if self._session and not self._session.closed:

            await self._session.close()

            self._session = None





