"""Download a public Pgyer Android build and install it through ADB."""

from __future__ import annotations

import argparse
from http.cookiejar import CookieJar
import re
import subprocess
import time
import zipfile
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import HTTPCookieProcessor, Request, build_opener

OVERSEAS_DOWNLOAD_PAGE = "https://www.pgyer.com/visionray-android-5"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/140 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}
OPENER = build_opener(HTTPCookieProcessor(CookieJar()))


def fetch(url, headers=None):
    """Fetch Pgyer content with browser headers and one retry for a transient 403."""
    merged = dict(HEADERS)
    merged.update(headers or {})
    for attempt in range(2):
        try:
            return OPENER.open(Request(url, headers=merged), timeout=120)
        except HTTPError as exc:
            if exc.code != 403 or attempt:
                raise RuntimeError(f'蒲公英请求失败（HTTP {exc.code}）：{url}') from exc
            time.sleep(1)


def install_url(build_key: str) -> str:
    """Create the short-lived Pgyer install URL required by historical builds."""
    with fetch(f"https://www.pgyer.com/{build_key}") as response:
        page = response.read().decode("utf-8", errors="ignore")

    def variable(name):
        match = re.search(rf"\b{name}\s*=\s*['\"]([^'\"]+)", page)
        return match.group(1) if match else ''

    params = [f"time={int(time.time() * 1000)}", "lang=cn"]
    for name in ("finalCode", "timeSign", "installToken"):
        if value := variable(name):
            params.append(f"{name}={value}")
    return f"https://www.pgyer.com/app/install/{variable('aKey') or build_key}?{'&'.join(params)}"


def download(build_key: str, target: Path) -> Path:
    """Resume the public Pgyer APK download and reject incomplete archives."""
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and zipfile.is_zipfile(target):
        return target
    offset = target.stat().st_size if target.exists() else 0
    headers = {}
    if offset:
        headers["Range"] = f"bytes={offset}-"
    url = install_url(build_key)
    with fetch(url, headers) as response:
        append = offset and response.status == 206
        with target.open("ab" if append else "wb") as output:
            while chunk := response.read(1024 * 1024):
                output.write(chunk)
    if not zipfile.is_zipfile(target):
        raise RuntimeError("APK download is incomplete; run the command again to resume it.")
    with zipfile.ZipFile(target) as archive:
        if archive.testzip():
            raise RuntimeError("APK archive integrity check failed.")
    return target


def resolve_build(source: str, version: str | None, build: str | None, variant: str | None = None) -> str:
    """Resolve a public Pgyer app page to its build key."""
    if re.fullmatch(r"[0-9a-f]{32}", source):
        return source
    with fetch(source) as response:
        page = response.read().decode("utf-8", errors="ignore")
    keys = list(dict.fromkeys(re.findall(r"(?:/app/build/|data-url=[\"']/)([0-9a-f]{32})", page)))
    if not keys:
        raise RuntimeError("No Pgyer builds were found on the supplied download page.")
    if not version and not build and not variant:
        return keys[0]
    checked = set()
    while keys:
        key = keys.pop(0)
        if key in checked:
            continue
        checked.add(key)
        with fetch(f"https://www.pgyer.com/app/build/{key}") as response:
            detail = response.read().decode("utf-8", errors="ignore")
        # 公开下载页只含当前构建；构建详情页再列出历史 release/debug 版本。
        keys.extend(k for k in re.findall(r"(?:/app/build/|data-url=[\"']/)([0-9a-f]{32})", detail) if k not in checked)
        found_version = re.search(r"aVersion\s*=\s*['\"]([^'\"]+)", detail)
        if not found_version:
            with fetch(f"https://www.pgyer.com/{key}") as response:
                detail = response.read().decode("utf-8", errors="ignore")
            found_version = re.search(r"aVersion\s*=\s*['\"]([^'\"]+)", detail)
        found_build = re.search(r"(?:buildVersion|buildBuildVersion)\s*=\s*['\"]?(\d+)", detail)
        is_debug = bool(found_version and found_version.group(1).endswith('-debug'))
        if variant == 'debug' and not is_debug:
            continue
        if variant == 'release' and is_debug:
            continue
        if version and (not found_version or found_version.group(1) != version):
            continue
        if build and (not found_build or found_build.group(1) != build):
            continue
        return key
    raise RuntimeError("No Pgyer build matched the supplied version/build value.")


def install(serial: str, apk: Path) -> str:
    result = subprocess.run(["adb", "-s", serial, "install", "-r", str(apk)], text=True, capture_output=True, check=False)
    if result.returncode or "Success" not in result.stdout:
        raise RuntimeError(result.stdout + result.stderr)
    return result.stdout.strip()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", help="Pgyer download-page URL, or a direct Pgyer build key")
    parser.add_argument("--serial", required=True, help="ADB device serial")
    parser.add_argument("--version", help="Exact version, e.g. 1.2.39-Occident-debug")
    parser.add_argument("--build", help="Pgyer build number, e.g. 121")
    parser.add_argument("--variant", choices=("debug", "release"), help="Choose a build variant when version is omitted")
    parser.add_argument("--output", type=Path, default=Path("work/downloads/VisionRay.apk"))
    args = parser.parse_args()
    build_key = resolve_build(args.source, args.version, args.build, args.variant)
    apk = download(build_key, args.output)
    print(f"downloaded: {apk} ({apk.stat().st_size} bytes)")
    print(install(args.serial, apk))


if __name__ == "__main__":
    main()
