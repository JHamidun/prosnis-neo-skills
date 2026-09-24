# Брендированные PDF эфира: саммари и транскрипт

Шаблоны HTML → A4 PDF через headless Chromium (Playwright). Дизайн тот же, что у ролика (`style/tokens.json`):
navy-сцена, коралл — «наш слой», Manrope + Caveat + JetBrains Mono, скетчи колоды (`assets/art/*.png`, вырезаны из
арта колоды и отделены от фона). Эталон — материалы эфира 23.09.2026: транскрипт 44 страницы, саммари 9 страниц.

Папку целиком копируют в `<job>/materials/pdf_templates/`, данные эфира кладут в `data/` (образцы — `data/*.example.json`,
переименовать без `.example`). Скрипты находят джобу сами: `--job <job.json>`, `$WEBINAR_JOB` или `../../job.json`.

## Запуск

```bash
cd <job>/materials/pdf_templates
python prepare_assets.py --job <job.json>        # вырезки скетчей (data/art_crops.json), логотипы, QR из outro.links
python make_all.py --job <job.json>              # черновики: out/*_ЧЕРНОВИК.pdf, таймкоды предварительные
python make_all.py --job <job.json> --timemap <job>/materials/final_timemap.json \
    --event-link <url> --pdf-link <url> --final --outdir <job>/publish/materials
```

`--final` откажется рендерить, если остался плейсхолдер `{UPPER_CASE}` или таймкоды не финальные.
`--drop-pending-links` — отрендерить сейчас, спрятав ссылки, которых ещё нет.
После рендера смотреть глазами `_qa/<kind>/p*.png` и `_qa/<kind>.render.json` (страницы, ссылки, предупреждения
линтера); сетка страниц — `python qa_sheet.py <pdf> 1,2,5 out.png`.

## Таймкоды транскрипта

`build_transcript_data.py` берёт слова всех источников (кусок диктофона — путь `words` из `timeline.json → files`,
части — `transcript/<part>.words.json`) и переводит время исходника во время ролика:

    edit_t = edit_in + (src_t − src_in)   для куска таймкарты, в который попадает src_t

Без `--timemap` — черновая карта из `timeline.json` (рекомендованные сегменты, без заставки и внутренних вырезов).
Финальная карта — из EDL монтажа (`scripts/webinar/deliver/build_final_timemap.py`): тизер не входит, вырез = разрыв
между кусками:

```json
{"segments": [
  {"source": "intro_plaud", "src_in": 280.25, "src_out": 564.75, "edit_in": 26.9},
  {"source": "part1", "src_in": 2.568, "src_out": 210.3, "edit_in": 311.4}
]}
```

Слова вне кусков выпадают (вырезаны из ролика). Главы привязаны к карточкам глав ролика (`anchor.card_n`) или к фразе
(`anchor {source, phrase}`) и пересчитываются сами. Абзацы: смена спикера, граница главы, ~520 знаков до конца предложения или
пауза ≥ 2,2 с; междометия «ээ/эм/ммм» убраны; фрагменты видео — отдельные блоки. Лёгкая литправка (`light_edit`):
паразиты только в запятых, повторы-заикания; в эталоне −4,3 % слов.

## Файлы данных

| Файл | Что внутри |
|---|---|
| `data/transcript.data.json` | генерируется: `meta` (timecodes provisional/final, длительность, слова, журнал правок), `doc`, `speakers`, `chapters[] {n,title,lead,art,theme,t,tc}`, `paragraphs[] {t,tc,chapter,speaker,kind,label,text}` |
| `data/transcript_doc.json` | тексты обложки транскрипта, спикеры (`name` = имя спикера в ASR), ссылки на запись и PDF деки |
| `data/transcript_chapters.json` | главы: название, подзаголовок, скетч, тема карточки (dark/paper), якорь |
| `data/transcript_redactions.json` | обязательные правки текста; сборка ПАДАЕТ, если правка не нашла своё место |
| `data/transcript_asr_fixes.json` | очевидные ошибки распознавания `[pattern, replacement, min_hits]` |
| `data/summary.data.json` | весь текст саммари; `chapters: "@transcript"` подтягивает главы и таймкоды из транскрипта |
| `data/shared.json` | общая страница «Что дальше», ссылки материалов, `allowed_url_hosts` (белый список ссылок) |
| `data/art_crops.json` | вырезки иллюстраций из арта колоды: `{"имя": ["файл арта", [x0, y0, x1, y1]]}` |

Схема `summary.data.json`: `doc {kind, eyebrow, title, title_accent, subtitle, lead, host, host_role, co[], date}`,
`stats[] {value,label}`, `cover_chips[]`, `about {title, paragraphs[]}`, `chapters`, `ideas[] {title,text,art}`,
`cases[] {title, chapter, art?, text, facts[]}`, `world {title, items[] {value,text}, footnote}`,
`chat {title, lead, stats[], polls[] {title, note, bars[] {label,value,correct?}}, questions[] {who,q,a}, thanks}`,
`raffle {title, lead, grand {badge,handle,note,prize}, winners[] {n,ticket,handle,prize}, key, fingerprint, tickets, note}`.
Скетч `art` = имя файла в `assets/art/`; светлые штрихи сами получают тёмную карточку, тёмные — бумажную.

job.json: `author` и `brand.name` (метаданные PDF), `brand.header` (колонтитул каждой страницы), `brand.dir`,
`brand.logo_svg` (логотип для тёмного фона; вариант для бумаги перекрашивается сам), `brand.mark_svg`, `deck.art_dir`,
`outro.links[] {url, qr: true, qr_file?}` (QR: `prepare_assets.py` пишет `assets/brand/qr-<индекс в outro.links>-navy.png`
или `qr_file`; какие файлы стоят на странице «Что дальше» — `shared.json → next.intensive.qr` (контакт, по умолчанию
`qr-0-navy.png`) и `next.bot.qr` (бот, по умолчанию `qr-1-navy.png`); пустая строка прячет плитку. Нет файла — рендер
падает на битой картинке), `materials.pdf_names {transcript, summary}`, `materials.keywords[]`,
`materials.rules[]` (правила текста, ниже).

## Правила текста (линтер `render_pdf.py` предупреждает)

Встроенные правила — общие: e-mail и телефоны в тексте (саммари и транскрипт), суммы и цены (саммари: не цена ли это
вашего продукта); ссылки только из `allowed_url_hosts`, остальное — через плейсхолдеры `{EVENT_PAGE_LINK}`,
`{PDF_LINK}`; участники — только по имени.

Свои правила владельца (как называть продукт, какие утверждения запрещены, какие темы не выносить в публичные тексты)
кладутся в `job.json → materials.rules` и ДОБАВЛЯЮТСЯ к встроенным — их же читает `deliver/make_text_materials.py`:

```json
"rules": [
  ["\\b<запрещённое слово>\\w*\\b", "говорим «<как надо>», а не «<как нельзя>»", ["summary"]],
  ["<регэксп запрещённого утверждения>", "запрещённая формулировка", ["summary", "transcript"]]
]
```

Третий элемент — где проверять: `summary` (саммари, тексты RuTube) и/или `transcript` (транскрипт: сказанное не
переписываем, поэтому туда — только то, что должно держаться и в устной речи); не указан — только `summary`.

Гочи шрифтов для PyMuPDF/PIL (статические веса, проверка сигнатуры файла) — `references/webinar-gotchas.md` G-F1…G-F5.
