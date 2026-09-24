# Запись эфира → длинный смонтированный ролик (Zoom/стрим + диктофон)

Пайплайн, которым смонтирован двухчасовой вебинар 23.09.2026: две локальные записи Zoom 4K (одна пришла от
со-ведущего), непрерывная запись диктофона (начало эфира есть только на нём), живой чат с опросами и розыгрышем,
дека из 76 рисованных слайдов с 15 роликами. Итог: 2:03:20 = 184 998 кадров 25 fps, 16 карточек глав, 1 935 реплик
караоке, 403 пузыря чата, 11 опросов, розыгрыш с баннерами и конфетти, −16,0 LUFS / −1,5 dBTP.

Код — `scripts/webinar/<стадия>/`, шаблоны — `templates/` (Remotion-проект `remotion-program`, PDF-материалы,
обложка, `job.example.json`, `edl_config.example.json`). Гочи с номерами G-… — `webinar-gotchas.md`.
Выдача (тексты, PDF, обложка, публикация) — `webinar-deliverables.md`. Сторис из хайлайтов — навык
`sketch-course-video` (`references/webinar-stories.md`). PDF деки с кликабельными роликами — навык `manus-slides`.

## Планка качества — «упрощение мне не нужно»

Слова владельца, и они относятся ко всему: к рендеру, к анимациям, к этому описанию. Скорость не покупается
упрощением: если рендер медленный — добавляют воркеры, режут клипы на входе, держат браузер открытым, но не убирают
живые скетчи, пометки в координатах слайда, морфы и чат. Эталон качества задаётся ВИДЕО владельца (`job.json
qa.reference`), а не словами; с ним сравнивает `qa/qa_reference.py`.

Что зритель должен видеть: чистый слайд вместо мутной трансляции Zoom; живой скетч, который рисуется под слова;
пометки маркером там, где ведущий «тыкает»; дудлы вокруг слайда для метафор; камеры с наездами на эмоции; живой чат
в порядке прихода, опросы карточками, реакции иконками; караоке с плашкой ключевого слова; карточки глав с рисунком;
плашки имён; тизер «лучшее из эфира»; аутро с QR. Приватность — ни одного ника, фамилии, вкладки, почты в кадре.

## Архитектура рендера: E (основная) и D (запасная)

**E — полный кадр в Remotion.** Композиция `Program` (`templates/remotion-program`) рисует весь кадр по EDL:
планы, окна источников с наездами, камеры, чат, опросы, караоке, скетчи, карточки. ffmpeg — только на входе
(4K → клипы, `render/ingest.py`) и выходе (склейка кусков, звук, одно кодирование NVENC). Выбрана после установки
владельца: только так живые скетчи и пометки живут в координатах слайда и едут вместе с наездами.

**D — GPU-компоновка** (NVDEC → `scale_cuda`/`overlay_cuda` → NVENC, 17,9–29,2 fps сборки на загруженной машине),
Remotion рисует только прозрачные слои PNG-последовательностью (не ProRes 4444: 64 Мбит/с и 100 с на склейку, G-R9).
Быстрее, но режет анимации в координатах слайда. Только если владелец сам выберет скорость ценой анимаций;
гочи пути D — G-F7…G-F9.

## Джоба: папка + job.json

Один эфир = одна папка на диске с местом (НЕ системный — там кончается место и сканирует Defender) + `job.json`
(`templates/job.example.json`). Каждый скрипт: `python <script> --job job.json …` (или `$WEBINAR_JOB`).
`scripts/webinar/job.py` отдаёт пути, ставит TEMP/TMP/TMPDIR в `<job>/tmp`, грузит ключи из `env_file` /
`$WEBINAR_ENV_FILE` (только имена переменных окружения: `DEEPGRAM_API_KEY`, `GOOGLE_API_KEY`; `GEMINI_API_KEY`
снимается перед `from google import genai`), даёт `run_low()` (BELOW_NORMAL на Windows, `nice` на POSIX).

```
<job>/
  job.json
  audio/  proxy/  align/  transcript/  vision/  chat/  style/  edl/  remotion/  render/  final/  materials/  tmp/
  timeline.json                  мастер-таймлайн (S2) - контракт для всех следующих стадий
```

Данные джобы (правятся руками, живут рядом с результатами): `align/align_config.json` (куски диктофона, окна стыков),
`align/timeline_config.json` (сегменты эфира с пометками main/optional/skip, визуальные подсказки интро),
`transcript/corrections.json` (+ `recorder_corrections.json`), `vision/vision_overrides.json` (ручные слайды,
перелистывания, разрешения по чувствительному), `chat/chat_labels.json` (виды сообщений, опросы), `edl/edl_config.json`
(всё, что было константами сборщика EDL). Схемы — в docstring каждого скрипта.

**Каждая стадия пишет результат на диск и пропускает готовое** (skip-if-done, `.part` + rename): обрыв сессии стоит
минуты, а не часы. Всё тяжёлое — BELOW_NORMAL (кроме сведения звука под рендером, G-A8).

## Стадии

### S0–S1. Источники, прокси, чанки для зрения

| Шаг | Команда | Что даёт |
|---|---|---|
| прокси + WAV | `sources/proxies.py --job j [wav] [proxy]` | `proxy/<part>.mp4` 1920×1080 25 fps NVENC cq20 g50 `scale_cuda`, `audio/<id>_16k.wav`; идемпотентно по длительности; фоном, BELOW_NORMAL |
| чанки для зрения | `sources/vision_chunks.py --job j [parallel=4] [--chunk-s 800]` | один GPU-декод чанка 4K даёт сразу: 960×540 @2 fps с чёрной полосой 36 px и **таймкодом источника, впечатанным в кадр** (G-V1), кадры 1280×720 каждые 2 с, моно-WAV, `silencedetect` |

### S2. Выравнивание по эталонной дорожке (диктофон)

Эталон времени — непрерывная запись диктофона (в данных она называется `plaud`, каким бы устройством ни писали);
части Zoom встают на неё.

| Шаг | Команда | Что делает |
|---|---|---|
| грубый сдвиг | `align/xcorr.py --job j` | огибающие лог-энергии 100 fps в полосе речи → FFT-xcorr; качество = пик/фон (эталон 8,3 и 13,1); пик на краю окна — расширить (G-A6) |
| плотная карта | `align/dense.py --job j <part> auto` | GCC-PHAT, окно 10 с шаг 10 с ±6 с вокруг грубого сдвига → `dense_<part>.json` |
| карта сдвигов | `align/offmap.py` (модуль) | надёжные точки (ratio > 1,5, sharp > 15, бегущая медиана 5, выброс > 0,15 с) → кусочно-линейная `offset(t)`; сдвиги СТУПЕНЧАТЫЕ (провалы сети Zoom), не дрейф (G-A5) |
| стыки | `align/junction.py --job j` | окно 1,5 с шаг 0,25 с на концах частей: первый/последний годный сэмпл, разрыв между частями (эталон 8,51 с, есть только на диктофоне) |
| проверка «на слух» | `align/dg_slices.py`, `align/verify_listen.py --job j` | независимые расшифровки Deepgram диктофона и Zoom в 6 окнах, слова Zoom переносятся картой → совпало 90–99 % слов, медиана 0,001–0,031 с, MAD ≤ 0,045 с |
| часы чата | `align/chat_anchors.py --job j` | ведущий читает сообщения вслух: токены ≥ 5 букв ищутся в расшифровке → границы `C = часы чата − часы диктофона`; эталон C = 23…24,5 ± 1,0 с (G-C2) |
| тембр | `align/audio_match.py --job j` | долгосрочный спектр диктофона vs Zoom на одном отрезке → 1/3-октавная кривая (клип ±3 дБ, 125 Гц–6,3 кГц) |
| чистка кусков диктофона | `align/process_recorder.py --job j` | highpass 85 → firequalizer по кривой → afftdn → статичное усиление → компрессор → alimiter; **пре-ролл 1 с + замер задержки GCC + обрезка по сэмплу** (G-A1); −16 LUFS статичным усилением (G-A2) |
| слова диктофона | `align/dg_pieces.py`, `align/build_recorder_words.py`, `align/relisten_pieces.py` | Deepgram по ОЧИЩЕННЫМ кускам (тем, что пойдут в монтаж) + правки + Gemini-переслушивание спорных мест |
| мастер-таймлайн | `align/build_timeline.py --job j` → `timeline.json` | сегменты в порядке эфира (`recommended`, `kind main/optional/skip`, `src_in/out`, `plaud_in/out`, `wall_msk`), узлы сдвигов, громкость частей, визуальные подсказки интро; схема — `how_to_read` внутри файла |

Точки резов — по тишине (`silencedetect` + энергия 20 мс), вручную только утверждение.

### S3. Расшифровка

`transcript/dg_transcribe.py --job j` — REST `/v1/listen` nova-3 ru, diarize, keyterms (`transcript.keyterms`); два
прохода: `smart_format` и «plain» без цифр — из второго малые числа прописью (G-T6). `transcript/corrections.json`:
`speaker_names`, `speaker_overrides`, `global [{from,to}]`, `anchored [{part,t,from,to,why}]` ±25 с — каждая правка
с доказательством (телесуфлёр/сценарий, чат, переслушивание). `transcript/gemini_relisten.py` — спорные места.
`transcript/build_outputs.py` — сборка слов, правки, склейка утверждений спикера в абзацы (пауза ≤ 2,5 с, G-T4),
**`tighten()`** (G-T1), журнал `corrections_applied.json`; правка, не нашедшая место, — падение, а не пропуск.
`transcript/whisper_crosscheck.py` — faster-whisper large-v3 для имён, которые Deepgram глотает (G-T3).
Эталон: 5 369 слов / 81 абзац и 11 384 / 140; 51 global + 54 anchored правок, 0 несработавших; 769 концов слов
подрезано, 0 перекрытий, 0 немонотонных.

### S4. Зрение (Gemini)

| Шаг | Команда | Выход |
|---|---|---|
| смысл по чанкам | `vision/gemini_video.py --job j [--chunk-s 800]` | `raw_v2/<chunk>.json`: сегменты с битами, энергия, хайлайты, проблемы, чувствительное; thinking HIGH, media_resolution HIGH |
| плотный проход кадров | `vision/gemini_frames.py --job j` | кадры каждые 2 с, дедуп в «визуальные состояния» (эталон 226 и 441), батчи → раскладка, номер слайда, плитка камеры, лицо — ИСТИНА по раскладке (G-V2) |
| покадровые границы | `vision/refine_bounds.py --job j` (+`vision/runs.py`) | граница 2-с сетки → кадр 1/25 с по максимуму разности в 4K-декоде 128×72; `fix_monotonic` против быстрых перелистываний (G-V4) |
| чувствительное | `vision/sensitive_pass.py --job j` | отдельный узкий промпт по КАЖДОМУ 2-с кадру: вкладки, адресная строка, @ники, уведомления, имена в ленте (G-V3) |
| плитки | `vision/tiles.py --job j` | детерминированно, без модели: какие слоты ленты Zoom несут живую камеру (`zoom.strip`) |
| сборка | `vision/build_scenes.py --job j` → `vision/scenes.json` | границы — из прохода кадров, смысл — из видеопрохода с варпом по якорям слайдов; ручные вставки из `vision_overrides.json` |

Схема «смысл — от видео, время — от кадров и расшифровки». Эталон: 90 сегментов, 25 хайлайтов (все привязаны к
словам или кадрам), 15 проблем, 27 чувствительных (11 требуют действия).

### S5. Чат, реакции, опросы

`chat/parse_zoom_chat.py` — оба лога Zoom (сохранённый чат `От X кому Y:` и лог клиента `HH:MM:SS\t От X : ` с
реакциями EN/RU и снятиями) → единый список в порядке прихода (G-C1, G-C3). `chat/label_chat.py` — черновик
`chat_labels.json` моделью (вопрос / опрос / благодарность / скрыть) + детерминированный поиск всплесков коротких
ответов после вопроса ведущего; правится руками. `chat/build_chat.py` → `chat_display.json` (приватность: регэкспы
URL/почта/телефон, «Участник» вместо ника/фамилии; сглаживание штампов). `chat/build_stats.py` → `chat_stats.json`
(опросы, викторина, итоговая оценка, уникальные авторы, вопросы). Реакции в кадре записи Zoom НЕ видны — только лог
(G-C5). Эталон: 458 сообщений, 401 показано, 39 выделено, 0 почт/телефонов/ссылок.

### S6. Система стиля

`style/style.md` (правила, 17 разделов) + `style/tokens.json` (все числа; из него читают и Remotion, и сборщик EDL) —
образцы `templates/remotion-program/style/{style.example.md, tokens.example.json}`. Если текст и токены
расходятся — прав `tokens.json`. Бренд, люди (`lower_third.people`, две строки роли), тексты интро/аутро, QR — поля
токенов; ассеты бренда — `remotion/public_lite/brand/`, QR — `deliver/make_qr.py` (с проверкой декодером).

Грамматика планов: studio / face / face_xl / board / full / studio_tile / full_tile / speaker / speaker_wide /
audio_only / intro_hidden. Морф 15 кадров easeInOutCubic без отскока (face — 16), пружина только у мелочи; караоке
с плашкой (несказанное 42 %, слово загорается за 3 кадра, плашка растёт за 5); карточки глав 3,6 с; плашки имён;
интро ≈ 23 с; аутро 16 с; музыка только под интро/главами/аутро; −16 LUFS / −1,5 dBTP.

### S7. Слайды и ролики деки

| Шаг | Команда | Что |
|---|---|---|
| рендер PDF + арты | `slides/prep_slides.py --job j render` | `public/full/slides/NNN.png` 1920 px (PyMuPDF), чистые арты `full/art/NNN.png` (`deck.art_map` или `deck.merged` exec-sketch) |
| окна показа | `slides/prep_slides.py --job j jobs` | показанные слайды из `scenes.json` (+ `slides.extra_windows` для кусков без видео) + расшифровка этих окон, метка времени каждые 8 слов → `edl/boxes_jobs.json` |
| разметка Gemini | `slides/prep_slides.py --job j boxes` (`slides/gemini_boxes.py` — один слайд) | `edl/boxes/boxes_NNN.json`: 3–9 смысловых элементов с рамками в порядке чтения, слова-якоря 1–4 дословно, пометка (circle/underline/check/arrow/pulse ≤ 3 на слайд) с рамкой, `margin_note`, `key_phrase` (≤ 60 знаков, НЕ написанная на слайде), `empty_corners` |
| штрихи живого скетча | `slides/sketch_slide.py --job j all` | движок `sketch-course-video/scripts/trace.py` (`trace_paths`, `order_strokes`, `color_paths`); маски чернил/акцента/серых заливок для тёмной и бумажной темы; «остальное» отдельным элементом → `full/sketch/NNN.json`; текстовые элементы слева направо (G-S1) |
| синхрон роликов со звуком | `slides/vsync_audio.py --job j` | xcorr звука ролика деки и записи, две пробы → `edl/vsync.json` |
| синхрон немых роликов | `slides/vsync_motion.py --job j` | xcorr энергии движения 10 fps в прямоугольнике ролика → `edl/vsync_vis.json`; слабые (< 0,4) — старт по началу слайда |

Прямоугольники роликов на слайде — из pptx (`manus-slides/scripts/pptx_video_rects.py`, G-P2).

### S8. Четыре обработки слайда

Правило выбора: перечисление по пунктам → **(b) живой скетч**; «вот здесь», цифра, вывод → **(c) пометки**; образ,
метафора, связь → **(d) board с дудлами**; демо и рассказ без опоры на слайд → **(a) чистый слайд** с дрейфом и лицом.
Живое демо не перерисовывается и схемой не подменяется. Размытую трансляцию слайда из Zoom в монтаж не берём.

- **(a) чистый слайд** — `Feed.drift` 0,015–0,03 за 10 с, направление чередуется; итоговый дрейф ≤ 4,5 % (G-S4, G-E2).
- **(b) живой скетч** — `Feed.kind='sketch'`, `SketchSpec{data, beats{id→кадр слова ±2}, durs, pen[≤2], settle}`;
  `SketchReveal.tsx`: SVG-маска `strokeDashoffset` открывает ОРИГИНАЛЬНЫЙ растр; ручка паркуется и гаснет за 4–5 кадров
  (G-S7); кроссфейд 8 кадров в чистый слайд. Удары — на словах-якорях, если их мало (< трети элементов) — спокойный
  темп ×1,4. Первый элемент — не позже from+50 кадров (G-E5). Только на ПЕРВОМ длинном (≥ 10 с) показе слайда из
  `sketch_slides`, не два скетча подряд.
- **(c) пометки внутри слайда** — `Mark{circle|underline|check|arrow|box|pulse|spotlight|strike}` в координатах
  слайда, едут с наездами (`Feed.moves`); рукописные пути `program/hand.ts` (seeded `random()` — одинаково в каждом
  куске). Наезд на мелкую обведённую деталь: 24 кадра вход, медленный подъезд 110, выход 30; рамка растёт, пока не
  перестанет резать элементы (G-S3), не больше 30 наездов на ролик.
- **(d) вокруг слайда** — план `board`, `Doodle{arrow|label|stat|stars|bracket|circle_stage}`, конец стрелки в
  координатах слайда (`to_content`), маршрут по пустому полю (G-S2), подпись — только сказанное/написанное
  (`margin_note` или своя в `edl_config.board`).

### S9. Композиция Program (архитектура E)

`templates/remotion-program/`: `src/program/types.ts` — **контракт EDL** (читать первым), `Program.tsx`,
`FeedView.tsx` (наезды, дрейф, пометки, размытие приватного, приглушение вшитой плитки), `SketchReveal.tsx`
(+ `SketchArt` для карточек глав), `Overlays.tsx` (PollCard, Reactions, Doodles, HeroCallout, WinnerBanner, Confetti,
Pill), `Captions2.tsx`, `hand.ts`, `icons.tsx`, `Vid.tsx` (клипы — `@remotion/media`, ролики деки — `OffthreadVideo`,
G-R10); `src/components/{Layout,Chat,LowerThird,ChapterCard,Intro,Outro,Stage,Frame,Sketch}.tsx`; `src/fonts.tsx`
(`delayRender` до загрузки всех шрифтов, G-R8); `src/tokens.ts` импортирует `style/tokens.json` (запекается в бандл,
G-R2). Remotion 4.0.526, React 19.2.3. Справка по API Remotion — плагин remotion (`remotion:*`).

### S10. EDL: сборка, проверка, нарезка

`python scripts/webinar/edl/build.py --job j` → `edl/edl.json` (+ `chapters.json`, `subtitles.srt`,
`audio_plan.json`, `owner_review.json`, `report_build.json`, `final_duration.txt`). Вход: `timeline.json`,
`scenes.json`, чат, `boxes/`, `full/sketch/`, `vsync*.json`, `style/tokens.json`, **`edl/edl_config.json`**
(`templates/edl_config.example.json`). Модули `edl/build_edl/`:

| Модуль | Что делает |
|---|---|
| `clock.py` | куски источников в порядке эфира (`ranges`), вырезы `cuts` (тишина между словами с запасом 0,45 с / заминка по регэкспам слов / абсолютные), точки карточек глав (`best_gap`: самая большая пауза речи в окне −5…+0,6 с до смены слайда), `Clock` (время источника → кадр выхода; время внутри выреза прижимается к следующему кадру), состояние экрана по источнику (`screen_runs` + `screen_fixups`, `black_to_slide`), смена слайда подтягивается на карточку |
| `captions.py` | слова → реплики (≤ 2 строк по `captions.max_chars_per_line`, балансировка строк, 0,9–5,6 с, разрыв на паузе > 8 кадров, конце предложения после 24 знаков, смене спикера, вырезе, карточке), плашка ключевого слова на ~35–40 % реплик (`pill_keyterms`, стоп-слова), `drop_words` — фамилии частных лиц вон |
| `feeds.py` | окна: слайд / скетч / ролики деки (время ролика идёт по часам выхода, петли) / окна Zoom (`zoom_feeds`: демо, барабан с размытием вкладок, камера-шара); продление окна под карточку +14 кадров; удары скетча, пометки, наезды; board; цитаты-акценты ≥ 200 с друг от друга и только если фразы нет на слайде |
| `events.py` | хайлайты → face / face_xl (`face_xl_highlights`); сцены-события (`events`: розыгрыш — баннеры победителей, конфетти, звёзды, наезд на барабан, круг на строке победителя, ритм studio↔full не чаще 8 с); плашки имён на face_xl (`plates`) |
| `layouts.py` | ключи планов: база + акценты (60 кадров между акцентами, 30 от карточек), острова < `min_hold_s` (3 с) — в соседа; камеры по спикеру (шаг 1 с, прогоны < 2,5 с — в предыдущий; вторая камера только где жива — `cam2.clips.live`), разрезаются на каждом шве и карточке |
| `chat.py` | порядок прихода + медиана 7 штампов + бегущий максимум; часы чата → часы диктофона → источник → кадр; голоса опросов → чипы голосов; реакции → значок на пузыре + летящие иконки; пузыри не выпрыгивают под карточкой (G-S10); высоты пузырей меряются реальными шрифтами (PIL); тизер берёт РЕАЛЬНЫЙ чат тех минут |
| `polls.py` | карточки опросов (открытие на реплике ведущего, ≤ 20 с до первого голоса, держится 4 с после последнего, без перекрытий), викторина со счётчиком по каждому ролику, итоговая оценка досчитывающейся цифрой |
| `assemble.py` | тизер на своих часах (3 куска + 22 кадра), карточки, главы с артом (`art_slide`, `art_ids`), интро-арт, теги, флаги владельцу (правила и слова-сигналы), сборка EDL, **пост-проходы `fill_sketch_gaps` (G-E5) и `sync_cams` (G-E6)**, `audio_plan.json` (голос кусками + музыка под тизером, каждой карточкой и аутро), SRT, `owner_review.json` (ничего не применено — только таймкоды для решения) |

Затем:
- `edl/validate_edl.py --job j` — **внешняя** проверка готового EDL (не перечитывание сборщика): покрытие без дыр
  и нахлёстов, ключи планов, файлы, диапазоны источников, камеры, реплики, приватность чата, фамилии из `drop_words`,
  окна с полосой вкладок (`validate.tabbar_windows`), опросы, главы, **синхрон камеры с голосом** и **пустой холст
  скетча** → `report_validate.json`, `timeline_readable.txt`; код выхода 1 при ошибках.
- `edl/split_chunks.py --job j [7500]` — куски по 5 минут, каждый — самостоятельный EDL на своих часах: всё
  сдвигается на −c0 с сохранением относительного времени — активный и предыдущий ключ плана с отрицательными кадрами,
  окна и камеры с отрицательным `from`, последние 10 пузырей чата, опросы целиком, реплики с переиндексацией слов →
  пружины, дрейфы, морфы и скетчи продолжаются через шов без рывка (G-R7). Пишет `chunks/index.json` и
  `chunks/changes.jsonl` (когда менялся каждый кусок — для `render/provenance.py`).
- `edl/make_tests.py --job j name:from:to …` — тестовые вырезки той же функцией нарезки: рендерится ровно то, что даст
  полный рендер (интро, опрос, карточка + ролик, розыгрыш, аутро).

Проверено на эталоне: `build.py --raw` даёт `edl.json`, побайтно совпадающий с EDL исходного однофайлового сборщика
(md5 9f13760c); с пост-проходами — побайтно совпадающий с итоговым исправленным EDL (14 скетчей, 15 отрезков камер);
нарезка — 25 из 25 кусков совпадают; валидатор — 0 ошибок на итоговом EDL и 29 ошибок (камеры +91 кадр, пустые
холсты) на EDL до исправлений.

### S11. Рендер

1. **Вход** — `render/ingest.py --job j [--test]`: `h264_cuvid -crop t×b×l×r -resize` (кроп и масштаб в декодере GPU),
   матрица 601→709 на CPU ровно один раз (G-F6), `h264_nvenc -preset p5 -cq 18 -g 25 -bf 0`, теги bt709, 4 потока.
   Главный кадр — область демонстрации x < 3440 (лента с именами отрезана), 2560×1608 (запас под наезд); камеры — из
   4K-плитки в 640×360 с лёгким unsharp; вторая камера — только на отрезках, где она жива (`ingest.clips`). Замер: вход
   4K → 1600×900 90 fps, вырез камеры 115 fps. `--test` — 3 с каждого клипа.
2. **Бандл** — `node bundle_lite.mjs out/bundle_<тег>` (в проекте remotion): бандл из `public_lite` + hardlink'и
   клипов (2–3 с вместо минут и гигабайт, G-R1). После ЛЮБОЙ правки `tokens.json` или `src/**` — новый бандл с новым
   именем (G-R2). Пробы кадров — `node still_edl.mjs <bundle> <outDir> <edl.json>:<f1,f2,…>` (~2–8 с на кадр, один процесс);
   одиночные EDL (тесты) — `node render_program.mjs <bundle> <outDir> <conc> <edl.json> …`.
3. **Воркеры** — `pwsh render/start_workers.ps1 -Root <job> -Bundle <bundle> -Name X1 -Conc 7 -Order asc`
   (второй `desc`, третий `mid`; `-LockTag` — новый после правки EDL/бандла): один node-процесс, один браузер
   (`openBrowser`, `gl=angle`), `renderMedia` h264 crf 16 jpeg 94, `offthreadVideoCacheSizeInBytes` 2 ГБ; кусок
   захватывается lock-файлом `wx`, готовые пропускаются, ошибка — в `render_errors.log` и браузер пересоздаётся;
   `render_times.jsonl`. Замеры (Intel Ultra 9 185H 22 потока, RTX 4090 Laptop): 1 процесс c16 21–29 fps (кадр Zoom
   2560×1440 — 14 fps); 2 процесса c10 25,6–38,1 fps суммарно; 3 процесса c7 43,9 fps (слайды); 4 процесса c6 25,9 fps
   (хуже трёх). Полный рендер на общей машине — 3,98 fps на воркер (G-R6); на свободной — 3 × c7 по ~21 fps.
4. **Правки во время рендера** — поправили EDL → `build.py` → `validate_edl.py` → `split_chunks.py` (атомарно) →
   `render/provenance.py --job j [--withdraw]`: кусок годен, только если его рендер начался после последней правки
   его EDL и бандл новее токенов/кода; устаревшие mp4 уходят в `render/withdrawn/`, живые воркеры их перерендерят.
   Не убивать и не перезапускать чужие воркеры; новые — с новым `-LockTag`.
5. **Кодирование по ходу** — `render/encode_chunks.py --job j`: каждый готовый кусок → NVDEC → NVENC с ОДИНАКОВЫМИ
   параметрами (p7 hq, High, VBR 7M max 11M, multipass fullres, spatial+temporal AQ, g50 bf3, bt709 tv) → `render/enc/`;
   сайдкар размер+mtime делает устаревшие кодирования видимыми (переделываются сами). Кусок начинается с IDR, SPS/PPS
   общие → склейка `concat -c copy` без шва (проверено: 15 000 кадров, непрерывные pts, IDR на шве, чистое декодирование).
6. **Сборка** — `render/finalize.py --job j` (concat -c copy + `final/program_mix.wav` → AAC 192k, faststart, метаданные;
   отказывается, если хоть один кусок устарел, длина микса ≠ длине EDL ± 0,05 с или итоговых кадров не столько же, сколько
   в EDL; под lock-файлом). Запасной путь без кодирования по ходу — `render/assemble.py` (одно NVENC по склейке).

### S12. Звук

`audio/mix_full.py --job j` по `edl/audio_plan.json`: голос — ОДНА цепочка concat с точными паузами в сэмплах (без
дрейфа), статичный подъём частей Zoom (G-A4), highpass 80 → компрессор −20 дБ 2,5:1 → фейды 20 мс на каждом шве;
музыка — две чередующиеся цепочки, одна −20 LUFS «одна», под голосом −10 дБ, рампы 0,35 с, вход 0,5 с, уход 1 с,
огибающая выражением `volume=…:eval=frame`; 3 потока в amix (G-A7); двухпроходный linear loudnorm (G-A2, G-A9).
Под рендером — обычный приоритет (G-A8). Подложка — своя (навык `ace-step`, seed в имени файла), проверка —
`qa/qa_music.py` (нет вокала, подъёмы трека ставятся на стыки карточек: `edl_config.music.cards`). Короткие вырезки —
`audio/mix_excerpt.py` (G-A3).

### S13. Контроль

| Проверка | Инструмент | Что ловит |
|---|---|---|
| валидатор EDL | `edl/validate_edl.py` | дыры, файлы, диапазоны, приватность чата, кропы, синхрон камер, пустые скетчи |
| кадры-пробы | `still_edl.mjs` | глазами — каждый новый элемент на реальном EDL |
| тестовые вырезки | `edl/make_tests.py` + `render_program.mjs` | интро, опрос, глава+ролик, розыгрыш, аутро — ровно то, что даст полный рендер |
| Gemini по кадрам | `qa/qa_frames.py <шаг> <mp4…>`, по ходу рендера — `qa/qa_watch.py` | переполнение, перекрытия, > 2 строк, пустые кадры, запасные шрифты, **приватность**, мыло |
| Gemini против эталона | `qa/qa_reference.py` | сравнение с роликом-эталоном владельца; ШУМНО (G-Q1) — только подтверждённое кадрами |
| покадрово | `qa/contact_sheet.py <mp4> <от> <до> --every 3` | проверка спорных пунктов (плавный морф vs «склейка», пустой холст, вспышка) |
| провенанс кусков | `render/provenance.py` | кусок из старого EDL / старого бандла |
| итоговый файл | `qa/verify_final.py` | кадры == EDL, кодек, громкость (R128), чёрные кадры, тишина > 2,5 с, **синхрон A/V в N точках против исходников** (звук xcorr + движение окна камеры против 4K-плитки) |
| громкость | `ebur128` в `mix_full.py` / `verify_final.py` | −16,0 ± 0,2 LUFS, TP ≤ −1,5 |

### S14. Выдача

Таймкарта итогового ролика → PDF саммари и транскрипта с таймкодами, текст RuTube с главами, обложка, PDF деки с
кликабельными роликами, сторис из хайлайтов, черновики публикаций — `webinar-deliverables.md`.

## Порядок запуска (сквозной)

```bash
J=--job ~/VideoJobs/<job>/job.json; W=<skill>/scripts/webinar
python $W/sources/proxies.py $J && python $W/sources/vision_chunks.py $J
python $W/align/xcorr.py $J && python $W/align/dense.py $J part1 auto && python $W/align/dense.py $J part2 auto
python $W/align/junction.py $J && python $W/align/dg_slices.py $J && python $W/align/verify_listen.py $J
python $W/align/audio_match.py $J && python $W/align/process_recorder.py $J && python $W/align/dg_pieces.py $J
python $W/align/build_recorder_words.py $J && python $W/align/build_timeline.py $J && python $W/align/chat_anchors.py $J
python $W/transcript/dg_transcribe.py $J && python $W/transcript/build_outputs.py $J      # + corrections.json, relisten, whisper
python $W/vision/gemini_video.py $J && python $W/vision/gemini_frames.py $J && python $W/vision/refine_bounds.py $J
python $W/vision/sensitive_pass.py $J && python $W/vision/tiles.py $J && python $W/vision/build_scenes.py $J
python $W/chat/parse_zoom_chat.py $J && python $W/chat/label_chat.py $J && python $W/chat/build_chat.py $J && python $W/chat/build_stats.py $J
python $W/slides/prep_slides.py $J all && python $W/slides/sketch_slide.py $J all
python $W/slides/vsync_audio.py $J && python $W/slides/vsync_motion.py $J
python $W/edl/build.py $J && python $W/edl/validate_edl.py $J && python $W/edl/split_chunks.py $J && python $W/edl/make_tests.py $J
python $W/render/ingest.py $J                      # затем в <job>/remotion: node bundle_lite.mjs out/bundle_v1
pwsh $W/render/start_workers.ps1 -Root <job> -Bundle <job>/remotion/out/bundle_v1 -Name X1 -Conc 7 -Order asc   # + X2 desc, X3 mid
python $W/audio/mix_full.py $J                     # параллельно рендеру, обычный приоритет
python $W/render/encode_chunks.py $J               # фоном, по мере готовности кусков
python $W/qa/qa_watch.py $J                         # фоном: Gemini по каждому куску
python $W/render/provenance.py $J && python $W/render/finalize.py $J && python $W/qa/verify_final.py $J
```

Между стадиями — глаза: кадры-пробы каждого нового элемента, контактные листы спорных мест, 4K-кадры для
чувствительного. «Модель сказала» — не проверка.
