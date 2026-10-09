-- Resolve Web Bridge: persistent local media, no external scripting permission required.
local function quote(s) return "'" .. s:gsub("'", "'\"'\"'") .. "'" end
local function alert(message)
    local escaped = message:gsub("\\", "\\\\"):gsub('"', '\\"'):gsub("\n", " ")
    os.execute('/usr/bin/osascript -e ' .. quote('display alert "DaVinci Web Bridge" message "' .. escaped .. '"'))
end
local app = resolve
if not app and bmd then app = bmd.scriptapp('Resolve') end
if not app then alert('No se puede conectar con DaVinci Resolve.'); return end
local project = app:GetProjectManager():GetCurrentProject()
if not project then alert('Abre un proyecto antes de importar.'); return end
local timeline = project:GetCurrentTimeline()
local projectId = project:GetUniqueId()
local timelineId = timeline and timeline:GetUniqueId() or nil
local result = os.tmpname()
local script_source = debug.getinfo(1, "S").source
if script_source:sub(1, 1) == "@" then script_source = script_source:sub(2) end
local script_directory = script_source:match("^(.*)/[^/]+$")
if not script_directory then alert('No se pudo localizar el script. Copia también la carpeta ResolveWebBridge junto al archivo Lua.'); return end
local helper_path = script_directory .. '/ResolveWebBridge/bridge.py'
local candidates = {'/opt/homebrew/bin/python3', '/usr/local/bin/python3', '/Library/Frameworks/Python.framework/Versions/3.13/bin/python3', '/Library/Frameworks/Python.framework/Versions/3.12/bin/python3', '/Library/Frameworks/Python.framework/Versions/3.11/bin/python3', '/usr/bin/python3'}
local python_path = nil
for _, candidate in ipairs(candidates) do
    local probe = io.open(candidate, 'rb')
    if probe then probe:close(); python_path = candidate; break end
end
if not python_path then alert('Instala Python 3 y vuelve a abrir Resolve.'); return end
os.execute(quote(python_path) .. ' ' .. quote(helper_path) .. ' image ' .. quote(result))
local file = io.open(result, 'r')
if not file then alert('El asistente no arrancó. Comprueba la instalación de Python.'); return end
local status = file:read('*l')
local path = file:read('*l')
local destination = file:read('*l')
file:close(); os.remove(result)
if status == 'CANCEL' then return end
if status ~= 'OK' then alert(path or 'Error desconocido.'); return end
local current = app:GetProjectManager():GetCurrentProject()
if not current or current:GetUniqueId() ~= projectId then
    alert('Has cambiado de proyecto. El archivo se conserva en: ' .. path); return
end
local pool = current:GetMediaPool()
local clips = pool:ImportMedia({path})
if not clips or #clips == 0 then
    alert('Resolve no admite este formato/códec. Se conserva el original sin recomprimir en: ' .. path); return
end
if destination == 'timeline' then
    local active = current:GetCurrentTimeline()
    if not active or not timelineId or active:GetUniqueId() ~= timelineId then
        alert('Importado a la biblioteca. La timeline ha cambiado o no había ninguna abierta.'); return
    end
    local added = pool:AppendToTimeline(clips)
    if not added or #added == 0 then alert('Importado a la biblioteca, pero Resolve no pudo añadirlo a la timeline.'); return end
    alert('Añadido al final de la timeline. Archivo conservado en: ' .. path)
else
    alert('Importado a la biblioteca. Archivo conservado en: ' .. path)
end
