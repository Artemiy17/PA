from integrations.todoist.sync import sync_todoist


def main() -> None:
    snapshot = sync_todoist()
    print(f"Получено активных задач: {snapshot['task_count']}")


if __name__ == "__main__":
    main()
