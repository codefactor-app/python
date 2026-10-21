"""Standalone downloader used only when building the pip distribution."""
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import ssl
import tempfile
import urllib.error
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parent


def platform_id():
    system = {"Linux": "linux", "Darwin": "darwin", "Windows": "win32"}.get(platform.system())
    arch = {"x86_64": "x64", "amd64": "x64", "aarch64": "arm64", "arm64": "arm64"}.get(platform.machine().lower())
    if not system or not arch:
        raise RuntimeError("Unsupported Codefactor platform")
    return f"{system}-{arch}"


def binary_path():
    return ROOT / "bin" / ("codefactor.exe" if os.name == "nt" else "codefactor")


class ReleaseRedirect(urllib.request.HTTPRedirectHandler):
    max_redirections = 5

    def redirect_request(self, request, fp, code, msg, headers, newurl):
        if urllib.parse.urlparse(newurl).scheme != "https" or any(
            request.has_header(name) for name in ("Private-token", "Job-token")
        ):
            raise urllib.error.URLError("Unsafe Codefactor release redirect")
        return super().redirect_request(request, fp, code, msg, headers, newurl)


def download(url, limit):
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https":
        raise RuntimeError("Codefactor release URL must use HTTPS")
    ca = os.environ.get("CODEFACTOR_CA_BUNDLE")
    if not ca and parsed.hostname == "gitlab.local":
        ca = str(ROOT / "certs/gitlab.local.pem")
    context = ssl.create_default_context(cafile=ca)
    headers = {}
    if parsed.hostname != "github.com":
        if token := os.environ.get("CODEFACTOR_TOKEN"):
            headers["PRIVATE-TOKEN"] = token
        elif token := os.environ.get("CODEFACTOR_JOB_TOKEN") or os.environ.get("CI_JOB_TOKEN"):
            headers["JOB-TOKEN"] = token
    opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=context), ReleaseRedirect())
    try:
        with opener.open(urllib.request.Request(url, headers=headers), timeout=60) as response:
            data = response.read(limit + 1)
    except (urllib.error.URLError, TimeoutError) as error:
        raise RuntimeError("Cannot download Codefactor release; check token, TLS certificate and published platform") from error
    if len(data) > limit:
        raise RuntimeError("Codefactor download exceeded size limit")
    return data


def release_base(config, version):
    override = os.environ.get("CODEFACTOR_RELEASE_BASE_URL")
    if version == "latest" and not override:
        return config["latest_url"].rstrip("/")
    base = (override or config["base_url"]).rstrip("/")
    return base.replace("{version}", version) if "{version}" in base else base + "/" + version


def install(*, version=None, destination=None, manifest=None):
    config = json.loads((ROOT / "release.json").read_text())
    version = version if version is not None else os.environ.get('CODEFACTOR_CORE_VERSION', config['version'])
    destination = Path(destination) if destination is not None else binary_path()
    destination.parent.mkdir(parents=True, exist_ok=True)
    manifest_path = destination.parent / "codefactor.manifest.json"
    override = os.environ.get("CODEFACTOR_BINARY")
    if override:
        if Path(override).resolve() != destination:
            shutil.copy2(override, destination)
        destination.chmod(0o755)
        return destination
    if not isinstance(version, str) or not re.fullmatch(r'latest|[0-9]+\.[0-9]+\.[0-9]+', version):
        raise RuntimeError('core.version must be latest or X.Y.Z')
    platform = platform_id()
    if platform not in config["platforms"]:
        raise RuntimeError(f"No Codefactor release for {platform}")
    base = release_base(config, version)
    manifest = manifest if manifest is not None else json.loads(download(f"{base}/manifest-{platform}.json", 65536))
    filename = f"codefactor-{platform}" + (".exe" if os.name == "nt" else "")
    if not isinstance(manifest, dict):
        raise RuntimeError("Invalid Codefactor release manifest")
    requested = version
    version = manifest.get("version")
    checksum = manifest.get("sha256")
    if not isinstance(version, str) or not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", version) or (
        requested != "latest" and version != requested
    ) or manifest.get("platform") != platform or manifest.get("file") != filename or not isinstance(checksum, str) or not re.fullmatch(r"[a-f0-9]{64}", checksum):
        raise RuntimeError("Invalid Codefactor release manifest")
    if type(manifest.get("size")) is not int or not 0 < manifest["size"] <= 128 * 1024 * 1024:
        raise RuntimeError("Invalid Codefactor release manifest")
    if destination.is_file() and destination.stat().st_size == manifest.get("size") and hashlib.sha256(destination.read_bytes()).hexdigest() == manifest["sha256"]:
        destination.chmod(0o755)
        manifest_path.write_text(json.dumps(manifest))
        return destination
    binary = download(f"{release_base(config, version)}/{filename}", 128 * 1024 * 1024)
    if len(binary) != manifest.get("size") or hashlib.sha256(binary).hexdigest() != manifest.get("sha256"):
        raise RuntimeError("Codefactor binary checksum mismatch")
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=destination.parent, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(binary)
        temporary.chmod(0o755)
        os.replace(temporary, destination)
        manifest_path.write_text(json.dumps(manifest))
    finally:
        if temporary and temporary.exists():
            temporary.unlink()
    return destination
