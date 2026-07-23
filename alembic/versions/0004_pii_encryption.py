"""0004: PII-шифрование — message_text остаётся TEXT (SEC-FIX-5).

Шифрование реализовано прозрачно через SQLAlchemy TypeDecorator (utils.crypto.
EncryptedText): ORM пишет/читает обычные строки, в БД лежит Fernet-шифротекст
с префиксом "enc::v1::". Колонка message_text уже TEXT — на SQLite и PG
текст неограничен, отдельного ALTER не требуется.

Миграция — маркерная (no-op DDL): фиксирует точку включения шифрования в
истории схемы. Реальное перешифрование существующих plaintext-строк происходит:
  * лениво — при следующем сохранении/удалении лида (process_bind_param);
  * или разово — скриптом scripts/encrypt_existing.py.

Run:
    alembic upgrade head
"""

revision = "0004"
down_revision = "0003"


def upgrade() -> None:
    # message_text уже TEXT на обоих движках — шифротекст (Fernet token, base64)
    # помещается. DDL не требуется; миграция документирует включение шифрования.
    pass


def downgrade() -> None:
    # Обратной миграции нет: расшифровка — через удаление PII_ENCRYPTION_KEY
    # (код отдаёт plaintext для незашифрованных строк и помечает зашифрованные).
    pass
