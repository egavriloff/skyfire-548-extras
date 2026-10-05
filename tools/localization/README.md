# Localization toolkit (MVP)

Офлайн-инструменты для просмотра, сравнения и подготовки reviewable SQL локализаций для World DB SkyFire 5.4.8. В первом MVP поддерживаются только `gossip_menu_option`, `item` и `gameobject`.

После fresh clone подготовьте источники в стандартной структуре:

```text
.porting/sources/
  alexkulya/
    repo/
    db/
  loap/
    repo/
    db/
  skyfire/
    repo/
    db/
```

Поместите repository checkouts в `repo/`, при необходимости дополнительные full/release DB dumps — в `db/`. Затем из корня workspace выполните `python tools/localization/localize.py index`. Создавать `inventory.json` вручную не нужно. Для runtime достаточно стандартной библиотеки Python; Git нужен только для определения revision, если source содержит независимые `.git`-метаданные.

```powershell
python tools/localization/localize.py index
python tools/localization/localize.py inspect item 12345 --locale ruRU
python tools/localization/localize.py compare item 12345 --locale ruRU
python tools/localization/localize.py export item 12345 --locale ruRU --output .porting/localization/review/item-12345.sql
python tools/localization/localize.py export-manifest item 12345 --locale ruRU --output .porting/localization/review/item-12345.json
python -m unittest discover -s tools/localization/tests -v
```

Команда `index` при каждом запуске самостоятельно рекурсивно обнаруживает `*.sql` в `repo/` и `db/` каждого source, включая SQL внутри ZIP. Сегменты каталогов `old`, `pending`, `archive`, `archives`, `deprecated`, `legacy` исключаются на любом уровне без учёта регистра, включая пути внутри ZIP. SQL-файлы и члены ZIP читаются потоково с ограниченным буфером; архивы не распаковываются. `inventory.json` не используется как вход: его отсутствие или устаревшее содержимое не мешает первому и повторному запуску. SQLite индекс и кэш создаются только в `.porting/localization/`; повторный `index` обнаруживает актуальный набор файлов и перестраивает индекс. Если SQL-источников нет, команда сообщает ошибку, сохраняя прежний индекс.

При совпадении ключей приоритет такой: SQL из repository base, затем полный/release dump из `db/`, затем repository updates в лексикографическом порядке путей. `DELETE` поддерживает equality, `IN`, `BETWEEN` и соединение условий через `AND`, включая удаление всех options по одному `MenuID`. Literal `UPDATE` применяются к существующим индексированным locale-значениям и identity-полям; очистка текста удаляет прежнее значение. Операции выполняются один раз в соответствующем проходе индексации.

Строковые локали проверяются по подтверждённой enum-карте. AlexKulya/LOAP индексируются из row-based таблиц, используемых loaders; одноимённые target wide-таблицы из upstream не смешиваются с ними. Широкие таблицы SkyFire `locales_item` и `locales_gameobject` представляются логическими строками locale с преобразованием `_locN` (`enUS` хранится в базовых полях сущности). Для gossip используется только `gossip_menu_option_locale`.

Экспорт не подключается к базе и не выполняется автоматически. Для item/gameobject создаётся строка в соответствующей широкой таблице; `ON DUPLICATE KEY UPDATE` заполняет только пустые поля. Для gossip генерируется upsert, который тоже заполняет только пустые поля. Разногласие upstream-источников и отличающееся непустое target-значение получают статус `CONFLICT` и не экспортируются. Экспорт требует существующей target-сущности и подтверждения identity по полям: item — name, gameobject — name/type, gossip — общий broadcast ID либо совпадающий базовый option text. Одного числового ID недостаточно. SQL сохраняет UTF-8 и экранирует MySQL backslash, кавычки и управляющие символы.

`export-manifest` создаёт детерминированный JSON со статусами сравнения и provenance. Revision указывается только при наличии независимых `.git`-метаданных у source checkout; иначе revision помечается как непроверенный, а SHA родительского workspace не выдаётся за версию upstream.

Парсер обрабатывает нужные `CREATE TABLE`, literal `INSERT`/`REPLACE`, ограниченный набор `DELETE`/`UPDATE` и literal user variables (`SET @name:=value`, `SET @name=value`). Для LOAP предусмотрен адаптер известного JOIN-переноса `BoxText` из `gossip_menu_option_box`; вспомогательная таблица не является новым entity type. UPDATE только игровых metadata-полей потребляются без применения к localization-индексу. Произвольные SQL-выражения, другие JOIN и хранимые процедуры не вычисляются. Неоднозначные identity и неподдержанные операции следует проверять по warnings; непроверенную сущность toolkit исключает из экспорта. Live DB соединение не реализовано.
