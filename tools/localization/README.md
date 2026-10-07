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
python tools/localization/localize.py export-all --locale ruRU
```

Основной workflow: подготовить `.porting/sources/`, построить index, выполнить `export-all`, проверить SQL и report. `inspect`/`compare` используйте для конфликтов и подозрительных entries; одиночные `export` и `export-manifest` остаются доступны.

Для одного entity type:

```powershell
python tools/localization/localize.py export-all item --locale ruRU
python tools/localization/localize.py inspect item 12345 --locale ruRU
python tools/localization/localize.py compare item 12345 --locale ruRU
python tools/localization/localize.py export item 12345 --locale ruRU --output .porting/localization/review/item-12345.sql
python tools/localization/localize.py export-manifest item 12345 --locale ruRU --output .porting/localization/review/item-12345.json
python -m unittest discover -s tools/localization/tests -v
```

Команда `index` при каждом запуске самостоятельно рекурсивно обнаруживает `*.sql` в `repo/` и `db/` каждого source, включая SQL внутри ZIP. Сегменты каталогов `old`, `pending`, `archive`, `archives`, `deprecated`, `legacy` исключаются на любом уровне без учёта регистра, включая пути внутри ZIP. SQL-файлы и члены ZIP читаются потоково с ограниченным буфером; архивы не распаковываются. `inventory.json` не используется как вход: его отсутствие или устаревшее содержимое не мешает первому и повторному запуску. SQLite индекс и кэш создаются только в `.porting/localization/`; повторный `index` обнаруживает актуальный набор файлов и перестраивает индекс. Если SQL-источников нет, команда сообщает ошибку, сохраняя прежний индекс.

`export-all --locale ruRU` создаёт `.porting/localization/review/item-ruRU.sql`, `gameobject-ruRU.sql`, `gossip_menu_option-ruRU.sql` и общий `report-ruRU.json`. При указании entity type создаются его SQL и report только для выбранного type. Повторный запуск перезаписывает соответствующие generated файлы. Имена и содержание не зависят от времени запуска; порядок — entity type, numeric/composite key, locale. SQL и подробности отчёта записываются потоково. Запуск выполняет SELECT в локальном SQLite index; подключения к live DB нет.

Bulk selection берёт только существующие SkyFire entities из index. Индекс сейчас содержит sparse selection base entities по candidate IDs, поэтому `total_target_entities` означает количество **индексированных** target entities, а не всех сущностей live World DB. Upstream-only IDs не обходятся. `SOURCE_ONLY` требует подтверждённой identity именно источника перевода. Любой `CONFLICT` или `UNSUPPORTED` в полях entity/locale блокирует всю строку bulk SQL. Отсутствующее дополнительное текстовое поле не мешает экспортировать другое безопасное поле. Непустые target translations сохраняются. `enUS` хранится в base entity tables и не является locale для `export-all`.

Report содержит `summary` по entity types, `totals` и `entries` для всех пропущенных entity/locale. В entries сохраняются причины, результаты по полям, значения AlexKulya/LOAP/SkyFire, source table/file provenance и доступные base entities для проверки identity. Счётчики `total_target_entities`, `candidates_found`, `exported`, `skipped`, `identity_failed`, `unsupported` относятся к entity/locale, а не к полям. `MATCH`, `SOURCE_ONLY`, `TARGET_IDENTICAL`, `CONFLICT`, `MISSING`, `UNSUPPORTED` — взаимоисключающие итоговые статусы строк; при сочетании MATCH и SOURCE_ONLY строка считается SOURCE_ONLY. `identity_failed` входит в `unsupported`; `skipped = total_target_entities - exported`. Конфликты имеют приоритет над безопасными полями, а неподтверждённая identity — над сравнением текстов. Report сохраняет исходные значения даже при failed identity.

Bulk provenance берётся из index. Текущий index не сохраняет revisions upstream, поэтому bulk SQL помечает их как `revision-unverified`; текущий Git HEAD не выдаётся за revision индексированных данных и не влияет на повторяемость результата. Статусы сравнения, identity и формат SQL общие с одиночным экспортом; bulk повторно использует рассчитанные значения, чтобы избежать лишних запросов.

Для item предусмотрен отдельный статус `SAFE_SINGLE_IDENTITY`: ровно один upstream подтверждает базовое name SkyFire, другой имеет отличающееся name, но оба дают одинаковые localization values по всем текстовым полям выбранной locale. Обязательные `class/subclass` и все дополнительные структурные поля, сохранённые в index, должны присутствовать и совпадать у всех трёх источников. Пустая identity, отсутствующая base entity, расхождение текстов, неполные структурные данные или конфликт с непустым target translation блокируют экспорт. Проверка ограничена полями index: текущий MVP сохраняет для item `class/subclass`, но не полную структуру `item_template`.

По умолчанию `SAFE_SINGLE_IDENTITY` только фиксируется в report и не экспортируется. Opt-in:

```powershell
python tools/localization/localize.py export-all item --locale ruRU --allow-single-identity
```

Этот статус учитывается отдельно от `MATCH`. Report сохраняет `allow_single_identity`, а для каждой такой записи — подтвердивший/отклонённый upstream, base entities, проверенные structural fields, localization text, provenance и reason. Такие entries сохраняются **и после экспорта**, с `exported: true`; SQL также содержит комментарий `SAFE_SINGLE_IDENTITY`. Одиночные команды и policy для gameobject/gossip остаются прежними. Перезапись generated файлов при повторном запуске сохраняется.

Verified aliases для gameobject/gossip — отдельный, выключенный по умолчанию режим:

```powershell
python tools/localization/localize.py index
python tools/localization/localize.py export-all gameobject --locale ruRU --allow-verified-aliases
python tools/localization/localize.py export-all gossip_menu_option --locale ruRU --allow-verified-aliases
```

После обновления toolkit обязательно перестройте index: старый cache не содержит достаточного structural evidence. Upstream gossip base rows теперь выбираются по общему набору gossip candidate keys обоих upstream, даже без собственных locale records. Base evidence и localization records остаются раздельными. Сохраняются option type/icon, npc flag, action menu/POI, box coded/money, option/box broadcast IDs; legacy LOAP action/box tables восстанавливаются известной JOIN-миграцией. Для gameobject сохраняются model/display, size, data slots и остальные поддержанные структурные поля. Структурные literal UPDATE, IN/BETWEEN, tuple IN и comparisons обновляют evidence; непонятная структурная операция помечает затронутое evidence как неполное, что блокирует alias.

Список фиксирован: gameobject **57708** (`Lamp Post` → `Lamppost`, type 8), **170524** (`Bench` → `Bench]`, type 7); gossip **0,1**, **0,3**, **0,9**, **125,0**, **126,0**. В `localize.py` зафиксированы точные English строки и ожидаемые broadcast IDs. Нормализации пунктуации/пробелов нет; gameobject 3642 и gossip 0,12 не входят в список. Правила действуют только для `ruRU`.

Alias требует всех трёх base entities и точного совпадения шаблона имён/текстов. Для gameobject обязательны type/display/size/data0..31, отсутствие противоречий в доступных дополнительных structural fields и одинаковые upstream ruRU values. Для gossip обязательны совпадающие поля действий и box, подтверждение ожидаемого target broadcast ID со стороны LOAP и непротиворечивый AlexKulya ruRU candidate. Любой непустой target locale (даже совпадающий), translation conflict, structural mismatch, отсутствующее обязательное поле или incomplete evidence запрещает alias.

Итоговый статус — **VERIFIED_ALIAS**, отдельно от MATCH/SOURCE_ONLY. Без флага запись отражается в report и пропускается. С флагом report сохраняет её и после экспорта: rule name/reason, source/target English texts, структурные значения всех источников, broadcast evidence, localization values и file/table provenance. SQL содержит комментарий `VERIFIED_ALIAS`. Флаг не распространяется на item и не меняет общую identity policy. Старые index без необходимого evidence не получают разрешение.

При совпадении ключей приоритет такой: SQL из repository base, затем полный/release dump из `db/`, затем repository updates в лексикографическом порядке путей. `DELETE` поддерживает equality, `IN`, `BETWEEN` и соединение условий через `AND`, включая удаление всех options по одному `MenuID`. Literal `UPDATE` применяются к существующим индексированным locale-значениям и identity-полям; очистка текста удаляет прежнее значение. Операции выполняются один раз в соответствующем проходе индексации.

Строковые локали проверяются по подтверждённой enum-карте. AlexKulya/LOAP индексируются из row-based таблиц, используемых loaders; одноимённые target wide-таблицы из upstream не смешиваются с ними. Широкие таблицы SkyFire `locales_item` и `locales_gameobject` представляются логическими строками locale с преобразованием `_locN` (`enUS` хранится в базовых полях сущности). Для gossip используется только `gossip_menu_option_locale`.

Экспорт не подключается к базе и не выполняется автоматически. Для item/gameobject создаётся строка в соответствующей широкой таблице; `ON DUPLICATE KEY UPDATE` заполняет только пустые поля. Для gossip генерируется upsert, который тоже заполняет только пустые поля. Разногласие upstream-источников и отличающееся непустое target-значение получают статус `CONFLICT` и не экспортируются. Экспорт требует существующей target-сущности и подтверждения identity по полям: item — name, gameobject — name/type, gossip — общий broadcast ID либо совпадающий базовый option text. Одного числового ID недостаточно. SQL сохраняет UTF-8 и экранирует MySQL backslash, кавычки и управляющие символы.

`export-manifest` создаёт детерминированный JSON со статусами сравнения и provenance. Revision указывается только при наличии независимых `.git`-метаданных у source checkout; иначе revision помечается как непроверенный, а SHA родительского workspace не выдаётся за версию upstream.

Парсер обрабатывает нужные `CREATE TABLE`, literal `INSERT`/`REPLACE`, ограниченный набор `DELETE`/`UPDATE` и literal user variables (`SET @name:=value`, `SET @name=value`). Для LOAP предусмотрен адаптер известного JOIN-переноса `BoxText` из `gossip_menu_option_box`; вспомогательная таблица не является новым entity type. UPDATE только игровых metadata-полей потребляются без применения к localization-индексу. Произвольные SQL-выражения, другие JOIN и хранимые процедуры не вычисляются. Неоднозначные identity и неподдержанные операции следует проверять по warnings; непроверенную сущность toolkit исключает из экспорта. Live DB соединение не реализовано.
