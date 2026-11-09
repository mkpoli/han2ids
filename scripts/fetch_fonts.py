"""Fetch IPAmj Mincho and verify it.

IPAmj Ver.006.01 is served as a zip by the IPA/Moji Joho site's distributor. The font's MD5 is
checked against the value printed on <https://moji.or.jp/mojikiban/font/>.
"""
import hashlib
import urllib.request
import zipfile
from pathlib import Path

URL = "https://dforest.watch.impress.co.jp/library/i/ipamjfont/10750/ipamjm00601.zip"
JIGMO = "https://kamichikoichi.github.io/jigmo/Jigmo-20250912.zip"
JIGMO_SHA256 = "5744c7386d129475d87607ca66d043c8793c65448adeaedc921b6931890e5d0b"
MD5 = "beee256d4ffec4c40493805a4d7e5cdd"
CACHE = Path("cache/fonts")


def main():
    CACHE.mkdir(parents=True, exist_ok=True)
    archive = CACHE / "ipamjm00601.zip"
    if not archive.exists():
        urllib.request.urlretrieve(URL, archive)
    with zipfile.ZipFile(archive) as bundle:
        bundle.extractall(CACHE / "ipamj")
    digest = hashlib.md5((CACHE / "ipamj/ipamjm.ttf").read_bytes()).hexdigest()
    if digest != MD5:
        raise SystemExit(f"IPAmj checksum mismatch: {digest}")
    print(CACHE / "ipamj/ipamjm.ttf")
    jigmo_zip = CACHE / "Jigmo-20250912.zip"
    if not jigmo_zip.exists():
        urllib.request.urlretrieve(JIGMO, jigmo_zip)
    digest = hashlib.sha256(jigmo_zip.read_bytes()).hexdigest()
    if digest != JIGMO_SHA256:
        raise SystemExit(f"Jigmo checksum mismatch: {digest}")
    with zipfile.ZipFile(jigmo_zip) as bundle:
        bundle.extractall(CACHE / "jigmo")
    print(CACHE / "jigmo/Jigmo.ttf")


if __name__ == "__main__":
    main()
