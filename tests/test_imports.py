import importlib
import importlib.util
import sys
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover
    tomllib = None


def test_imports():
    import weavehr_yaib

    assert hasattr(weavehr_yaib, "build_mortality_dynamic_wide_from_config")


def test_public_api_is_importable():
    import weavehr_yaib

    for name in weavehr_yaib.__all__:
        assert hasattr(weavehr_yaib, name), name


def test_package_is_loaded_from_weavehr_yaib_source():
    spec = importlib.util.find_spec("weavehr_yaib")
    assert spec is not None and spec.origin is not None
    src = Path(__file__).resolve().parents[1] / "src"
    assert Path(spec.origin).resolve() == src / "weavehr_yaib" / "__init__.py"
    assert not (src / "openicu_yaib").exists()


def test_cli_entry_points_target_weavehr_yaib():
    if tomllib is None:
        return
    pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
    scripts = tomllib.loads(pyproject.read_text())["project"]["scripts"]

    assert scripts == {
        "weavehr-yaib": "weavehr_yaib.cli:main",
        "weavehr-yaib-dyn": "weavehr_yaib.cli:main",
    }
    module, func = scripts["weavehr-yaib"].split(":")
    assert callable(getattr(importlib.import_module(module), func))


def test_mimic_iii_is_marked_as_not_bundled_with_weavehr():
    from weavehr_yaib import dataset_spec

    assert not dataset_spec("mimic-iii").weavehr_bundled
    assert not dataset_spec("mimic-iii-demo").weavehr_bundled
    assert dataset_spec("aumc").weavehr_bundled
