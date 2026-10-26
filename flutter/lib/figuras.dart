// Figuras geométricas: traducción a Dart (sin OpenCV) de la detección de la versión de Windows.
// Clasifica cada píxel en un color con nombre, junta los píxeles de cada color en manchas y decide la forma
// de cada mancha por el número de vértices de su contorno.
import 'dart:io';
import 'dart:math' as math;
import 'dart:typed_data';
import 'package:flutter/foundation.dart';
import 'package:image/image.dart' as img;

const List<String> nombresColor = [
  'negro', 'blanco', 'gris', 'rojo', 'naranja', 'amarillo', 'verde', 'azul', 'morado', 'rosa'
];

class Figura {
  final String forma, color;
  final int x;
  Figura(this.forma, this.color, this.x);
}

/// recorte = true: solo la zona central (la que se ve en la guía de la cámara).
Future<List<Figura>> detectarFiguras(String ruta, {bool recorte = true}) => compute(_detectar, [ruta, recorte]);

int _clase(int r, int g, int b) {
  final mx = math.max(r, math.max(g, b)), mn = math.min(r, math.min(g, b));
  final d = mx - mn;
  final v = mx;
  final s = mx == 0 ? 0 : (255 * d / mx).round();
  double h = 0;
  if (d != 0) {
    if (mx == r) {
      h = 60 * (((g - b) / d) % 6);
    } else if (mx == g) {
      h = 60 * ((b - r) / d + 2);
    } else {
      h = 60 * ((r - g) / d + 4);
    }
  }
  if (h < 0) h += 360;
  final hc = (h / 2).floor(); // 0..179, como OpenCV
  if (v < 70) return 0;
  if (s < 40 && v > 180) return 1;
  if (s < 40) return 2;
  if (hc < 8 || hc >= 170) return 3;
  if (hc < 22) return 4;
  if (hc < 35) return 5;
  if (hc < 85) return 6;
  if (hc < 130) return 7;
  if (hc < 160) return 8;
  return 9;
}

class _Mancha {
  final int color, area, minx, miny, maxx, maxy;
  final double cx, cy;
  final List<math.Point<int>> borde;
  _Mancha(this.color, this.area, this.minx, this.miny, this.maxx, this.maxy, this.cx, this.cy, this.borde);
  int get w => maxx - minx + 1;
  int get h => maxy - miny + 1;
}

double _cruz(math.Point<int> o, math.Point<int> a, math.Point<int> b) =>
    ((a.x - o.x) * (b.y - o.y) - (a.y - o.y) * (b.x - o.x)).toDouble();

List<math.Point<int>> _casco(List<math.Point<int>> pts) {
  final p = [...pts]..sort((a, b) => a.x != b.x ? a.x.compareTo(b.x) : a.y.compareTo(b.y));
  if (p.length < 3) return p;
  final inf = <math.Point<int>>[];
  for (final q in p) {
    while (inf.length >= 2 && _cruz(inf[inf.length - 2], inf.last, q) <= 0) {
      inf.removeLast();
    }
    inf.add(q);
  }
  final sup = <math.Point<int>>[];
  for (final q in p.reversed) {
    while (sup.length >= 2 && _cruz(sup[sup.length - 2], sup.last, q) <= 0) {
      sup.removeLast();
    }
    sup.add(q);
  }
  inf.removeLast();
  sup.removeLast();
  return [...inf, ...sup];
}

double _areaPoligono(List<math.Point<int>> h) {
  var a = 0.0;
  for (var i = 0; i < h.length; i++) {
    final p = h[i], q = h[(i + 1) % h.length];
    a += p.x * q.y - q.x * p.y;
  }
  return a.abs() / 2;
}

double _perimetro(List<math.Point<int>> h) {
  var s = 0.0;
  for (var i = 0; i < h.length; i++) {
    s += h[i].distanceTo(h[(i + 1) % h.length]);
  }
  return s;
}

double _distSegmento(math.Point<int> p, math.Point<int> a, math.Point<int> b) {
  final dx = (b.x - a.x).toDouble(), dy = (b.y - a.y).toDouble();
  final l2 = dx * dx + dy * dy;
  if (l2 == 0) return p.distanceTo(a);
  final t = (((p.x - a.x) * dx + (p.y - a.y) * dy) / l2).clamp(0.0, 1.0);
  return math.sqrt(math.pow(p.x - (a.x + t * dx), 2) + math.pow(p.y - (a.y + t * dy), 2));
}

List<math.Point<int>> _rdp(List<math.Point<int>> p, double eps) {
  if (p.length < 3) return p;
  var mejor = 0.0, idx = 0;
  for (var i = 1; i < p.length - 1; i++) {
    final d = _distSegmento(p[i], p.first, p.last);
    if (d > mejor) {
      mejor = d;
      idx = i;
    }
  }
  if (mejor <= eps) return [p.first, p.last];
  final a = _rdp(p.sublist(0, idx + 1), eps), b = _rdp(p.sublist(idx), eps);
  return [...a.sublist(0, a.length - 1), ...b];
}

/// Número de vértices del contorno cerrado (aproximación de polígono, como approxPolyDP).
List<math.Point<int>> _vertices(List<math.Point<int>> h, double eps) {
  var lejos = 0;
  var dmax = -1.0;
  for (var i = 1; i < h.length; i++) {
    final d = h[0].distanceTo(h[i]);
    if (d > dmax) {
      dmax = d;
      lejos = i;
    }
  }
  final a = _rdp(h.sublist(0, lejos + 1), eps);
  final b = _rdp([...h.sublist(lejos), h[0]], eps);
  return [...a.sublist(0, a.length - 1), ...b.sublist(0, b.length - 1)];
}

String? _clasificar(_Mancha m) {
  if (m.borde.length < 6) return null;
  final h = _casco(m.borde);
  if (h.length < 3) return null;
  final peri = _perimetro(h);
  if (peri == 0 || m.area == 0) return null;
  final v = _vertices(h, 0.03 * peri);
  var radio = 0.0;
  for (final q in h) {
    radio = math.max(radio, math.sqrt(math.pow(q.x - m.cx, 2) + math.pow(q.y - m.cy, 2)));
  }
  final ratioCirculo = radio > 0 ? m.area / (math.pi * radio * radio) : 0.0;
  final n = v.length;
  if (n >= 5 && ratioCirculo > 0.88) return 'círculo';
  if (n == 3) return 'triángulo';
  if (n == 4) {
    final l = [for (var i = 0; i < 4; i++) v[i].distanceTo(v[(i + 1) % 4])];
    final w = (l[0] + l[2]) / 2, hh = (l[1] + l[3]) / 2;
    if (math.min(w, hh) == 0) return null;
    return math.min(w, hh) / math.max(w, hh) >= 0.88 ? 'cuadrado' : 'rectángulo';
  }
  if (n == 5) return 'pentágono';
  if (n == 6) return 'hexágono';
  return 'figura irregular';
}

List<Figura> _detectar(List<dynamic> args) {
  final ruta = args[0] as String;
  final recorte = args[1] as bool;
  var im = img.decodeImage(File(ruta).readAsBytesSync());
  if (im == null) return [];
  im = img.bakeOrientation(im);
  if (recorte) {
    im = img.copyCrop(im,
        x: (im.width * .08).round(), y: (im.height * .08).round(),
        width: (im.width * .84).round(), height: (im.height * .84).round());
  }
  im = img.copyResize(im, width: 480, interpolation: img.Interpolation.average);
  final w = im.width, h = im.height, total = w * h;
  final cls = Uint8List(total);
  for (var y = 0; y < h; y++) {
    for (var x = 0; x < w; x++) {
      final p = im.getPixel(x, y);
      cls[y * w + x] = _clase(p.r.toInt(), p.g.toInt(), p.b.toInt());
    }
  }
  // Manchas conectadas de un mismo color
  final visto = Uint8List(total);
  final pila = Int32List(total);
  final manchas = <_Mancha>[];
  for (var inicio = 0; inicio < total; inicio++) {
    if (visto[inicio] == 1) continue;
    final k = cls[inicio];
    var tope = 0;
    pila[tope++] = inicio;
    visto[inicio] = 1;
    var area = 0, minx = w, miny = h, maxx = 0, maxy = 0;
    var sx = 0.0, sy = 0.0;
    final borde = <math.Point<int>>[];
    while (tope > 0) {
      final i = pila[--tope];
      final x = i % w, y = i ~/ w;
      area++;
      sx += x;
      sy += y;
      if (x < minx) minx = x;
      if (x > maxx) maxx = x;
      if (y < miny) miny = y;
      if (y > maxy) maxy = y;
      var esBorde = false;
      for (final d in const [[1, 0], [-1, 0], [0, 1], [0, -1]]) {
        final nx = x + d[0], ny = y + d[1];
        if (nx < 0 || ny < 0 || nx >= w || ny >= h) {
          esBorde = true;
          continue;
        }
        final j = ny * w + nx;
        if (cls[j] != k) {
          esBorde = true;
        } else if (visto[j] == 0) {
          visto[j] = 1;
          pila[tope++] = j;
        }
      }
      if (esBorde) borde.add(math.Point(x, y));
    }
    if (area < total * 0.004 || area > total * 0.90) continue; // muy pequeño = ruido
    if (minx <= 1 || miny <= 1 || maxx >= w - 2 || maxy >= h - 2) continue; // toca el borde: fondo o marco
    final m = _Mancha(k, area, minx, miny, maxx, maxy, sx / area, sy / area, borde);
    if (nombresColor[k] == 'gris') {
      // los grises solo valen si son formas sólidas (no sombras ni reflejos)
      final hull = _areaPoligono(_casco(borde));
      if (hull == 0 || area / hull < 0.93) continue;
    }
    manchas.add(m);
  }
  // Descartar "contenedores": pantalla, marco u hoja grande que tiene otras figuras dentro
  final finales = <_Mancha>[];
  for (final a in manchas) {
    final neutro = a.color == 0 || a.color == 1;
    if (a.area > total * 0.25 || (neutro && a.area > total * 0.08)) {
      final dentro = manchas.any((b) =>
          !identical(b, a) &&
          a.minx <= b.minx + b.w / 2 && b.minx + b.w / 2 <= a.minx + a.w &&
          a.miny <= b.miny + b.h / 2 && b.miny + b.h / 2 <= a.miny + a.h);
      if (dentro) continue;
    }
    finales.add(a);
  }
  final figuras = <Figura>[];
  for (final m in finales) {
    final f = _clasificar(m);
    if (f != null) figuras.add(Figura(f, nombresColor[m.color], m.minx));
  }
  figuras.sort((a, b) => a.x.compareTo(b.x));
  return figuras.take(8).toList();
}

String fraseFiguras(List<Figura> f) {
  if (f.isEmpty) return 'No se detectaron figuras. Coloca la figura sobre un fondo liso y con buena luz.';
  if (f.length == 1) return 'Se detectó un ${f[0].forma} ${f[0].color}.';
  return 'Se detectaron ${f.length} figuras, de izquierda a derecha: ${f.map((e) => '${e.forma} ${e.color}').join(', ')}.';
}
