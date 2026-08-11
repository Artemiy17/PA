from __future__ import annotations

import os
from typing import Any

import requests
from dotenv import load_dotenv


TODOIST_API_BASE_URL = "https://api.todoist.com/api/v1"


class TodoistClient:
    """Минимальный клиент Todoist API v1."""

    def __init__(self, api_token: str | None = None, timeout: int = 30) -> None:
        load_dotenv()
        self.api_token = api_token or os.getenv("TODOIST_API_TOKEN")
        if not self.api_token:
            raise RuntimeError(
                "TODOIST_API_TOKEN не найден. Создай .env на основе .env.example "
                "и вставь туда Todoist API token."
            )

        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"Bearer {self.api_token}",
                "Accept": "application/json",
            }
        )

    def get_active_tasks(self) -> list[dict[str, Any]]:
        """Получить все активные задачи пользователя с обработкой пагинации."""
        url = f"{TODOIST_API_BASE_URL}/tasks"
        tasks: list[dict[str, Any]] = []
        cursor: str | None = None
        seen_ids: set[str] = set()

        while True:
            params: dict[str, Any] = {"limit": 200}
            if cursor:
                params["cursor"] = cursor

            response = self.session.get(url, params=params, timeout=self.timeout)
            response.raise_for_status()
            payload = response.json()

            for task in payload.get("results", []):
                task_id = str(task.get("id", ""))
                if task_id and task_id in seen_ids:
                    continue
                if task_id:
                    seen_ids.add(task_id)
                tasks.append(task)

            cursor = payload.get("next_cursor")
            if not cursor:
                break

        return tasks
