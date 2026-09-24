# public_lite — что куда класть

`public_lite/` — лёгкая публичная папка, из которой делается бандл (`node bundle_lite.mjs out/bundle`).
Тяжёлое (клипы, ролики деки) лежит в `public/` и попадает в бандл hardlink'ами, не копией (гоча G-R1).
Все пути в EDL и токенах — относительно корня public (`staticFile('full/slides/004.png')`).

| Папка | Что | Откуда |
|---|---|---|
| `fonts/` | `Manrope-var.ttf` (UI, 200–800), `Caveat-var.ttf` (ПОЛНЫЙ рукописный, 753 глифа: латиница+кириллица+цифры), `JetBrainsMono-Medium.ttf`, `JetBrainsMono-Bold.ttf` | OFL; список грузит `src/fonts.tsx` и держит кадр `delayRender`, пока все не загрузятся (G-R8). Проверять сигнатуру файла (`00 01 00 00` / `OTTO`), а не имя: «шрифты» в пользовательской папке Windows бывают сохранёнными HTML-страницами (G-F1) |
| `brand/` | логотип на тёмном (`tokens.brand.logo`), QR-коды аутро (`tokens.outro.qr_main`, `qr_small`), `stage.png` при желании | свой бренд; QR генерировать из URL (`scripts/webinar/deliver/make_qr.py`) и проверять декодером |
| `full/slides/NNN.png` | чистые слайды 1920×1080 из PDF деки | `scripts/webinar/slides/prep_slides.py` |
| `full/art/NNN.png` | чистые арты деки (растры, которые открывает живой скетч) | папка артов деки + `deck.art_map` |
| `full/sketch/NNN.json` | штрихи живого скетча по элементам слайда | `scripts/webinar/slides/sketch_slide.py` (движок `sketch-course-video/scripts/trace.py`) |

В `public/` (НЕ в public_lite, в бандл — hardlink'ами):

| Папка | Что | Откуда |
|---|---|---|
| `full/clips/` | `<part>_main.mp4` (область демонстрации 2560×1608/1440, bt709), `<part>_cam.mp4`, `<part>_cam2.mp4` (камеры 640×360) | `scripts/webinar/render/ingest.py` (NVDEC → NVENC, GOP 25, без B-кадров — так их читает `@remotion/media`) |
| `full/video/` | чистые ролики деки (заменяют дёрганое воспроизведение через Zoom) | из pptx / папки деки; синхронизация — `slides/vsync_audio.py`, `vsync_motion.py` |

`src/program/Vid.tsx`: клипы из `/full/clips/` идут через `@remotion/media` `<Video>` (в 2 раза быстрее
`OffthreadVideo` на загруженной машине), ролики деки — через `OffthreadVideo` (чужие кодировки, один повесил WebCodecs).
