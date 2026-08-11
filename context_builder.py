from __future__ import annotations

import argparse
import copy
import json
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

try:
    import yaml
except ModuleNotFoundError as exc:
    raise SystemExit(
        "Не найден PyYAML. Установите зависимость:\n"
        "python -m pip install -r requirements-memory.txt"
    ) from exc


PROJECT_ROOT = Path(__file__).resolve().parent
CONFIG_PATH = PROJECT_ROOT / "config" / "memory.yaml"

CORE_KEYS = {
    "areas.yaml": "areas",
    "goals.yaml": "goals",
    "projects.yaml": "projects",
    "obligations.yaml": "obligations",
    "routines.yaml": "routines",
    "facts.yaml": "facts",
    "priorities.yaml": "priorities",
}

PLACEHOLDER_PATTERN = re.compile(r"<<УТОЧНИТЬ:\s*.+?>>")
HISTORY_FILE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}\.md$")


class ContextBuildError(RuntimeError):
    """Ошибка, при которой рабочий контекст нельзя считать надёжным."""


class StringSafeLoader(yaml.SafeLoader):
    """SafeLoader, который оставляет ISO-даты строками."""


# PyYAML по умолчанию преобразует YYYY-MM-DD в datetime.date.
# Для переносимого JSON-подобного контекста даты удобнее хранить строками.
for first_char, resolvers in list(StringSafeLoader.yaml_implicit_resolvers.items()):
    StringSafeLoader.yaml_implicit_resolvers[first_char] = [
        (tag, regex)
        for tag, regex in resolvers
        if tag != "tag:yaml.org,2002:timestamp"
    ]


def _resolve(path_value: str) -> Path:
    return PROJECT_ROOT / path_value


def _read_text(path: Path, *, required: bool = True) -> str | None:
    if not path.exists():
        if required:
            raise ContextBuildError(f"Не найден обязательный файл: {path}")
        return None

    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ContextBuildError(f"Не удалось прочитать файл: {path}: {exc}") from exc


def _read_yaml(path: Path, *, required: bool = True) -> dict[str, Any]:
    text = _read_text(path, required=required)
    if text is None:
        return {}

    try:
        data = yaml.load(text, Loader=StringSafeLoader)
    except yaml.YAMLError as exc:
        raise ContextBuildError(f"Некорректный YAML: {path}: {exc}") from exc

    if data is None:
        return {}

    if not isinstance(data, dict):
        raise ContextBuildError(
            f"Ожидался YAML-объект верхнего уровня в файле: {path}"
        )

    return data


def _read_json(path: Path, *, required: bool = True) -> dict[str, Any]:
    text = _read_text(path, required=required)
    if text is None:
        return {}

    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ContextBuildError(f"Некорректный JSON: {path}: {exc}") from exc

    if not isinstance(data, dict):
        raise ContextBuildError(
            f"Ожидался JSON-объект верхнего уровня в файле: {path}"
        )

    return data


def _items(data: dict[str, Any], path: Path) -> list[dict[str, Any]]:
    items = data.get("items", [])
    if not isinstance(items, list):
        raise ContextBuildError(f"Поле items должно быть списком: {path}")

    result: list[dict[str, Any]] = []
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            raise ContextBuildError(
                f"Элемент items[{index}] должен быть объектом: {path}"
            )
        result.append(item)

    return result


def load_config() -> dict[str, Any]:
    config = _read_yaml(CONFIG_PATH)

    if not isinstance(config.get("recent_history_days"), int):
        raise ContextBuildError(
            "config/memory.yaml: recent_history_days должен быть целым числом"
        )

    if config["recent_history_days"] < 0:
        raise ContextBuildError(
            "config/memory.yaml: recent_history_days не может быть отрицательным"
        )

    return config


def load_core_memory(config: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    core_dir = _resolve(config["paths"]["core"])
    required_files = config["core"]["required_files"]

    result: dict[str, list[dict[str, Any]]] = {}

    for filename in required_files:
        if filename not in CORE_KEYS:
            raise ContextBuildError(
                f"Неизвестный обязательный core-файл в конфигурации: {filename}"
            )

        path = core_dir / filename
        result[CORE_KEYS[filename]] = _items(_read_yaml(path), path)

    return result


def load_recent_history(
    config: dict[str, Any],
    *,
    today: date | None = None,
) -> list[dict[str, str]]:
    history_dir = _resolve(config["paths"]["history"])
    days = config["recent_history_days"]

    if not history_dir.exists() or days == 0:
        return []

    tz = ZoneInfo(config["timezone"])
    current_day = today or datetime.now(tz).date()
    earliest_day = current_day - timedelta(days=max(days - 1, 0))

    records: list[dict[str, str]] = []

    for path in history_dir.rglob("*.md"):
        if not HISTORY_FILE_PATTERN.match(path.name):
            continue

        try:
            file_day = date.fromisoformat(path.stem)
        except ValueError:
            continue

        if not (earliest_day <= file_day <= current_day):
            continue

        text = _read_text(path, required=False)
        if text is None:
            continue

        records.append(
            {
                "date": file_day.isoformat(),
                "path": str(path.relative_to(PROJECT_ROOT)),
                "content": text,
            }
        )

    records.sort(key=lambda item: item["date"])
    return records


def load_analytics(config: dict[str, Any]) -> list[dict[str, Any]]:
    path = _resolve(config["paths"]["analytics"])
    data = _read_yaml(path, required=False)
    items = _items(data, path) if data else []

    excluded = {"archived", "rejected", "resolved", "inactive"}
    return [
        item
        for item in items
        if str(item.get("status", "hypothesis")).lower() not in excluded
    ]


def load_pending_changes(config: dict[str, Any]) -> list[dict[str, Any]]:
    path = _resolve(config["paths"]["pending"])
    data = _read_yaml(path, required=False)
    items = _items(data, path) if data else []

    return [
        item
        for item in items
        if str(item.get("status", "pending")).lower() == "pending"
    ]


def load_placeholders(config: dict[str, Any]) -> list[dict[str, Any]]:
    path = _resolve(config["paths"]["placeholders"])
    data = _read_yaml(path, required=False)
    return _items(data, path) if data else []


def load_todoist_links(config: dict[str, Any]) -> dict[str, Any]:
    path = _resolve(config["paths"]["todoist_links"])
    return _read_yaml(path, required=False)


def load_todoist_context(
    config: dict[str, Any],
    *,
    status: str,
) -> dict[str, Any]:
    if status not in {"fresh", "stale", "unavailable"}:
        raise ContextBuildError(
            "Todoist status должен быть fresh, stale или unavailable"
        )

    snapshot_path = _resolve(config["todoist"]["snapshot_path"])
    diff_path = _resolve(config["todoist"]["diff_path"])

    snapshot = _read_json(snapshot_path, required=False)
    diff = _read_json(diff_path, required=False)

    if status == "fresh" and not snapshot:
        raise ContextBuildError(
            "Todoist помечен как fresh, но текущий tasks.json отсутствует "
            "или не может быть прочитан"
        )

    if not snapshot:
        return {
            "status": "unavailable",
            "last_successful_sync": None,
            "warning": "Доступного снимка Todoist нет.",
            "snapshot": None,
            "diff": None,
        }

    effective_status = status
    warning = None

    if effective_status == "unavailable":
        # Если API недоступен, но старый снимок существует, это stale-data mode.
        effective_status = "stale"

    if effective_status == "stale":
        warning = (
            "Не удалось подтвердить свежесть Todoist. "
            "Используется последний сохранённый снимок; он может быть неактуальным."
        )

    return {
        "status": effective_status,
        "last_successful_sync": snapshot.get("synced_at"),
        "warning": warning,
        "snapshot": snapshot,
        "diff": diff or None,
    }


def _validate_unique_ids(
    items: list[dict[str, Any]],
    *,
    section: str,
    errors: list[str],
) -> set[str]:
    seen: set[str] = set()

    for index, item in enumerate(items):
        item_id = item.get("id")
        if item_id is None or str(item_id).strip() == "":
            errors.append(f"{section}[{index}]: отсутствует обязательный id")
            continue

        item_id = str(item_id)
        if item_id in seen:
            errors.append(f"{section}: повторяющийся id: {item_id}")
        seen.add(item_id)

    return seen


def validate_context(context: dict[str, Any]) -> dict[str, list[str]]:
    errors: list[str] = []
    warnings: list[str] = []

    core = context["core"]

    ids: dict[str, set[str]] = {}
    for section, items in core.items():
        ids[section] = _validate_unique_ids(
            items,
            section=f"core.{section}",
            errors=errors,
        )

    area_ids = ids["areas"]
    goal_ids = ids["goals"]
    project_ids = ids["projects"]

    for goal in core["goals"]:
        area_id = goal.get("area_id")
        if area_id and str(area_id) not in area_ids:
            errors.append(
                f"Цель {goal.get('id')}: неизвестный area_id={area_id}"
            )

    for project in core["projects"]:
        area_id = project.get("area_id")
        if area_id and str(area_id) not in area_ids:
            errors.append(
                f"Проект {project.get('id')}: неизвестный area_id={area_id}"
            )

        goal_refs = project.get("goal_ids", [])
        if goal_refs is None:
            goal_refs = []
        if not isinstance(goal_refs, list):
            errors.append(
                f"Проект {project.get('id')}: goal_ids должен быть списком"
            )
        else:
            for goal_id in goal_refs:
                if str(goal_id) not in goal_ids:
                    errors.append(
                        f"Проект {project.get('id')}: неизвестный goal_id={goal_id}"
                    )

    for priority in core["priorities"]:
        scope = priority.get("scope")
        target_id = priority.get("target_id")
        if not target_id:
            continue
        if scope == "project" and str(target_id) not in project_ids:
            errors.append(
                f"Приоритет {priority.get('id')}: неизвестный project target_id={target_id}"
            )
        if scope == "goal" and str(target_id) not in goal_ids:
            errors.append(
                f"Приоритет {priority.get('id')}: неизвестный goal target_id={target_id}"
            )
        if scope == "area" and str(target_id) not in area_ids:
            errors.append(
                f"Приоритет {priority.get('id')}: неизвестный area target_id={target_id}"
            )

    todoist = context["todoist"]
    snapshot = todoist.get("snapshot")

    if snapshot:
        tasks = snapshot.get("tasks", [])
        if not isinstance(tasks, list):
            errors.append("Todoist snapshot: tasks должен быть списком")
        else:
            task_ids: set[str] = set()
            for index, task in enumerate(tasks):
                if not isinstance(task, dict):
                    errors.append(f"Todoist tasks[{index}] должен быть объектом")
                    continue
                task_id = task.get("id")
                if task_id is None:
                    errors.append(f"Todoist tasks[{index}]: отсутствует id")
                    continue
                task_id = str(task_id)
                if task_id in task_ids:
                    errors.append(f"Todoist snapshot: повторяющийся task id={task_id}")
                task_ids.add(task_id)

            declared_count = snapshot.get("task_count")
            if isinstance(declared_count, int) and declared_count != len(tasks):
                warnings.append(
                    "Todoist snapshot: task_count не совпадает с фактическим числом tasks"
                )

    if todoist["status"] == "stale":
        warnings.append(
            "Todoist stale: список задач может отличаться от текущего состояния в Todoist."
        )

    if todoist["status"] == "unavailable":
        warnings.append(
            "Todoist unavailable: актуальные задачи в контексте отсутствуют."
        )

    return {"errors": errors, "warnings": warnings}


def build_context(
    *,
    todoist_status: str = "stale",
    today: date | None = None,
) -> dict[str, Any]:
    """
    Собрать полный структурированный контекст.

    todoist_status:
      fresh       — синхронизация Todoist только что завершилась успешно;
      stale       — свежесть не подтверждена, использовать последний snapshot;
      unavailable — синхронизация не удалась/недоступна. Если старый snapshot
                    существует, он автоматически используется как stale.
    """
    config = load_config()
    tz = ZoneInfo(config["timezone"])

    context: dict[str, Any] = {
        "meta": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "local_timezone": config["timezone"],
            "local_date": (today or datetime.now(tz).date()).isoformat(),
            "history_days": config["recent_history_days"],
            "warnings": [],
        },
        "core": load_core_memory(config),
        "history": load_recent_history(config, today=today),
        "analytics": load_analytics(config),
        "pending_changes": load_pending_changes(config),
        "unknowns": load_placeholders(config),
        "links": {
            "todoist": load_todoist_links(config),
        },
        "todoist": load_todoist_context(
            config,
            status=todoist_status,
        ),
    }

    validation = validate_context(context)

    if validation["errors"]:
        details = "\n".join(f"- {item}" for item in validation["errors"])
        raise ContextBuildError(
            "Контекст не прошёл обязательную проверку:\n" + details
        )

    context["meta"]["warnings"] = validation["warnings"]
    return context


def dump_context(context: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_text(
        json.dumps(context, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temp_path.replace(path)


def _default_dump_path() -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return PROJECT_ROOT / "data" / "debug" / f"context_{stamp}.json"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Собрать и проверить контекст персонального AI-ассистента."
    )
    parser.add_argument(
        "--todoist-status",
        choices=("fresh", "stale", "unavailable"),
        default="stale",
        help=(
            "fresh — Todoist только что успешно синхронизирован; "
            "stale — использовать последний снимок; "
            "unavailable — свежий Todoist недоступен."
        ),
    )
    parser.add_argument(
        "--dump-context",
        nargs="?",
        const="AUTO",
        metavar="PATH",
        help=(
            "Сохранить полный контекст в JSON. "
            "Если PATH не указан, файл создаётся в data/debug/."
        ),
    )
    args = parser.parse_args()

    try:
        context = build_context(todoist_status=args.todoist_status)
    except ContextBuildError as exc:
        raise SystemExit(f"Ошибка сборки контекста:\n{exc}") from exc

    print("Контекст собран успешно.")
    print(f"Сфер: {len(context['core']['areas'])}")
    print(f"Целей: {len(context['core']['goals'])}")
    print(f"Проектов: {len(context['core']['projects'])}")
    print(f"Дней истории: {len(context['history'])}")
    print(f"Pending changes: {len(context['pending_changes'])}")
    print(f"Todoist status: {context['todoist']['status']}")

    snapshot = context["todoist"].get("snapshot")
    if snapshot:
        print(f"Todoist tasks: {len(snapshot.get('tasks', []))}")

    for warning in context["meta"]["warnings"]:
        print(f"ПРЕДУПРЕЖДЕНИЕ: {warning}")

    if args.dump_context:
        path = (
            _default_dump_path()
            if args.dump_context == "AUTO"
            else Path(args.dump_context).expanduser()
        )
        if not path.is_absolute():
            path = PROJECT_ROOT / path
        dump_context(context, path)
        print(f"Контекст сохранён: {path}")


if __name__ == "__main__":
    main()
