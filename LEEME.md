# DaVinci Torralbo Pack

Recursos desarrollados por Juan Torralbo, en parte con ayuda de IA. Versión en desarrollo, preparada para DaVinci Resolve Studio 21.1 en macOS. Compartidos gratuitamente y con código abierto bajo licencia MIT; consulta LICENSE.txt. Las futuras mejoras y actualizaciones podrán incorporarse al pack.

## Contenido

- 10 títulos animados y 10 presets de texto para subtítulos, diseñados para 9:16 y 60 fps.
- 6 transiciones con desenfoque: Dissolve, Zoom, Bloom, Slide, Whip y Dip.
- 1 generador de subrayado permanente.
- Marker Shorts: prepara/exporta tramos de la timeline a partir de marcadores.
- YouTube a DaVinci: descarga y convierte vídeo/audio para importarlo a la biblioteca o al final de la timeline.
- Pegar imagen de internet: importa imágenes del portapapeles o de su URL a Resolve.
- FlowLyrics 0.4.0: busca letras, importa SRT y crea textos animados; incluye el código de su módulo opcional de alineación.
- 2 extras experimentales, conservados de la instalación original: ResaltadorAmarillo y Foto_Estilo_Torralbo.

Son 29 presets y 4 herramientas. El DRFX contiene los 27 presets principales; los dos extras se entregan aparte. Las fuentes tipográficas no están incluidas.

## Compatibilidad y validación

La recopilación procede de macOS con DaVinci Resolve Studio 21.1. La integridad del ZIP, la sintaxis Python y la copia del instalador se han comprobado. No se ha ejecutado una instalación completa en un segundo Mac ni un render de cada preset. No se garantiza compatibilidad con la edición Free, otras versiones o Windows.

Las plantillas de texto son gráficos Fusion editables; no transcriben audio por sí solas ni convierten una pista SRT automáticamente. Ajusta duración y animación si tu timeline no está a 60 fps. Si falta Helvetica Neue u Open Sans, selecciona otra fuente en el Inspector. FlowLyrics usa Montserrat de forma predeterminada.

## Instalación rápida de los presets

1. Descomprime el ZIP en una carpeta permanente.
2. Abre `Presets_Torralbo.drfx` y acepta la instalación en Resolve.
3. Reinicia Resolve si no aparecen. Encontrarás los recursos en Títulos, Transiciones y Generadores.

Alternativa manual: copia el contenido de `Fusion/Templates/Edit` en la carpeta `Fusion/Templates/Edit` de tu instalación. El DRFX y esta carpeta contienen los mismos 27 recursos: elige una de las dos vías.

## Instalar presets y scripts en macOS

Con Python 3 instalado, abre Terminal, escribe `python3 `, arrastra `Instalar_macOS.py` a la ventana y pulsa Intro. Cierra Resolve antes de instalar y vuelve a abrirlo después.

El instalador copia las carpetas Templates y Scripts a:

`~/Library/Application Support/Blackmagic Design/DaVinci Resolve/Fusion/`

Si un archivo diferente ya existe, conserva una copia de seguridad junto a él. No instala software externo ni toca proyectos. Puedes añadir `--dry-run` para ver qué se copiaría sin hacer cambios.

También puedes copiar las carpetas manualmente. Mantén `ResolveWebBridge` junto a los dos archivos Lua dentro de `Fusion/Scripts/Utility`. Abre los scripts en `Área de trabajo > Scripts > Utility`.

### Marker Shorts

Abre una timeline con marcadores. El script usa sus nombres para los archivos y permite filtrar por color y elegir la configuración de render. Los marcadores puntuales delimitan capítulos hasta el siguiente marcador; los de duración respetan su intervalo. Revisa la vista previa, carpeta de destino y subtítulos antes de crear la cola/exportar. La función inicia renders cuando la confirmas desde su ventana.

### Herramientas de importación (macOS)

Necesitan Python 3. La importación de YouTube necesita también `yt-dlp`, `ffmpeg` y `ffprobe`, instalados por separado. Si ya usas Homebrew: `brew install python yt-dlp ffmpeg`.

Para pegar imágenes, copia una imagen en el navegador o copia su URL directa y ejecuta el script. El helper `clipboard` incluido es para Apple Silicon. En Mac Intel, recompílalo a partir de `clipboard.swift` con las herramientas de desarrollo de Apple:

`xcrun swiftc clipboard.swift -o clipboard`

Ejecuta el comando dentro de la carpeta ResolveWebBridge instalada. Los medios se guardan en una carpeta que tú eliges: mantenla disponible mientras el proyecto los utilice.

## FlowLyrics (macOS / Studio)

1. Copia `Workflow_Integration/FlowLyrics.py` en:

   `/Library/Application Support/Blackmagic Design/DaVinci Resolve/Workflow Integration Plugins/`

   Finder puede pedir credenciales de administrador. El instalador principal no realiza esta operación.
2. Reinicia Resolve y abre `Área de trabajo > Integraciones de dinámicas de trabajo > FlowLyrics`.
3. Busca una letra o importa un SRT, revisa texto y tiempos, configura estilo y crea los bloques en la timeline.
4. Necesita `ffmpeg` para generar el soporte de vídeo; la búsqueda/descarga de audio de YouTube necesita también `yt-dlp`.

La alineación precisa con el audio es opcional: requiere un entorno Python adicional. Ejecuta `FlowLyrics_opcional/Preparar_alineacion.py` con Python 3.11–3.13 si deseas prepararlo. Este paso sí descarga librerías (stable-ts, Whisper y sus dependencias). El modelo large-v3 se descarga en el primer uso y puede ocupar varios GB; el cálculo en CPU puede tardar. Modelos, entornos virtuales, audios y cachés personales no se incluyen en el ZIP.

Si ya existe `~/Library/Application Support/FlowLyrics/alignment-env`, el asistente lo conserva. En ese caso copia solo `flowlyrics_align.py` a `~/Library/Application Support/FlowLyrics/` y utiliza tu entorno existente. Desmarca Alinear para trabajar con los tiempos disponibles sin preparar esa función.

## Extras experimentales

No se instalan automáticamente ni se incluyen en el DRFX. Son macros originales guardadas que no se han validado funcionalmente en otra composición. Úsalas como material de Fusion para revisar/adaptar; no como efectos listos para producción. Puedes arrastrarlas al área de nodos de una composición de prueba.

## Recursos de otros autores

El inventario recoge los demás complementos detectados. Snap Captions, IG Master Text Animation y las 13 animaciones identificadas como VortyX no se redistribuyen en este pack. Su ausencia no indica que se hayan desinstalado: siguen intactos en el equipo de origen. Descárgalos de sus autores y conserva su licencia.

- Snap Captions: https://orsonlord.com/help/snap-captions
- IG Master Text Animation: https://isaiahgrade-shop.fourthwall.com/en-eur/products/ig-master-text-animation-project-file
- VortyX: origen de descarga no confirmado; no se proporciona un enlace de otro autor por aproximación.

## Uso

Pack gratuito y de código abierto bajo licencia MIT, disponible para utilizar, estudiar, modificar y redistribuir respetando el aviso de autoría y la licencia incluidos. Utiliza tus propias fuentes y medios con los permisos correspondientes. Las letras consultadas a LRCLIB y los recursos de YouTube mantienen los derechos de sus autores; el pack no incorpora música, letras ni material de clientes.

## Desinstalación

Elimina únicamente los archivos de este pack de las carpetas donde los copiaste. Consulta `Inventario.md` y `Archivos_SHA256.json` para identificarlos. Si el instalador guardó una copia `.backup-…`, puedes restaurarla. No borres carpetas de otros plugins.
