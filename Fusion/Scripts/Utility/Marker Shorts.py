#!/usr/bin/env python3
"""Marker Shorts: render timeline markers as separate videos in DaVinci Resolve."""

import csv
import os
import re
import unicodedata
from datetime import datetime


APP_ID = "com.juantorralbo.resolve.marker-shorts.v4"
CURRENT_SETTINGS = "Configuración actual"
COLOR_OPTIONS = [
    ("Todos", None),
    ("Azul", "Blue"),
    ("Cian", "Cyan"),
    ("Verde", "Green"),
    ("Amarillo", "Yellow"),
    ("Rojo", "Red"),
    ("Rosa", "Pink"),
    ("Morado", "Purple"),
    ("Fucsia", "Fuchsia"),
    ("Rosa claro", "Rose"),
    ("Lavanda", "Lavender"),
    ("Celeste", "Sky"),
    ("Menta", "Mint"),
    ("Limón", "Lemon"),
    ("Arena", "Sand"),
    ("Cacao", "Cocoa"),
    ("Crema", "Cream"),
]


def safe_filename(value):
    value = unicodedata.normalize("NFC", str(value or ""))
    # Resolve's render queue rejects '?' in CustomName even on macOS, where the
    # filesystem itself would allow it. Keep punctuation such as ':' so names
    # still match their marker titles as closely as Resolve permits.
    forbidden = r'[\\/:*?"<>|\x00-\x1f]' if os.name == "nt" else r'[/?\x00-\x1f]'
    value = re.sub(forbidden, "-", value)
    value = re.sub(r"\s+", " ", value).strip(" .-")
    return value[:160] or "Short"


def collect_chapters(timeline, marker_color=None):
    start_frame = int(timeline.GetStartFrame())
    end_frame = int(timeline.GetEndFrame())
    markers = timeline.GetMarkers() or {}
    chapters = []

    selected = [
        (offset, marker)
        for offset, marker in sorted(markers.items(), key=lambda item: float(item[0]))
        if not marker_color or marker.get("color") == marker_color
    ]

    for index, (offset, marker) in enumerate(selected):
        duration = int(round(float(marker.get("duration") or 0)))
        mark_in = start_frame + int(round(float(offset)))

        # Resolve represents an ordinary point marker with duration 1. In that
        # case, treat it as a chapter start and end it immediately before the
        # next selected marker (or at the end of the timeline for the last one).
        if duration <= 1:
            if index + 1 < len(selected):
                next_offset = int(round(float(selected[index + 1][0])))
                mark_out = start_frame + next_offset - 1
            else:
                mark_out = end_frame - 1
        else:
            mark_out = mark_in + duration - 1

        mark_out = min(mark_out, end_frame - 1)
        if mark_out < mark_in:
            continue

        chapters.append({
            "offset": int(round(float(offset))),
            "mark_in": mark_in,
            "mark_out": mark_out,
            "duration": mark_out - mark_in + 1,
            "name": marker.get("name") or "Short",
            "color": marker.get("color") or "",
        })

    return chapters


def unique_names(chapters, add_index=True):
    counts = {}
    total = len(chapters)
    digits = max(2, len(str(total)))

    for index, chapter in enumerate(chapters, 1):
        base = safe_filename(chapter["name"])
        counts[base] = counts.get(base, 0) + 1
        if counts[base] > 1:
            base = f"{base} ({counts[base]})"
        chapter["filename"] = f"{index:0{digits}d} - {base}" if add_index else base
    return chapters


def format_duration(frames, fps):
    seconds = frames / fps if fps else 0
    minutes = int(seconds // 60)
    remaining = seconds - minutes * 60
    return f"{minutes}:{remaining:05.2f}"


def has_enabled_subtitles(timeline):
    try:
        track_count = int(timeline.GetTrackCount("subtitle") or 0)
    except Exception:
        return False

    for track_index in range(1, track_count + 1):
        try:
            enabled = timeline.GetIsTrackEnabled("subtitle", track_index)
            if enabled is False:
                continue
        except Exception:
            # Older Resolve versions may not expose GetIsTrackEnabled. In that
            # case, the presence of subtitle clips is the useful signal.
            pass
        try:
            if timeline.GetItemListInTrack("subtitle", track_index):
                return True
        except Exception:
            pass
    return False


def write_manifest(
    output_dir, timeline_name, preset_name, fps, chapters, burn_subtitles
):
    manifest = os.path.join(output_dir, "marker-shorts.csv")
    with open(manifest, "w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.writer(handle)
        writer.writerow([
            "timeline", "preset", "archivo", "marcador", "color",
            "entrada_frame", "salida_frame", "duracion_frames", "duracion_segundos",
            "subtitulos_incrustados",
        ])
        for chapter in chapters:
            writer.writerow([
                timeline_name,
                preset_name,
                chapter["filename"],
                chapter["name"],
                chapter["color"],
                chapter["mark_in"],
                chapter["mark_out"],
                chapter["duration"],
                f"{chapter['duration'] / fps:.3f}" if fps else "",
                "sí" if burn_subtitles else "no",
            ])
    return manifest


def current_context():
    project = resolve.GetProjectManager().GetCurrentProject()
    timeline = project.GetCurrentTimeline() if project else None
    return project, timeline


def timeline_fps(project):
    for key in ("timelineFrameRate", "timelinePlaybackFrameRate"):
        try:
            value = float(project.GetSetting(key) or 0)
            if value > 0:
                return value
        except (TypeError, ValueError):
            pass
    return 24.0


def selected_color():
    index = int(items["Color"].CurrentIndex)
    return COLOR_OPTIONS[index][1]


def refresh_preview(ev=None):
    project, timeline = current_context()
    if not project or not timeline:
        items["Preview"].PlainText = "No hay ningún proyecto o timeline activo."
        items["Status"].Text = "Abre una timeline y vuelve a analizar."
        return []

    chapters = unique_names(collect_chapters(timeline, selected_color()), False)
    fps = timeline_fps(project)
    subtitle_status = (
        "subtítulos listos" if has_enabled_subtitles(timeline)
        else "sin subtítulos activos"
    )
    lines = [
        f"Timeline: {timeline.GetName()} · {len(chapters)} shorts · {fps:g} fps",
        f"Estado: {subtitle_status}",
        "",
    ]
    if chapters:
        for chapter in chapters:
            lines.append(
                f"{chapter['filename']}  ·  {format_duration(chapter['duration'], fps)}"
            )
    else:
        lines.append("No hay marcadores para este filtro.")
    items["Preview"].PlainText = "\n".join(lines)
    items["Status"].Text = f"Listos para preparar: {len(chapters)}"
    return chapters


def choose_output(ev=None):
    current = items["OutputDir"].Text or os.path.expanduser("~/Movies")
    selected = fusion.RequestDir(current)
    if selected:
        items["OutputDir"].Text = str(selected)


def queue_and_render(ev=None):
    project, timeline = current_context()
    if not project or not timeline:
        items["Status"].Text = "Error: no hay ningún proyecto o timeline activo."
        return

    output_dir = os.path.abspath(os.path.expanduser(items["OutputDir"].Text.strip()))
    if not output_dir:
        items["Status"].Text = "Elige una carpeta de destino."
        return

    chapters = unique_names(collect_chapters(timeline, selected_color()), False)
    if not chapters:
        items["Status"].Text = "No hay marcadores para procesar."
        return
    burn_subtitles = bool(items["BurnSubtitles"].Checked)
    if burn_subtitles and not has_enabled_subtitles(timeline):
        items["Status"].Text = (
            "No hay una pista de subtítulos activa. Actívala o desmarca "
            "«Incrustar subtítulos»."
        )
        return

    if project.IsRenderingInProgress():
        items["Status"].Text = "Espera a que termine el render que está en curso."
        return

    try:
        os.makedirs(output_dir, exist_ok=True)
    except OSError as exc:
        items["Status"].Text = f"No se pudo crear la carpeta: {exc}"
        return

    preset_name = items["Preset"].CurrentText
    if preset_name != CURRENT_SETTINGS and not project.LoadRenderPreset(preset_name):
        items["Status"].Text = f"No se pudo cargar el preset «{preset_name}»."
        return
    if not project.SetCurrentRenderMode(1):
        items["Status"].Text = "No se pudo activar el modo de clip único."
        return

    job_ids = []
    items["Run"].Enabled = False
    try:
        for chapter in chapters:
            settings = {
                "SelectAllFrames": False,
                "MarkIn": chapter["mark_in"],
                "MarkOut": chapter["mark_out"],
                "TargetDir": output_dir,
                "CustomName": chapter["filename"],
                "ExportVideo": True,
                "ExportAudio": True,
                "ExportSubtitle": burn_subtitles,
            }
            if burn_subtitles:
                settings["SubtitleFormat"] = "BurnIn"
            if not project.SetRenderSettings(settings):
                raise RuntimeError(f"No se pudo configurar «{chapter['name']}»")
            job_id = project.AddRenderJob()
            if not job_id:
                raise RuntimeError(f"No se pudo añadir «{chapter['name']}» a la cola")
            job_ids.append(job_id)

        fps = timeline_fps(project)
        manifest = write_manifest(
            output_dir, timeline.GetName(), preset_name, fps, chapters,
            burn_subtitles,
        )

        if items["AutoStart"].Checked:
            resolve.OpenPage("deliver")
            started = project.StartRendering(job_ids, True)
            if not started:
                raise RuntimeError("La cola se creó, pero Resolve no pudo iniciar el render")
            items["Status"].Text = (
                f"Renderizando {len(job_ids)} shorts · Registro: {manifest}"
            )
        else:
            resolve.OpenPage("deliver")
            items["Status"].Text = (
                f"Añadidos {len(job_ids)} shorts a la cola · Registro: {manifest}"
            )
    except Exception as exc:
        for job_id in job_ids:
            try:
                project.DeleteRenderJob(job_id)
            except Exception:
                pass
        items["Status"].Text = f"Error: {exc}"
    finally:
        items["Run"].Enabled = True


def close_window(ev=None):
    dispatcher.ExitLoop()


ui = fusion.UIManager
dispatcher = bmd.UIDispatcher(ui)
existing = ui.FindWindow(APP_ID)
if existing:
    existing.Show()
    existing.Raise()
    raise SystemExit

project, timeline = current_context()
timeline_name = timeline.GetName() if timeline else "Sin timeline"
project_name = project.GetName() if project else "Sin proyecto"
default_output = os.path.join(
    os.path.expanduser("~/Movies/DaVinci Shorts"), safe_filename(project_name)
)
presets = [CURRENT_SETTINGS] + (project.GetRenderPresetList() if project else [])

window = dispatcher.AddWindow(
    {
        "ID": APP_ID,
        "Geometry": [180, 140, 720, 590],
        "WindowTitle": "Marker Shorts · Render por marcadores",
    },
    ui.VGroup({"Spacing": 10, "Margin": 14}, [
        ui.Label({
            "Text": "MARKER SHORTS",
            "Font": ui.Font({"PixelSize": 22, "Bold": True}),
            "Weight": 0,
        }),
        ui.Label({
            "Text": f"Proyecto: {project_name}    ·    Timeline: {timeline_name}",
            "Weight": 0,
        }),
        ui.HGroup({"Weight": 0, "Spacing": 8}, [
            ui.Label({"Text": "Carpeta", "Weight": 0.12}),
            ui.LineEdit({"ID": "OutputDir", "Text": default_output, "Weight": 0.72}),
            ui.Button({"ID": "Browse", "Text": "Elegir…", "Weight": 0.16}),
        ]),
        ui.HGroup({"Weight": 0, "Spacing": 8}, [
            ui.Label({"Text": "Preset", "Weight": 0.12}),
            ui.ComboBox({"ID": "Preset", "Weight": 0.43}),
            ui.Label({"Text": "Color", "Weight": 0.10}),
            ui.ComboBox({"ID": "Color", "Weight": 0.35}),
        ]),
        ui.HGroup({"Weight": 0, "Spacing": 16}, [
            ui.CheckBox({
                "ID": "AutoStart", "Text": "Iniciar render automáticamente", "Checked": True
            }),
            ui.CheckBox({
                "ID": "BurnSubtitles", "Text": "Incrustar subtítulos", "Checked": True
            }),
            ui.HGap(0, 1),
        ]),
        ui.TextEdit({
            "ID": "Preview",
            "ReadOnly": True,
            "AcceptRichText": False,
            "Font": ui.Font({"Family": "Menlo", "PixelSize": 12, "MonoSpaced": True}),
            "Weight": 1,
        }),
        ui.Label({"ID": "Status", "Text": "Analizando…", "Weight": 0}),
        ui.HGroup({"Weight": 0, "Spacing": 8}, [
            ui.Button({"ID": "Refresh", "Text": "Volver a analizar", "Weight": 0.30}),
            ui.HGap(0, 0.20),
            ui.Button({
                "ID": "Run", "Text": "CREAR SHORTS", "Weight": 0.50,
                "Font": ui.Font({"PixelSize": 14, "Bold": True}),
            }),
        ]),
    ]),
)

items = window.GetItems()
for preset in presets:
    items["Preset"].AddItem(str(preset))
for label, _ in COLOR_OPTIONS:
    items["Color"].AddItem(label)

# Universal defaults: preserve the project's current render configuration and
# include every marker regardless of its color. Users can still choose a preset
# or color explicitly when they need to.
items["Preset"].CurrentIndex = 0
items["Color"].CurrentIndex = 0

window.On[APP_ID].Close = close_window
window.On["Browse"].Clicked = choose_output
window.On["Refresh"].Clicked = refresh_preview
window.On["Run"].Clicked = queue_and_render
window.On["Color"].CurrentIndexChanged = refresh_preview
window.On["BurnSubtitles"].Clicked = refresh_preview

refresh_preview()
window.Show()
dispatcher.RunLoop()
window.Hide()
