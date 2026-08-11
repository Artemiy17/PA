# PA — Todoist starter

Минимальный старт проекта с интеграцией Todoist.

## 1. Установка

```bash
python -m venv .venv
```

Активируй окружение и установи зависимости:

```bash
pip install -r requirements.txt
```

## 2. Todoist API token

Скопируй `.env.example` в `.env`:

```bash
cp .env.example .env
```

Затем вставь персональный Todoist API token:

```env
TODOIST_API_TOKEN=YOUR_TOKEN
```

Токен находится в Todoist: Settings → Integrations → Developer → API token.

## 3. Проверка синхронизации

```bash
python -m integrations.todoist.sync
```

После успешного запроса появится:

```text
data/todoist/tasks.json
```

## Текущая логика

- `client.py` отвечает только за запросы к Todoist API.
- `sync.py` получает все активные задачи и сохраняет локальный snapshot.
- `AGENTS.md` говорит агенту запускать синхронизацию только когда нужны актуальные Todoist-задачи и ждать завершения команды.
- `.env` не коммитится в Git.
