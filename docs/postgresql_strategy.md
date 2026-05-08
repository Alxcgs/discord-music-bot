# Стратегія переходу на PostgreSQL

## 1. Обґрунтування (Rationale)
На поточному етапі Discord Music Bot використовує **SQLite** через його простоту, відсутність необхідності в окремому сервері БД та WAL-режим, який забезпечує достатню продуктивність для одного інстансу бота.

Однак, для подальшого масштабування та реалізації Web Dashboard, перехід на **PostgreSQL** є доцільним з наступних причин:
*   **Паралельний доступ:** PostgreSQL набагато краще обробляє одночасні записи (concurrent writes), що важливо при великій кількості серверів.
*   **Зовнішні інструменти:** Легша інтеграція з BI-інструментами та веб-панелями керування, які можуть працювати з тією ж базою незалежно від бота.
*   **Типізація:** Більш строга типізація та підтримка складних індексів для аналітики.

## 2. Сумісність Схеми (Schema Mapping)
Схема в `database.py` спроектована максимально стандартно, що полегшує міграцію:
*   `INTEGER PRIMARY KEY` (SQLite) -> `SERIAL PRIMARY KEY` або `BIGINT` (PostgreSQL).
*   `DATETIME DEFAULT CURRENT_TIMESTAMP` -> `TIMESTAMP DEFAULT CURRENT_TIMESTAMP`.
*   `BOOLEAN` (INTEGER 0/1 в SQLite) -> `BOOLEAN` (Native в PG).
*   `JSON` (Text в SQLite) -> `JSONB` (PG).

## 3. План Міграції (Migration Path)

### Фаза 1: Абстракція (Поточний стан)
Завдяки використанню **Repository Pattern** (`MusicRepository`), бізнес-логіка бота не залежить від SQL-діалекту. Вся робота з БД зосереджена в одному класі.

### Фаза 2: Підтримка декількох драйверів
1.  Впровадження `DatabaseInterface` (абстрактний базовий клас).
2.  Створення `PostgresRepository`, який реалізує ті ж методи, що й `MusicRepository`, але через `asyncpg`.
3.  Вибір репозиторію через конфігурацію (`DB_TYPE=sqlite` або `DB_TYPE=postgres`).

### Фаза 3: Скрипт міграції даних
Розробка Python-скрипта, який:
1.  Читає всі дані з SQLite.
2.  Виконує масовий запис (bulk insert) у PostgreSQL.
3.  Перевіряє цілісність даних (row counts, foreign keys).

## 4. Конфігурація
Для PostgreSQL будуть додані наступні змінні оточення:
```env
DB_TYPE=postgres
POSTGRES_USER=bot_user
POSTGRES_PASSWORD=bot_password
POSTGRES_DB=music_bot
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
```

## 5. Ризики та обмеження
*   **Latency:** SQLite працює в пам'яті/локальному диску, PostgreSQL додає мережеву затримку. Потрібне використання Connection Pooling (`asyncpg.create_pool`).
*   **Deployment:** Потрібен додатковий контейнер у `docker-compose.yml`.
