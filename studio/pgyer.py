"""Download a public Pgyer Android build and install it through ADB."""

from __future__ import annotations

import argparse
import subprocess
import time
import zipfile
from pathlib import Path
from urllib.request import Request, urlopen


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


def install(serial: str, apk: Path) -> str:
    result = subprocess.run(["adb", "-s", serial, "install", "-r", str(apk)], text=True, capture_output=True, check=False)
    if result.returncode or "Success" not in result.stdout:
        raise RuntimeError(result.stdout + result.stderr)
    return result.stdout.strip()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("build_key", help="Pgyer build key, from the selected version URL")
    parser.add_argument("--serial", required=True, help="ADB device serial")
    parser.add_argument("--output", type=Path, default=Path("work/downloads/VisionRay.apk"))
    args = parser.parse_args()
    apk = download(args.build_key, args.output)
    print(f"downloaded: {apk} ({apk.stat().st_size} bytes)")
    print(install(args.serial, apk))


if __name__ == "__main__":
    main()
