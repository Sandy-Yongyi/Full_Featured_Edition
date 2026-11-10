"""Build private modules: python -m model.build_extensions build_ext --inplace."""

from pathlib import Path

from setuptools import Extension, find_packages, setup

from model.runtime.app_bootstrap import prepare_environment


PRIVATE_PACKAGES = ("lidar", "plc", "dataprocess", "formats", "pointcloud")


def get_extensions() -> list[Extension]:
    root = Path(__file__).resolve().parents[1]
    extensions = []
    for package in PRIVATE_PACKAGES:
        for source in sorted((root / "model" / package).rglob("*.py")):
            if source.name == "__init__.py":
                continue
            relative = source.relative_to(root)
            extensions.append(Extension(".".join(relative.with_suffix("").parts), [relative.as_posix()]))
    return extensions


def main() -> None:
    from Cython.Build import cythonize
    prepare_environment()
    setup(name="Package", version="0.1", packages=find_packages(), ext_modules=cythonize(get_extensions(), language_level=3), zip_safe=False)


if __name__ == "__main__":
    main()
