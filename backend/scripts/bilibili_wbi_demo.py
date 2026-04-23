#!/usr/bin/env python3
"""Demo: fetch bilibili user videos via WBI signed API.

Usage:
  python3 backend/scripts/bilibili_wbi_demo.py 312017759 --limit 5

This avoids scraping https://space.bilibili.com (often blocked with 412).
"""

from __future__ import annotations

import argparse
import hashlib
import time
import urllib.parse

import requests


# The mixin key table used by bilibili WBI signing.
# Source: widely used community implementations.
MIXIN_KEY_ENC_TAB = [
    46, 47, 18, 2, 53, 8, 23, 32,
    15, 50, 10, 31, 58, 3, 45, 35,
    27, 43, 5, 49, 33, 9, 42, 19,
    29, 28, 14, 39, 12, 38, 41, 13,
    37, 48, 7, 16, 24, 55, 40, 61,
    26, 17, 0, 1, 60, 51, 30, 4,
    22, 25, 54, 21, 56, 59, 6, 63,
    57, 62, 11, 36, 20, 34, 44, 52,
]


def _md5_hex(s: str) -> str:
    return hashlib.md5(s.encode("utf-8")).hexdigest()


def _get_img_sub_keys(session: requests.Session) -> tuple[str, str]:
    """Fetch img_key and sub_key from /x/web-interface/nav."""
    r = session.get(
        "https://api.bilibili.com/x/web-interface/nav",
        timeout=10,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Referer": "https://www.bilibili.com/",
        },
    )
    r.raise_for_status()
    data = r.json()
    wbi_img = (data.get("data") or {}).get("wbi_img") or {}
    img_url = wbi_img.get("img_url", "")
    sub_url = wbi_img.get("sub_url", "")
    if not img_url or not sub_url:
        raise RuntimeError(f"wbi_img missing: {wbi_img}")
    img_key = img_url.rsplit("/", 1)[-1].split(".")[0]
    sub_key = sub_url.rsplit("/", 1)[-1].split(".")[0]
    return img_key, sub_key


def _mixin_key(img_key: str, sub_key: str) -> str:
    raw = img_key + sub_key
    mixed = "".join(raw[i] for i in MIXIN_KEY_ENC_TAB)
    return mixed[:32]


def _sign_params(params: dict[str, str], mixin_key: str) -> dict[str, str]:
    # Bilibili WBI requires filtering these characters from values.
    bad_chars = "!'()*"
    filtered = {
        k: "".join(ch for ch in str(v) if ch not in bad_chars)
        for k, v in params.items()
    }
    query = urllib.parse.urlencode(sorted(filtered.items()), quote_via=urllib.parse.quote)
    w_rid = _md5_hex(query + mixin_key)
    return {**filtered, "w_rid": w_rid}


def fetch_user_videos(mid: str, *, pn: int = 1, ps: int = 30, order: str = "pubdate") -> dict:
    session = requests.Session()

    img_key, sub_key = _get_img_sub_keys(session)
    mixin = _mixin_key(img_key, sub_key)

    wts = str(int(time.time()))
    base_params = {
        "mid": str(mid),
        "pn": str(pn),
        "ps": str(ps),
        "order": order,
        "platform": "web",
        "wts": wts,
    }
    signed = _sign_params(base_params, mixin)

    r = session.get(
        "https://api.bilibili.com/x/space/wbi/arc/search",
        params=signed,
        timeout=15,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Referer": "https://www.bilibili.com/",
        },
    )
    r.raise_for_status()
    return r.json()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("mid", help="Bilibili user UID")
    ap.add_argument("--limit", type=int, default=5)
    ap.add_argument("--page", type=int, default=1)
    ap.add_argument("--order", default="pubdate", choices=["pubdate", "click", "stow"])
    args = ap.parse_args()

    data = fetch_user_videos(args.mid, pn=args.page, ps=min(max(args.limit, 1), 50), order=args.order)
    code = data.get("code")
    if code != 0:
        raise SystemExit(f"API error: code={code} msg={data.get('message')}")

    vlist = (((data.get("data") or {}).get("list") or {}).get("vlist")) or []
    for i, v in enumerate(vlist[: args.limit], 1):
        bvid = v.get("bvid")
        title = v.get("title")
        url = f"https://www.bilibili.com/video/{bvid}/" if bvid else ""
        print(f"{i}. {title}\n   {url}")

    print(f"\nTotal returned on this page: {len(vlist)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
