"""PEP 517 backend: a source install fetches core, wheels already contain it."""
import importlib.util
from pathlib import Path
from setuptools import build_meta as _backend

get_requires_for_build_wheel = _backend.get_requires_for_build_wheel
get_requires_for_build_sdist = _backend.get_requires_for_build_sdist
prepare_metadata_for_build_wheel = _backend.prepare_metadata_for_build_wheel
build_sdist = _backend.build_sdist


def build_wheel(wheel_directory, config_settings=None, metadata_directory=None):
    path = Path(__file__).parent / "src/codefactor/_installer.py"
    spec = importlib.util.spec_from_file_location("_codefactor_installer", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.install()
    return _backend.build_wheel(wheel_directory, config_settings, metadata_directory)
