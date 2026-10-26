import 'dart:convert';
import 'dart:io';
import 'package:path_provider/path_provider.dart';

/// Algo que puede hacer un botón lateral.
class Accion {
  final String id, icono, nombre, descripcion;
  const Accion(this.id, this.icono, this.nombre, this.descripcion);
}

const List<Accion> acciones = [
  Accion('capturar', '📷', 'Capturar', 'toma la foto y la lee'),
  Accion('repetir', '▶', 'Repetir', 'vuelve a leer lo último'),
  Accion('inicio', '🏠', 'Inicio', 'va al menú principal'),
  Accion('atras', '↩', 'Atrás', 'vuelve a la pantalla anterior'),
  Accion('silencio', '🔇', 'Silencio', 'corta la lectura'),
  Accion('camara', '🔄', 'Cámara', 'cambia entre la cámara frontal y la trasera'),
  Accion('orden', '🎤', 'Orden', 'escucha una orden por voz'),
  Accion('voz', '🎙', 'Voz activa', 'enciende o apaga la voz siempre activa'),
  Accion('gestos', '🖐', 'Gestos', 'enciende o apaga las señas de mano'),
  Accion('importar', '🖼', 'Importar', 'abre una imagen de la galería'),
  Accion('m_texto', '📖', 'Leer texto', 'abre leer texto'),
  Accion('m_letras', '🅰', 'Letras', 'abre letras y palabras'),
  Accion('m_numeros', '🔢', 'Números', 'abre reconocer números'),
  Accion('m_figuras', '🔷', 'Figuras', 'abre figuras geométricas'),
  Accion('m_objetos', '📦', 'Objetos', 'abre contar objetos'),
  Accion('materiales', '📁', 'Materiales', 'abre los materiales guardados'),
  Accion('ajustes', '⚙', 'Ajustes', 'abre los ajustes'),
  Accion('senas_lista', '✋', 'Señas', 'lee la lista de señas'),
];

Accion accionDe(String id) => acciones.firstWhere((a) => a.id == id, orElse: () => acciones[0]);

/// Funciones de fábrica de los 4 botones laterales (las que llevan en braille).
const List<String> botonesDeFabrica = ['capturar', 'repetir', 'inicio', 'atras'];

/// Ajustes que se guardan en el teléfono (por ahora: qué hace cada botón lateral).
class AjustesApp {
  List<String> botones = [...botonesDeFabrica];

  Future<File> _archivo() async => File('${(await getApplicationDocumentsDirectory()).path}/ajustes.json');

  Future<void> cargar() async {
    try {
      final f = await _archivo();
      if (await f.exists()) {
        final d = jsonDecode(await f.readAsString());
        final l = List<String>.from(d['botones'] ?? []);
        if (l.length == 4 && l.every((id) => acciones.any((a) => a.id == id))) botones = l;
      }
    } catch (_) {}
  }

  Future<void> guardar() async {
    try {
      await (await _archivo()).writeAsString(jsonEncode({'botones': botones}));
    } catch (_) {}
  }
}
