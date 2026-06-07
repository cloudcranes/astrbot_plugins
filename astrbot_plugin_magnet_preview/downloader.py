import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

import aiohttp
import hashlib
import re

LOW_VERSION_AUTH_SECRET = 'yrjmxtpovrzzdqgtbjdncmsywlpmyqcaawbnruddxucykfebpkuseypjegajzzpplmzrejnavcwtvciupgigyrtomdljhtmsljegvutunuizvatwtqdjheituaizfjyfzpbcvhhlaxzfatpgongrqadvixrnvastczwnolznfavqrvmjseiosmvrtcqiapmtzjfihdysqmhaijlpsrssovkpqnjbxuwkhjpfxpoldvqrnlhgdbcpnsilsmydxaxrxjzbdekzmshputmgkedetrcbmcdgljfkpbprvqncixfkavyxoibbuuyqzvcbzdgvipozeplohmcyfornhxzsadavvimivbzexfzhlndddnbywhsvjrotwzarbycpwydvpeqtuigfwzcvoswgpoakuvgdbykdjdcsdlnqskogpbsyceeyaigbgmrbnzixethpvqvvfvdcvjbilxikvklfbkcnfprzhijjnuoovulvigiqvbosnbixeplvnewmyipxuzpvocbvidnzgsrdfkejghvvyizkjlofndcuzvlhdhovpeolsyroljurbplpwbbihmdloahicnqehgjnbthmrljtzovltnlpeibodpjvemhhybmanskbtvdrgkrzoyhsjcexfrcpddoemazkfjwmrbrcloitmdzzkgxwlhnbfpjffrpryljdzdqsbacrjgohzwgbvzgevnqvxppsxqzczfgpuvigjbuhzweyeinukeurkogpotdegqhtsztdinmijjowivciviunhcjhtufzhjlmpqlngslimksdeezdzxihtmaywfvipjctuealhlovmzdodruperyysdhwjbtidwdzusifeepywsmkqbknlgdhextvlheufxivphskqvdtbcjfryxlolujmennakdqjdhtcxwnhknhzlaatuhyofenhdigojyxrluijjxeywnmopsuicglfcqyybbpynpcsnizupumtakwwnjlkfkuooqoqxhjnryylklokmzvmmgjsbbvgmwoucpvzedmqpkmazwhhvxqygrexopkmcdyniqocguykphlngjesqohhuvnkcliuawkzcmvevdbouwzvgmhtavwyhstvqwhcwjluzjopnhuisbsrloavcieskcyqftdhieduduhowgvrkimgdhyszsiknmuzvnrqqlbykbdlixosgxrdunymbixakkmgppteayqmqivxcwawyidpltevotwoxlkrucmluuluatgeskhfsrsebhniwhujpwrpknjxylidtjwebvwmbwayoepootybnlcaoixlgvjmpquxnyomoiopsjxtnorhwnlmonllastiezyvfbbgngjybtgbkxuaqdmkuqwupgzhffuyzgdnahdifaqtfmpysnlesvfoiofxvbtqkiqvdniejbyzugbkursumqddaslhqpkdrjnnsdqfthxtghxhaylgeqnknhqwpammlfnlkjuqevnxesyqsnpufvrbeohphxfabcduuklpkfoiifsqrrbsxkkmdrnkeboprnksfzwmjymjspzsrfjlwneuwzjjwejruubhhqaktxhygtjuhjmtvrklrmxdbbwooxsucmynwgcxhzdctgtchaevmpfiqfwydultmgqnionuendspvdrcctxldnyjlgnsqxaddadxeyvlcifdxksgdhaatsslhcofnxmilljpzdlumfjvcwvjrxegwbwuuwkguydhozqqnuselsoojnsefquuhpijdguofwrcjbuaugyzphkenbyhdstsldybdqsfxjhpgnerbdosbtyzdtrhyvwkzkurnmbgjtzlzcpfsuxussguelnjttmwejhreptwogekfvdsemlkvklcxeuzlboqwbngddexhsmyzqkztvlbgybbfmzbjroajaucykiqvhjrirlgawaessusvulngosviecmbpfgevxqptalguchfzkrrpruwxspggiqokepqpocezcewhyajsgxrqqqeuhwvc'
VIDEO_EXTENSIONS = {'.mp4', '.mkv', '.avi', '.mov', '.wmv', '.flv', '.webm', '.m4v', '.ts', '.m2ts', '.rmvb', '.mpg', '.mpeg'}
MIN_VIDEO_SIZE = 50 * 1024 * 1024


class DownloadError(Exception):
    pass


@dataclass(slots=True)
class DownloadResult:
    downloader: str
    task_id: str
    name: str = ""
    save_path: str = ""
    message: str = ""


def parse_info_hash(magnet: str) -> str:
    marker = "xt=urn:btih:"
    lower = magnet.lower()
    index = lower.find(marker)
    if index < 0:
        return ""
    start = index + len(marker)
    end = magnet.find("&", start)
    return magnet[start:] if end < 0 else magnet[start:end]


class BaseDownloader:
    name = "base"

    def is_enabled(self) -> bool:
        return False

    async def add(self, magnet: str, display_name: str = "") -> DownloadResult:
        raise NotImplementedError

class XunleiDownloader(BaseDownloader):
    name = "xunlei"

    def __init__(
        self,
        session: aiohttp.ClientSession,
        host: str = "",
        port: str = "",
        ssl: bool = False,
        platform: str = "docker",
    ) -> None:
        self.session = session
        self.host = host.strip().rstrip("/")
        self.port = str(port).strip()
        self.ssl = ssl
        self.platform = platform.strip().lower()
        self._pan_auth: str | None = None
        self._device_id: str | None = None
        self._req_count = 0

    @property
    def _base_url(self) -> str:
        proto = "https" if self.ssl else "http"
        return f"{proto}://{self.host}:{self.port}"

    @property
    def _prefix(self) -> str:
        if self.platform == "fnos":
            return "/cgi/ThirdParty/xunlei/index.cgi"
        return "/webman/3rdparty/pan-xunlei-com/index.cgi"

    def is_enabled(self) -> bool:
        return bool(self.host) and bool(self.port)

    @staticmethod
    def _is_version_at_least(v: str, target: str) -> bool:
        parts = v.split(".")
        tgts = target.split(".")
        for a, b in zip(parts, tgts):
            try:
                if int(a) > int(b):
                    return True
                if int(a) < int(b):
                    return False
            except ValueError:
                pass
        return len(parts) >= len(tgts)

    async def _discover_token(self) -> str:
        # Try high-version path first
        try:
            async with self.session.get(
                f"{self._base_url}{self._prefix}/launcher/status",
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status == 200:
                    data = await resp.json(content_type=None)
                    server_version = (data.get("running_version") or data.get("version") or "").strip()
                    if server_version and self._is_version_at_least(server_version, "3.21.0"):
                        token = await self._token_high_version()
                        if token:
                            return token
        except Exception:
            pass
        # Fallback: low-version token from root page HTML
        return await self._token_low_version()

    async def _token_high_version(self) -> str | None:
        try:
            async with self.session.get(
                f"{self._base_url}{self._prefix}/",
                timeout=aiohttp.ClientTimeout(total=15),
                ssl=False,
            ) as resp:
                if resp.status >= 400:
                    return None
                html = await resp.text()
        except Exception:
            return None
        match = re.search(r'function\s+uiauth\(value\)\s*\{\s*return\s*["\']([^"\']+)["\']\s*\}', html)
        if match:
            return match.group(1)
        return None

    async def _token_low_version(self) -> str:
        timestamp = int(time.time())
        digest = hashlib.md5(f"{timestamp}{LOW_VERSION_AUTH_SECRET}".encode()).hexdigest()
        return f"{timestamp}.{digest}"

    async def _ensure_auth(self) -> str:
        if self._pan_auth and self._req_count < 50:
            return self._pan_auth
        self._pan_auth = await self._discover_token()
        self._req_count = 0
        if not self._pan_auth:
            raise DownloadError("xunlei: failed to acquire pan-auth token")
        return self._pan_auth

    async def _do_request(self, method: str, path: str, body=None) -> any:
        pan_auth = await self._ensure_auth()
        url = f"{self._base_url}{self._prefix}{path}"
        headers = {
            "pan-auth": pan_auth,
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "application/json",
            "device-space": "",
        }
        kwargs = {
            "headers": headers,
            "timeout": aiohttp.ClientTimeout(total=30),
            "ssl": False,
        }
        if body is not None:
            kwargs["json"] = body
        async with self.session.request(method, url, **kwargs) as resp:
            self._req_count += 1
            if resp.status == 401:
                self._pan_auth = None
                text = await resp.text()
                raise DownloadError(f"xunlei auth expired (401): {text[:100]}")
            if resp.status >= 400:
                text = await resp.text()
                raise DownloadError(f"xunlei API {method} {path}: HTTP {resp.status} {text[:200]}")
            try:
                return await resp.json(content_type=None)
            except Exception as exc:
                raise DownloadError(f"xunlei API response not JSON: {exc}") from exc

    async def _get_device_id(self) -> str:
        if self._device_id:
            return self._device_id
        data = await self._do_request(
            "GET", "/drive/v1/tasks?type=user%23runner&device_space="
        )
        tasks = data.get("tasks") or []
        if not tasks:
            raise DownloadError("xunlei: no remote device bound")
        target = tasks[0].get("params", {}).get("target", "")
        if not target:
            raise DownloadError("xunlei: device has no target param")
        self._device_id = target
        return self._device_id

    async def _get_parent_folder_id(self, device_id: str) -> str:
        qs = urlencode({
            "space": device_id,
            "limit": "200",
            "parent_id": "",
            "filters": '{"kind":{"eq":"drive#folder"}}',
            "page_token": "",
            "device_space": "",
        })
        data = await self._do_request("GET", f"/drive/v1/files?{qs}")
        files = data.get("files") or []
        if files and "parent_id" in files[0]:
            return files[0]["parent_id"] or ""
        return ""

    async def _extract_files(self, magnet: str) -> list[dict[str, Any]]:
        data = await self._do_request("POST", "/drive/v1/resource/list?device_space=", {"urls": magnet})
        resources = data.get("list", {}).get("resources", [])
        files: list[dict[str, Any]] = []

        def walk(items: list[dict[str, Any]]) -> None:
            for item in items:
                if item.get("is_dir"):
                    walk(item.get("dir", {}).get("resources", []) or [])
                    continue
                file_name = item.get("name") or "download"
                file_size = int(item.get("file_size") or 0)
                suffix = file_name.lower().rsplit(".", 1)[-1]
                if f".{suffix}" not in VIDEO_EXTENSIONS or file_size <= MIN_VIDEO_SIZE:
                    continue
                files.append({
                    "file_name": file_name,
                    "file_size": file_size,
                    "index": int(item.get("file_index") or 0),
                })

        walk(resources)
        return files

    async def add(self, magnet: str, display_name: str = "") -> DownloadResult:
        device_id = await self._get_device_id()
        parent_id = await self._get_parent_folder_id(device_id)
        files = await self._extract_files(magnet)
        if not files:
            raise DownloadError("xunlei: no video files larger than 50MB")
        task_name = display_name or files[0]["file_name"] or "下载任务"
        body = {
            "type": "user#download-url",
            "name": task_name,
            "file_name": task_name,
            "file_size": str(sum(file["file_size"] for file in files)),
            "space": device_id,
            "params": {
                "target": device_id,
                "url": magnet,
                "app_name": "Xunlei",
                "total_file_count": str(len(files)),
                "parent_folder_id": parent_id,
                "sub_file_index": ",".join(str(file["index"]) for file in files),
                "file_id": "",
            },
        }
        result = await self._do_request("POST", "/drive/v1/task?device_space=", body=body)
        task_id = str(result.get("task_id") or result.get("id") or parse_info_hash(magnet))
        return DownloadResult(self.name, task_id, task_name, "", "已加入迅雷下载")


