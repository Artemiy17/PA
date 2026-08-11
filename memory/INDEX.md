# Индекс памяти

## Основная память

`memory/core/areas.yaml` — жизненные сферы.  
`memory/core/goals.yaml` — цели.  
`memory/core/projects.yaml` — проекты.  
`memory/core/obligations.yaml` — обязательства.  
`memory/core/routines.yaml` — регулярные действия.  
`memory/core/facts.yaml` — устойчивые важные факты.  
`memory/core/priorities.yaml` — стратегические приоритеты.

Основная память считается подтверждённой.
Существенные изменения требуют approve.

## История

`memory/history/YYYY/MM/YYYY-MM-DD.md`

Хранит планы, фактическое выполнение, причины невыполнения, события и изменения.

## Аналитика

`memory/analytics/observations.yaml`

Содержит гипотезы и наблюдения.
Не является подтверждённой основной памятью.

## Ожидающие изменения

`memory/pending/core_changes.yaml`

Содержит предложения изменений основной памяти до решения пользователя.

## Неизвестные данные

`memory/PLACEHOLDERS.yaml`

Содержит сведения, которые нужно уточнить.
Placeholder не является фактом.

## Todoist

Задачи не копируются в `memory/core/`.
Todoist остаётся отдельным источником задач.

Связи между Todoist и памятью находятся в:

`memory/links/todoist.yaml`

## Загрузка

Обычный контекст собирается через:

`context_builder.py`

Он загружает:
1. основную память;
2. последние N дней истории;
3. действующую аналитику;
4. pending changes;
5. placeholders;
6. связи Todoist;
7. текущий Todoist snapshot и diff.

`bootstrap_candidates.yaml` в обычный контекст не загружается.
Он используется только при начальной калибровке или отдельной проверке.
