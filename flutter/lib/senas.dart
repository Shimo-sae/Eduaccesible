// Lógica pura (sin Android): señas, clasificador de mano, estabilizador y órdenes de voz.
// Es la traducción directa de la versión de Windows (app.py).
import 'dart:math' as math;

String par(String a, String b) {
  final l = [a, b]..sort();
  return l.join('+');
}

class Sena {
  final String orden, nombre, como;
  const Sena(this.orden, this.nombre, this.como);
}

final Map<String, Sena> senas = {
  'uno': const Sena('m_texto', 'leer texto', 'un dedo levantado'),
  'dos': const Sena('m_letras', 'reconocer letras y palabras', 'dos dedos levantados'),
  'tres': const Sena('m_numeros', 'reconocer números', 'tres dedos levantados'),
  'cuatro': const Sena('m_figuras', 'figuras geométricas', 'cuatro dedos levantados, sin el pulgar'),
  'palma': const Sena('m_objetos', 'contar objetos', 'una mano completamente abierta'),
  par('palma', 'uno'): const Sena('materiales', 'materiales guardados',
      'dos manos: una mano abierta y la otra con un dedo, como contar seis'),
  par('palma', 'dos'): const Sena('ajustes', 'ajustes',
      'dos manos: una mano abierta y la otra con dos dedos, como contar siete'),
  par('puno', 'puno'): const Sena('capturar', 'capturar', 'los dos puños cerrados'),
  'puno': const Sena('repetir', 'repetir', 'un puño cerrado'),
  par('palma', 'palma'): const Sena('silencio', 'silencio', 'las dos manos abiertas, como pidiendo que pare'),
  par('uno', 'uno'): const Sena('inicio', 'ir al inicio', 'dos manos, un dedo levantado en cada una'),
  par('dos', 'dos'): const Sena('atras', 'volver atrás', 'dos manos, dos dedos levantados en cada una'),
  par('tres', 'tres'): const Sena('senas', 'ayuda de señas', 'dos manos, tres dedos levantados en cada una'),
  'pulgar': const Sena('voz', 'la voz siempre activa', 'el pulgar hacia arriba'),
};

String? senaDeOrden(String orden) {
  for (final e in senas.entries) {
    if (e.value.orden == orden) return e.key;
  }
  return null;
}

String fraseSena(String orden) {
  if (orden == 'voz_on' || orden == 'voz_off') orden = 'voz';
  final clave = senaDeOrden(orden);
  if (clave == null) {
    if (orden == 'gestos_on' || orden == 'gestos_off') {
      return 'Los gestos no tienen seña, porque para hacer señas ya tienen que estar activos.';
    }
    return 'Esa opción no tiene seña. Está dentro de Ajustes, o se pide por voz.';
  }
  final s = senas[clave]!;
  return 'La seña de ${s.nombre} es: ${s.como}.';
}

List<Sena> listaSenas() {
  const orden = ['m_texto', 'm_letras', 'm_numeros', 'm_figuras', 'm_objetos', 'materiales', 'ajustes',
    'capturar', 'repetir', 'silencio', 'inicio', 'atras', 'senas', 'voz'];
  return [for (final o in orden) senas[senaDeOrden(o)]!];
}

// ------------------------------------------------------------------ Clasificador de mano
// p: 21 puntos [x, y] en PÍXELES (formato MediaPipe Hands). Devuelve 'palma', 'puno', 'uno', 'dos', 'tres',
// 'cuatro', 'pulgar' o null (también null si algún dedo está a medias).
const double dedoAbierto = 1.18, dedoCerrado = 0.98;

String? clasificarMano(List<List<double>> p) {
  double d(int a, int b) {
    final dx = p[a][0] - p[b][0], dy = p[a][1] - p[b][1];
    return math.sqrt(dx * dx + dy * dy);
  }

  final dedos = <bool>[];
  for (final par_ in const [[8, 6], [12, 10], [16, 14], [20, 18]]) {
    final r = d(par_[0], 0) / (d(par_[1], 0) < 1e-6 ? 1e-6 : d(par_[1], 0));
    if (r >= dedoAbierto) {
      dedos.add(true);
    } else if (r <= dedoCerrado) {
      dedos.add(false);
    } else {
      return null;
    }
  }
  final pulgar = d(4, 17) > d(3, 17) * 1.05 && d(4, 5) > d(3, 5);
  final n = dedos.where((x) => x).length;
  final indice = dedos[0], medio = dedos[1], anular = dedos[2], menique = dedos[3];
  if (n == 4 && pulgar) return 'palma';
  if (n == 0) {
    if (pulgar && p[4][1] < p[3][1] && p[3][1] < p[2][1] && p[5][1] - p[4][1] > 0.2 * d(0, 9)) return 'pulgar';
    return 'puno';
  }
  if (n == 4) return 'cuatro';
  if (indice && !(medio || anular || menique)) return 'uno';
  if (indice && medio && !(anular || menique)) return 'dos';
  if (indice && medio && anular && !menique) return 'tres';
  return null;
}

/// Combina las manos claras de un cuadro en una seña: una mano -> su gesto; dos manos -> "a+b" solo si está en [senas].
String? combinarManos(List<String?> gestos) {
  if (gestos.isEmpty || gestos.any((g) => g == null)) return null;
  if (gestos.length == 1) return gestos[0];
  final g = par(gestos[0]!, gestos[1]!);
  return senas.containsKey(g) ? g : null;
}

/// Estabilizador: ejecuta una seña solo si se mantuvo ~[hold] segundos en casi toda la ventana, con la mano quieta,
/// y hay que soltarla antes de que vuelva a valer. Llama a [actualizar] con cada cuadro (seña o null).
/// [meta] = [centro x, centro y, largo de palma] de las manos que hacen la seña.
class Estabilizador {
  final double hold, enfriar, maxMov;
  Estabilizador({this.hold = 1.2, this.enfriar = 2.5, this.maxMov = 0.9});
  final List<(double, String?, List<double>?)> _m = [];
  final List<String?> _ultimas = [];
  double _bloqueadoHasta = 0;
  String? _desarmado;
  String? dominante;
  double progreso = 0;
  String nota = '';

  bool _quieta(String g) {
    final metas = [for (final e in _m) if (e.$2 == g && e.$3 != null) e.$3!];
    if (metas.length < 2) return true;
    final xs = metas.map((m) => m[0]), ys = metas.map((m) => m[1]);
    final tam = metas.map((m) => m[2]).reduce((a, b) => a + b) / metas.length;
    final mov = math.max(xs.reduce(math.max) - xs.reduce(math.min), ys.reduce(math.max) - ys.reduce(math.min));
    return mov <= maxMov * tam;
  }

  String? actualizar(String? g, double ahora, [List<double>? meta]) {
    _m.add((ahora, g, g == null ? null : meta));
    while (_m.isNotEmpty && ahora - _m.first.$1 > hold) {
      _m.removeAt(0);
    }
    _ultimas.add(g);
    if (_ultimas.length > 8) _ultimas.removeAt(0);
    if (_desarmado != null) {
      final ajenos = _ultimas.where((x) => x != _desarmado).length;
      if (_ultimas.length >= 6 && ajenos >= 5) _desarmado = null;
    }
    dominante = null;
    progreso = 0;
    nota = '';
    final cuenta = <String, int>{};
    for (final e in _m) {
      if (e.$2 != null) cuenta[e.$2!] = (cuenta[e.$2!] ?? 0) + 1;
    }
    if (cuenta.isEmpty) return null;
    final mejor = cuenta.entries.reduce((a, b) => a.value >= b.value ? a : b);
    final span = ahora - _m.first.$1;
    final frac = mejor.value / _m.length;
    if (frac < 0.8) return null;
    dominante = mejor.key;
    final quieta = _quieta(mejor.key);
    if (!quieta) {
      nota = 'mantén la mano quieta';
      return null;
    }
    progreso = math.min(1.0, span / (hold * 0.9)) * math.min(1.0, frac);
    if (span >= hold * 0.9 && _m.length >= 6 && ahora >= _bloqueadoHasta && mejor.key != _desarmado) {
      _m.clear();
      _ultimas.clear();
      _bloqueadoHasta = ahora + enfriar;
      _desarmado = mejor.key;
      return mejor.key;
    }
    return null;
  }
}

// ------------------------------------------------------------------ Órdenes de voz
String sinTildes(String t) {
  const a = 'áéíóúüñ', b = 'aeiouun';
  var r = t.toLowerCase();
  for (var i = 0; i < a.length; i++) {
    r = r.replaceAll(a[i], b[i]);
  }
  return r;
}

class _O {
  final List<String> claves;
  final String orden;
  const _O(this.claves, this.orden);
}

// Se revisa en este orden: lo más específico primero.
const List<_O> _ordenes = [
  _O(['ayuda de senas', 'lista de senas', 'que senas hay', 'todas las senas', 'senas', 'ayuda'], 'senas_lista'),
  _O(['configurar botones', 'botones laterales', 'cambiar botones', 'editar botones', 'botones'], 'botones'),
  _O(['desactivar voz', 'apagar voz', 'dejar de escuchar', 'modo manual'], 'voz_off'),
  _O(['activar voz', 'voz activa', 'voz siempre activa', 'escuchar siempre', 'modo voz'], 'voz_on'),
  _O(['desactivar gestos', 'apagar gestos', 'quitar gestos', 'sin gestos'], 'gestos_off'),
  _O(['activar gestos', 'activa gestos', 'gestos', 'gesto'], 'gestos_on'),
  _O(['cambiar camara', 'otra camara', 'siguiente camara', 'camara', 'camaras'], 'camara'),
  _O(['ajustes', 'configuracion', 'dispositivos'], 'ajustes'),
  _O(['wifi', 'wi fi', 'recibir', 'red'], 'wifi'),
  _O(['importar', 'subir imagen', 'abrir imagen', 'imagen', 'documento', 'archivo', 'pdf', 'word'], 'importar'),
  _O(['materiales', 'guardados'], 'materiales'),
  _O(['contar', 'objetos', 'cuantos'], 'm_objetos'),
  _O(['figuras', 'geometricas', 'formas'], 'm_figuras'),
  _O(['numeros', 'numero', 'cifras'], 'm_numeros'),
  _O(['letras', 'palabras', 'abecedario'], 'm_letras'),
  _O(['leer texto', 'texto', 'leer'], 'm_texto'),
  _O(['capturar', 'captura', 'foto', 'tomar', 'escanear'], 'capturar'),
  _O(['repetir', 'otra vez', 'de nuevo', 'repite'], 'repetir'),
  _O(['detener', 'silencio', 'callate', 'calla', 'parar', 'para', 'basta'], 'silencio'),
  _O(['inicio', 'menu', 'principal'], 'inicio'),
  _O(['atras', 'volver', 'regresar', 'salir'], 'atras'),
];

const Set<String> _relleno = {'sena', 'senas', 'gesto', 'de', 'del', 'la', 'el', 'las', 'los', 'para', 'cual',
  'cuales', 'es', 'son', 'que', 'como', 'se', 'hace', 'hago', 'haces', 'una', 'un', 'dime', 'dame', 'repite',
  'me', 'puedes', 'decir', 'quiero', 'saber', 'a', 'en', 'por', 'favor'};

String? _ordenBase(String texto) {
  final base = sinTildes(texto);
  final t = ' $base ';
  final pegado = base.replaceAll(' ', '');
  for (final o in _ordenes) {
    for (final c in o.claves) {
      final cc = c.replaceAll(' ', '');
      if (t.contains(' $c ') || (c.length > 4 && t.contains(c)) || (cc.length >= 5 && pegado.contains(cc))) {
        return o.orden;
      }
    }
  }
  return null;
}

/// Devuelve la orden dicha, 'sena:<orden>' si preguntan por una seña, o 'senas_lista'.
String? interpretarOrden(String texto) {
  final base = sinTildes(texto);
  final palabras = base.split(RegExp(r'\s+')).where((p) => p.isNotEmpty).toList();
  final pregunta = palabras.contains('sena') || palabras.contains('senas') ||
      (palabras.contains('gesto') && ['de', 'del', 'para', 'cual', 'que', 'como'].any(palabras.contains));
  if (pregunta) {
    final resto = palabras.where((p) => !_relleno.contains(p)).join(' ').trim();
    if (resto.isNotEmpty) {
      final rp = resto.split(' ');
      if (rp.contains('voz') && !resto.contains('microfono') && !resto.contains('gestos')) return 'sena:voz';
      if (resto == 'ayuda' || resto == 'ayuda de senas') return 'sena:senas';
      final o = _ordenBase(resto);
      if (o != null && o != 'senas_lista') return 'sena:$o';
    }
    return 'senas_lista';
  }
  return _ordenBase(texto);
}
