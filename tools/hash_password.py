"""Создаёт Argon2id-хеш пароля без сохранения открытого значения."""
from getpass import getpass

from amnezia_panel.security import AuthService


def main() -> None:
    """▶ hidden prompt ×2 → policy/compare → Argon2id hash."""
    first = getpass("Новый пароль (минимум 12 символов): ")
    second = getpass("Повторите пароль: ")
    if first != second:
        raise SystemExit("Пароли не совпадают")
    print(AuthService.hash_password(first))


if __name__ == "__main__":
    main()
