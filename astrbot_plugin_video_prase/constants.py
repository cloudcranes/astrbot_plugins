import re

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
}

MAX_RETRIES = 3
RETRY_DELAY = 1

SUPPORTED_DOMAINS = (
    "douyin.com",
    "iesdouyin.com",
    "x.com",
    "twitter.com",
    "t.co",
    "bilibili.com",
    "b23.tv",
    "youtube.com",
    "youtu.be",
    "xiaohongshu.com",
    "xhslink.com",
    "kuaishou.com",
    "gifshow.com",
    "pipix.com",
    "pipigx.com",
    "weibo.com",
    "weibo.cn",
    "h5.weibo.cn",
    "weishi.qq.com",
    "ixigua.com",
    "huya.com",
)

URL_PATTERN = re.compile(r"https?://[^\s'\"<>]+", re.IGNORECASE)
