import AppKit
import Foundation
let pb = NSPasteboard.general
let target = CommandLine.arguments[1]
// Prefer original encoded clipboard bytes; never resize or encode as JPEG.
for pair in [(NSPasteboard.PasteboardType("public.png"), "png"), (NSPasteboard.PasteboardType("public.jpeg"), "jpg")] {
    if let data = pb.data(forType: pair.0), NSImage(data: data) != nil {
        let path = target + "." + pair.1
        try data.write(to: URL(fileURLWithPath: path), options: .atomic)
        print(path)
        exit(0)
    }
}
if let objects = pb.readObjects(forClasses: [NSURL.self], options: nil) {
    for obj in objects {
        if let url = obj as? URL, url.isFileURL, NSImage(contentsOf: url) != nil {
            let path = target + "." + url.pathExtension
            try FileManager.default.copyItem(atPath: url.path, toPath: path)
            print(path)
            exit(0)
        }
    }
}
if let data = pb.data(forType: .tiff), let rep = NSBitmapImageRep(data: data),
   let png = rep.representation(using: .png, properties: [:]) {
    let path = target + ".png"
    try png.write(to: URL(fileURLWithPath: path), options: .atomic)
    print(path)
    exit(0)
}
if let string = pb.string(forType: .string) { print("URL:" + string.trimmingCharacters(in: .whitespacesAndNewlines)); exit(0) }
fputs("El portapapeles no contiene una imagen. Usa Copiar imagen en el navegador.\n", stderr)
exit(1)
