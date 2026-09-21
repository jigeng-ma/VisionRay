"""Download a public Pgyer Android build and install it through ADB."""

from __future__ import annotations

import argparse
import re
import subprocess
import time
import zipfile
from pathlib import Path
from urllib.request import Request, urlopen

OVERSEAS_DOWNLOAD_PAGE = "https://www.pgyer.com/visionray-android-5"


def download(build_key: str, target: Path) -> Path:
    """Resume the public Pgyer APK download and reject incomplete archives."""
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and zipfile.is_zipfile(target):
        return target
    offset = target.stat().st_size if target.exists() else 0
    headers = {"User-Agent": "Mozilla/5.0"}
    if offset:
        headers["Range"] = f"bytes={offset}-"
    url = f"https://www.pgyer.com/app/install/{build_key}?time={int(time.time() * 1000)}&lang=cn"
    with urlopen(Request(url, headers=headers), timeout=120) as response:
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


def resolve_build(source: str, version: str | None, build: str | None) -> str:
    """Resolve a public Pgyer app page to its build key."""
    if re.fullmatch(r"[0-9a-f]{32}", source):
        return source
    with urlopen(Request(source, headers={"User-Agent": "Mozilla/5.0"}), timeout=30) as response:
        page = response.read().decode("utf-8", errors="ignore")
    keys = list(dict.fromkeys(re.findall(r"/app/build/([0-9a-f]{32})", page)))
    if not keys:
        raise RuntimeError("No Pgyer builds were found on the supplied download page.")
    if not version and not build:
        return keys[0]
    for key in keys:
        with urlopen(Request(f"https://www.pgyer.com/app/build/{key}", headers={"User-Agent": "Mozilla/5.0"}), timeout=30) as response:
            detail = response.read().decode("utf-8", errors="ignore")
        found_version = re.search(r"aVersion\s*=\s*['\"]([^'\"]+)", detail)
        found_build = re.search(r"(?:buildVersion|buildBuildVersion)\s*=\s*['\"]?(\d+)", detail)
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
    parser.add_argument("--output", type=Path, default=Path("work/downloads/VisionRay.apk"))
    args = parser.parse_args()
    build_key = resolve_build(args.source, args.version, args.build)
    apk = download(build_key, args.output)
    print(f"downloaded: {apk} ({apk.stat().st_size} bytes)")
    print(install(args.serial, apk))


if __name__ == "__main__":
    main()
