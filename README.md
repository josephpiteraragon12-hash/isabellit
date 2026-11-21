# Isabelledit

Editor de video liviano para Windows, pensado para laptops viejas.
Corta, une, cambia velocidad, aplica filtros, añade texto y música, y exporta con **calidad visualmente idéntica** en archivos livianos (H.264 CRF 16).

## Cómo obtener el .exe (sin instalar nada en tu PC)

1. Crea un repositorio nuevo en [github.com/new](https://github.com/new).
2. Sube **todo el contenido de esta carpeta** (incluida `.github`) con *Add file → Upload files*.
3. Entra a la pestaña **Actions**. La compilación empieza sola (tarda ~5–8 min). Si no, pulsa *Compilar Isabelledit → Run workflow*.
4. Al terminar, abre la ejecución y descarga **Isabelledit-Windows** (sección *Artifacts*).
5. Descomprime el zip y abre **Isabelledit.exe**. Ya trae FFmpeg dentro; no necesitas instalar nada.

Para publicar una versión descargable en la sección *Releases*, crea una etiqueta: `git tag v1.0 && git push --tags`.

> Se entrega como carpeta (no como un único .exe) a propósito: abre en 1–2 segundos incluso en equipos lentos. Un .exe único tendría que descomprimir ~250 MB cada vez que lo abres.

## Uso rápido

| Acción | Cómo |
|---|---|
| Añadir videos | Arrástralos a la ventana o **+ Importar** |
| Cortar | Mueve el cursor en la línea de tiempo → **Dividir** (Ctrl+K) |
| Recortar | *Inicio / Fin* en el panel derecho |
| Reordenar | **←  →** |
| Efectos | Brillo, contraste, saturación, velocidad, volumen, filtros, fundidos, texto |
| Ver el resultado | **Probar efectos (4 s)** genera una vista previa rápida con los efectos |
| Música | **♪ Música** (se mezcla al exportar) |
| Deshacer | Ctrl+Z (cortes, borrados, orden) |
| Exportar | **Exportar** (Ctrl+E) |

### Calidad de exportación
- **Idéntica** (recomendada): sin pérdida visible, archivo mucho más liviano que un video sin comprimir.
- **Alta / Ligera**: más rápida o más pequeña.
- **Copia exacta**: une clips enteros sin recodificar. Instantánea y 100 % igual al original (solo si no hay cortes, efectos ni música).

## Probar en tu PC con Python (opcional)
```
pip install -r requirements.txt
python main.py        # necesita ffmpeg y ffprobe en el PATH
```
