"""Проверяет версии runtime-зависимостей без запуска панели."""
from importlib import import_module
from importlib.metadata import PackageNotFoundError, version

PACKAGES = ("flask", "argon2-cffi", "qrcode", "gunicorn", "pytest")


def check_dependencies() -> dict[str, str]:
    """▶ packages → metadata lookup → status map."""
    result: dict[str, str] = {}
    for package in PACKAGES:
        try:
            result[package] = version(package)
        except PackageNotFoundError:
            result[package] = "MISSING"
    return result


if __name__ == "__main__":
    for name, installed_version in check_dependencies().items():
        print(f"{name}: {installed_version}")
