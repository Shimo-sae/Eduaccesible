/// Registro interno de lo que hace la app (errores, lo que oye el micrófono, lo que detecta la cámara).
/// Se ve en Ajustes → Diagnóstico y se puede compartir, para saber por qué algo falla sin conectar el celular al computador.
class Registro {
  static final List<String> _lineas = [];
  static final Map<String, int> _veces = {};

  static void anotar(String texto) {
    final t = DateTime.now();
    String d2(int n) => n.toString().padLeft(2, '0');
    _lineas.add('${d2(t.hour)}:${d2(t.minute)}:${d2(t.second)}  $texto');
    if (_lineas.length > 400) _lineas.removeRange(0, _lineas.length - 400);
  }

  /// Como [anotar] pero solo las primeras [max] veces (para lo que ocurre muchas veces por segundo).
  static void poco(String clave, String texto, {int max = 5}) {
    final n = (_veces[clave] ?? 0) + 1;
    _veces[clave] = n;
    if (n <= max) anotar(texto);
  }

  static void contar(String clave) => _veces[clave] = (_veces[clave] ?? 0) + 1;
  static int veces(String clave) => _veces[clave] ?? 0;

  static String texto() => _lineas.isEmpty ? '(sin registros todavía)' : _lineas.join('\n');
  static void limpiar() {
    _lineas.clear();
    _veces.clear();
  }
}
