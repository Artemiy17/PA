# PA TODOIST NORMALIZED SYNC v4 + DIFF
from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .client import TODOIST_API_BASE_URL, TodoistClient


SYNC_VERSION = "normalized-v4-diff"

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data" / "todoist"

OUTPUT_PATH = DATA_DIR / "tasks.json"
PREVIOUS_PATH = DATA_DIR / "tasks.prev.json"
DIFF_PATH = DATA_DIR / "tasks.diff.json"


# Поля, изменения которых считаем содержательными.
DIFF_FIELDS = (
    "content",
    "description",
    "project",
    "section",
    "parent",
    "labels",
    "priority",
    "due",
    "deadline",
    "duration",
    "child_order",
    "is_collapsed",
    "postponed_count",
)


def get_all(client: TodoistClient, resource: str) -> list[dict[str, Any]]:
    """Получить все страницы ресурса Todoist API."""
    url = f"{TODOIST_API_BASE_URL}/{resource}"
    items: list[dict[str, Any]] = []
    cursor: str | None = None
    seen_ids: set[str] = set()

    while True:
        params: dict[str, Any] = {"limit": 200}
        if cursor:
            params["cursor"] = cursor

        response = client.session.get(
            url,
            params=params,
            timeout=client.timeout,
        )
        response.raise_for_status()
        payload = response.json()

        for item in payload.get("results", []):
            item_id = str(item.get("id", ""))
            if item_id and item_id in seen_ids:
                continue
            if item_id:
                seen_ids.add(item_id)
            items.append(item)

        cursor = payload.get("next_cursor")
        if not cursor:
            break

    return items


def normalize_task(
    task: dict[str, Any],
    projects_by_id: dict[str, dict[str, Any]],
    sections_by_id: dict[str, dict[str, Any]],
    tasks_by_id: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Преобразовать сырую Todoist-задачу в нормализованный формат."""

    project_id = str(task["project_id"]) if task.get("project_id") else None
    section_id = str(task["section_id"]) if task.get("section_id") else None
    parent_id = str(task["parent_id"]) if task.get("parent_id") else None

    project = projects_by_id.get(project_id) if project_id else None
    section = sections_by_id.get(section_id) if section_id else None
    parent = tasks_by_id.get(parent_id) if parent_id else None

    return {
        "id": str(task["id"]),
        "content": task.get("content", ""),
        "description": task.get("description", ""),

        "project": (
            {
                "id": project_id,
                "name": project.get("name") if project else None,
            }
            if project_id
            else None
        ),

        "section": (
            {
                "id": section_id,
                "name": section.get("name") if section else None,
            }
            if section_id
            else None
        ),

        "parent": (
            {
                "id": parent_id,
                "content": parent.get("content") if parent else None,
            }
            if parent_id
            else None
        ),

        "labels": task.get("labels", []),
        "priority": task.get("priority", 1),
        "due": task.get("due"),
        "deadline": task.get("deadline"),
        "duration": task.get("duration"),
        "child_order": task.get("child_order"),
        "is_collapsed": task.get("is_collapsed", False),
        "postponed_count": task.get("postponed_count", 0),
        "added_at": task.get("added_at"),
        "updated_at": task.get("updated_at"),
    }


def load_snapshot(path: Path) -> dict[str, Any] | None:
    """Прочитать snapshot, если он существует и является корректным JSON."""
    if not path.exists():
        return None

    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def compact_task(task: dict[str, Any]) -> dict[str, Any]:
    """Компактное представление задачи для diff."""
    return {
        "id": task.get("id"),
        "content": task.get("content"),
        "project": task.get("project"),
        "section": task.get("section"),
        "parent": task.get("parent"),
        "priority": task.get("priority"),
        "due": task.get("due"),
        "deadline": task.get("deadline"),
    }


def build_diff(
    previous: dict[str, Any] | None,
    current: dict[str, Any],
) -> dict[str, Any]:
    """
    Сравнить два нормализованных snapshot по task.id.

    Важно:
    Todoist sync получает активные задачи.
    Поэтому задача, исчезнувшая из нового snapshot, обозначается как
    removed_from_active, а не автоматически как completed.
    """

    current_tasks = {
        str(task["id"]): task
        for task in current.get("tasks", [])
        if task.get("id") is not None
    }

    # Первый запуск: предыдущего состояния нет.
    if not previous:
        return {
            "source": "todoist",
            "sync_version": SYNC_VERSION,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "baseline": True,
            "summary": {
                "added": len(current_tasks),
                "removed_from_active": 0,
                "changed": 0,
                "unchanged": 0,
            },
            "added": [compact_task(task) for task in current_tasks.values()],
            "removed_from_active": [],
            "changed": [],
        }

    previous_tasks = {
        str(task["id"]): task
        for task in previous.get("tasks", [])
        if task.get("id") is not None
    }

    previous_ids = set(previous_tasks)
    current_ids = set(current_tasks)

    added_ids = sorted(current_ids - previous_ids)
    removed_ids = sorted(previous_ids - current_ids)
    common_ids = previous_ids & current_ids

    changed: list[dict[str, Any]] = []
    unchanged_count = 0

    for task_id in sorted(common_ids):
        old_task = previous_tasks[task_id]
        new_task = current_tasks[task_id]

        changes: dict[str, Any] = {}

        for field in DIFF_FIELDS:
            old_value = old_task.get(field)
            new_value = new_task.get(field)

            if old_value != new_value:
                changes[field] = {
                    "before": old_value,
                    "after": new_value,
                }

        if changes:
            changed.append(
                {
                    "id": task_id,
                    "content": new_task.get("content"),
                    "changes": changes,
                }
            )
        else:
            unchanged_count += 1

    return {
        "source": "todoist",
        "sync_version": SYNC_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "baseline": False,
        "previous_synced_at": previous.get("synced_at"),
        "current_synced_at": current.get("synced_at"),
        "summary": {
            "added": len(added_ids),
            "removed_from_active": len(removed_ids),
            "changed": len(changed),
            "unchanged": unchanged_count,
        },
        "added": [
            compact_task(current_tasks[task_id])
            for task_id in added_ids
        ],
        "removed_from_active": [
            compact_task(previous_tasks[task_id])
            for task_id in removed_ids
        ],
        "changed": changed,
    }


def write_json_atomic(path: Path, data: dict[str, Any]) -> None:
    """Безопасно записать JSON через временный файл."""
    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temp_path.replace(path)


def sync_todoist() -> tuple[dict[str, Any], dict[str, Any]]:
    """
    Полный цикл:
    1. получить задачи + проекты + секции;
    2. нормализовать;
    3. сравнить с предыдущим tasks.json;
    4. сохранить tasks.prev.json;
    5. записать новый tasks.json;
    6. записать tasks.diff.json.
    """

    client = TodoistClient()

    # Состояние ДО синхронизации.
    previous_snapshot = load_snapshot(OUTPUT_PATH)

    # Получаем свежие данные Todoist.
    raw_tasks = client.get_active_tasks()
    raw_projects = get_all(client, "projects")
    raw_sections = get_all(client, "sections")

    projects_by_id = {
        str(project["id"]): project
        for project in raw_projects
    }
    sections_by_id = {
        str(section["id"]): section
        for section in raw_sections
    }
    tasks_by_id = {
        str(task["id"]): task
        for task in raw_tasks
    }

    tasks = [
        normalize_task(
            task=task,
            projects_by_id=projects_by_id,
            sections_by_id=sections_by_id,
            tasks_by_id=tasks_by_id,
        )
        for task in raw_tasks
    ]

    current_snapshot: dict[str, Any] = {
        "source": "todoist",
        "sync_version": SYNC_VERSION,
        "synced_at": datetime.now(timezone.utc).isoformat(),
        "task_count": len(tasks),
        "tasks": tasks,
    }

    DATA_DIR.mkdir(parents=True, exist_ok=True)

    # Считаем diff ДО замены текущего snapshot.
    diff = build_diff(previous_snapshot, current_snapshot)

    # Сохраняем старое состояние.
    if OUTPUT_PATH.exists():
        shutil.copy2(OUTPUT_PATH, PREVIOUS_PATH)

    # Записываем новое состояние и diff.
    write_json_atomic(OUTPUT_PATH, current_snapshot)
    write_json_atomic(DIFF_PATH, diff)

    return current_snapshot, diff


def main() -> None:
    snapshot, diff = sync_todoist()
    summary = diff["summary"]

    print(
        f"Todoist sync OK [{SYNC_VERSION}]: "
        f"{snapshot['task_count']} active tasks"
    )
    print(f"Current:  {OUTPUT_PATH}")

    if PREVIOUS_PATH.exists():
        print(f"Previous: {PREVIOUS_PATH}")

    print(f"Diff:     {DIFF_PATH}")
    print(
        "Changes: "
        f"+{summary['added']} added, "
        f"-{summary['removed_from_active']} removed_from_active, "
        f"~{summary['changed']} changed"
    )


if __name__ == "__main__":
    main()