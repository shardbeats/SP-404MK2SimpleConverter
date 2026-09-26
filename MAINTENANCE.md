# Guía de mantenimiento — SP-404 MK2 Simple Converter

Guía práctica para mantener esta aplicación funcionando durante años.
Idioma del documento: español (el código y la UI están en inglés).

## 1. Mapa del proyecto (qué toca qué)

```
sp404_converter/
├── main.py            Entrada. Llama a gui.main().
├── gui.py             Ventana PySide6 + drag&drop + agrupación de la cola por carpeta.
├── converter.py       TODO lo que habla con FFmpeg:
│                      │  - ffmpeg_bin()/ffprobe_bin() (bundled vía sys._MEIPASS o PATH)
│                      │  - get_audio_info() (metadata vía ffprobe)
│                      │  - is_compatible_format()/needs_conversion() (reglas SP-404)
│                      │  - compute_output_path() (rutas + sufijo _sp.wav)
│                      │  - convert_file() (copia si compatible, convierte si no)
│                      │  - find_audio_files() (descubrimiento por extensiones)
├── styles.qss         Tema oscuro (se edita sin tocar código).
├── build_exe.py       Receta del portable (PyInstaller one-file + FFmpeg bundled).
├── SP404Converter.spec  Generado por el build (ignorado por git).
├── setup.py           Instalación pip (comando `sp404-converter`).
├── start.bat          Setup + arranque en un clic (crea .venv, instala, lanza).
├── legacy/            UI antigua (referencia; no se mantiene).
└── requirements.txt   Dependencias de runtime.
```

**Regla de oro:** la GUI (`gui.py`) nunca invoca a FFmpeg directamente;
siempre a través de las funciones de `converter.py`. Si respetas eso,
los cambios no se rompen entre sí.

## 2. Calendario de mantenimiento sugerido

| Cuándo | Tarea | Dónde mirar |
|---|---|---|
| Cada 6–12 meses | Actualizar dependencias (`pip install -U ...`, ver §3) | `requirements.txt` |
| Cada 12 meses | Probar con el FFmpeg estable más reciente | https://ffmpeg.org/download.html |
| Cada 12 meses | Revisar que los specs SP-404 no hayan cambiado (Roland) | Manual del SP-404 MK2 |
| Tras cada cambio | Correr la suite (`python -m pytest tests -q`) | `tests/` + CI en `.github/workflows/` |
| Tras cada cambio | Recompilar el exe y probarlo en una carpeta limpia | `build_exe.py` |
| Siempre | Nunca commitear `.venv/`, `build/`, `dist/`, `*.log`, `*.db` | `.gitignore` ya los cubre |

## 3. Actualizar dependencias sin romper nada

1. Crea un venv de prueba y anota lo instalado: `pip freeze > antes.txt`
2. Actualiza por grupos (nunca todo a la vez): primero `PySide6`, luego `ffmpeg-python`, luego el resto.
3. Tras cada grupo: corre los tests y prueba la app (arrastrar carpeta → convertir 1 archivo compatible y 1 no compatible).
4. Si algo falla: vuelve a `requirements.txt` y fija el tope del rango.
5. Solo entonces actualiza los rangos en `requirements.txt`.

**Puntos históricamente sensibles:**
- **PySide6 6.x → 7.x (cuando salga):** revisar drag&drop y señales de la GUI.
- **Python:** el README pide 3.10+. Antes de subir de versión menor,
  recompila el exe: PyInstaller es sensible a la versión.

## 4. FFmpeg (lo que más se rompe con los años)

- Todo el acoplamiento está en `converter.py`. Si ffprobe cambia el formato
  de `streams` o ffmpeg renombra un filtro, solo se toca ese archivo.
- **Lección aprendida (2026):** ffprobe reporta los WAV de 24-bit con
  `sample_fmt: s32` (decodifica a contenedor de 32-bit). Por eso
  `get_audio_info()` prefiere `bits_per_sample` cuando existe, con fallback
  al heurístico de `sample_fmt`. Si tocas esa función, el test
  `test_compatible_24bit_file_is_copied_not_reencoded` te avisa si regresa
  el bug (los 24-bit volverían a convertirse en vez de copiarse).
- La app empaqueta FFmpeg **dentro** del exe (decisión consciente:
  portabilidad total a cambio de ~100 MB). El `build_exe.py` avisa si no
  encuentra los binarios en el PATH y el exe sale **no portable**.

## 5. Recompilar el portable

```powershell
python build_exe.py   # compila dist\SP404Converter.exe
```

- Requiere FFmpeg en el PATH (el build lo localiza con `shutil.which`).
- `icon.ico` se detecta solo; sin él, el exe usa el icono por defecto.
- Verificación rápida: arrastrar una carpeta con 1 WAV compatible
  (debe copiarse) y 1 MP3 (debe convertirse a `*_sp.wav`).

## 6. Checklist de release

1. `git status` limpio de artefactos (`build/`, `dist/`, `.venv/`, `*.log`).
2. `python -m pytest tests -q` en verde (y CI verde en GitHub).
3. README al día (formatos soportados = `find_audio_files` + `SP404_SPEC`).
4. Probar el exe en PC/carpeta limpio: compatible→copia, MP3→convierte,
   estructura preservada con y sin carpeta de salida.
5. Subir el exe a GitHub Releases (nunca commiteado: `dist/` está ignorado).

## 7. Comportamientos decididos (no son bugs)

- **Compatible = copia, no conversión.** Si ya cumple el spec SP-404
  (rate en la lista, 16/24-bit, mono o estéreo, PCM), se copia byte a byte.
- **El sufijo es `_sp.wav`** y los archivos que ya lo llevan se saltan:
  una carpeta espejo nunca se reconvierte.
- **MP3 de entrada → WAV de salida.** Los formatos con pérdida se
  decodifican a PCM para no acumular una segunda generación con pérdida.
- **Sin estado local.** La app no guarda ajustes ni historial; no hay nada
  que migrar ni respaldar más allá del código (GitHub).

## 8. Tests

```
pip install -r requirements-dev.txt
python -m pytest tests -q
```

41 tests: tabla de spec, binarios, estructura del comando ffmpeg, metadata
ffprobe, detección de compatibilidad por regla, rutas de salida,
descubrimiento de archivos y conversión end-to-end con tonos generados
al vuelo (sin fixtures de audio en el repo). Los tests de integración
se saltan solos si no hay FFmpeg en el PATH. La GUI no se testea
(verificación manual con el checklist del punto 6).
