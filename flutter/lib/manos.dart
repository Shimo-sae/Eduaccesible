import 'dart:async';
import 'dart:math' as math;
import 'package:camera/camera.dart';
import 'package:flutter/services.dart' show DeviceOrientation;
import 'package:hand_landmarker/hand_landmarker.dart';
import 'senas.dart';

/// Una mano vista, para dibujarla (puntos normalizados 0..1) y saber si es "clara" (verde) o dudosa (naranja).
class ManoVista {
  final List<List<double>> puntos;
  final bool clara;
  ManoVista(this.puntos, this.clara);
}

/// Señas de mano en vivo: ve hasta dos manos, y solo ejecuta una seña clara, quieta y sostenida.
class Manos {
  dynamic _plugin;
  StreamSubscription? _sub;
  Timer? _vigia;
  final Estabilizador estab = Estabilizador();
  bool activo = false;
  String nota = '';
  String? visto;
  List<ManoVista> manos = [];
  CameraController? _cam;
  CameraDescription? _desc;
  int _ultimoFrameMs = 0, _ultimaRespuestaMs = 0;
  double _ancho = 480, _alto = 640;

  void Function(String sena)? alEjecutar;
  void Function()? alCambiar;

  String? get dominante => estab.dominante;
  double get progreso => estab.progreso;

  Future<void> iniciar(CameraController cam, CameraDescription desc) async {
    await detener(cam);
    _cam = cam;
    _desc = desc;
    final dynamic creado = HandLandmarkerPlugin.create(
        numHands: 2, minHandDetectionConfidence: 0.7, delegate: HandLandmarkerDelegate.gpu);
    _plugin = await creado;
    _sub = _plugin.landmarkStream.listen((dynamic h) => _alRecibir(List<Hand>.from(h)));
    _ultimaRespuestaMs = DateTime.now().millisecondsSinceEpoch;
    // Si el detector no avisa cuando no hay manos, cada 0,3 s sin respuesta se cuenta como "sin manos"
    _vigia = Timer.periodic(const Duration(milliseconds: 300), (_) {
      if (DateTime.now().millisecondsSinceEpoch - _ultimaRespuestaMs > 400) _alRecibir(const []);
    });
    await cam.startImageStream((CameraImage img) {
      final t = DateTime.now().millisecondsSinceEpoch;
      if (t - _ultimoFrameMs < 80) return; // unos 12 cuadros por segundo bastan
      _ultimoFrameMs = t;
      try {
        // Cuánto hay que girar el cuadro para verlo derecho, según cómo sostengas el teléfono (vertical u horizontal)
        final grados = switch (_cam!.value.deviceOrientation) {
          DeviceOrientation.portraitUp => 0,
          DeviceOrientation.landscapeLeft => 90,
          DeviceOrientation.portraitDown => 180,
          DeviceOrientation.landscapeRight => 270,
        };
        final sensor = _desc!.sensorOrientation;
        final rot = _desc!.lensDirection == CameraLensDirection.front ? (sensor + grados) % 360 : (sensor - grados + 360) % 360;
        final mn = math.min(img.width, img.height).toDouble(), mx = math.max(img.width, img.height).toDouble();
        _ancho = rot % 180 == 90 ? mn : mx;
        _alto = rot % 180 == 90 ? mx : mn;
        _plugin?.processFrame(img, rot);
      } catch (_) {}
    });
    activo = true;
  }

  Future<void> detener(CameraController? cam) async {
    activo = false;
    _vigia?.cancel();
    _vigia = null;
    await _sub?.cancel();
    _sub = null;
    try {
      if (cam != null && cam.value.isStreamingImages) await cam.stopImageStream();
    } catch (_) {}
    try {
      _plugin?.dispose();
    } catch (_) {}
    _plugin = null;
    manos = [];
    visto = null;
  }

  (bool, String) _clara(List<List<double>> px) {
    final tam = math.sqrt(math.pow(px[0][0] - px[9][0], 2) + math.pow(px[0][1] - px[9][1], 2));
    if (tam < 0.11 * _alto) return (false, 'acerca más la mano a la cámara');
    final xs = px.map((q) => q[0]), ys = px.map((q) => q[1]);
    const m = 0.02;
    if (xs.reduce(math.min) < m * _ancho || xs.reduce(math.max) > (1 - m) * _ancho ||
        ys.reduce(math.min) < m * _alto || ys.reduce(math.max) > (1 - m) * _alto) {
      return (false, 'la mano está cortada por el borde: llévala al centro');
    }
    return (true, '');
  }

  void _alRecibir(List<Hand> hands) {
    _ultimaRespuestaMs = DateTime.now().millisecondsSinceEpoch;
    final ahora = _ultimaRespuestaMs / 1000.0;
    final vistas = <ManoVista>[];
    final claras = <String?>[];
    final pxClaras = <List<List<double>>>[];
    var dudosas = 0;
    var motivo = '';
    for (final h in hands) {
      final px = [for (final l in h.landmarks) [l.x * _ancho, l.y * _alto]];
      final (ok, m) = _clara(px);
      vistas.add(ManoVista([for (final l in h.landmarks) [l.x, l.y]], ok));
      if (ok) {
        claras.add(clasificarMano(px));
        pxClaras.add(px);
      } else {
        dudosas++;
        motivo = m;
      }
    }
    String? g;
    nota = '';
    if (hands.isEmpty) {
      g = null;
    } else if (claras.isEmpty) {
      nota = motivo;
    } else if (dudosas > 0) {
      nota = 'hay otra mano dudosa ($motivo): muéstrala completa o bájala';
    } else if (claras.any((c) => c == null)) {
      nota = 'gesto a medias: abre o cierra los dedos del todo';
    } else {
      g = combinarManos(claras);
      if (g == null) nota = 'esa combinación de dos manos no es una seña (di: señas)';
    }
    List<double>? meta;
    if (g != null) {
      var cx = 0.0, cy = 0.0, tam = 0.0;
      for (final px in pxClaras) {
        cx += px.map((q) => q[0]).reduce((a, b) => a + b) / 21;
        cy += px.map((q) => q[1]).reduce((a, b) => a + b) / 21;
        tam += math.sqrt(math.pow(px[0][0] - px[9][0], 2) + math.pow(px[0][1] - px[9][1], 2));
      }
      final n = pxClaras.length;
      meta = [cx / n, cy / n, math.max(tam / n, 1.0)];
    }
    manos = vistas;
    visto = g;
    final r = estab.actualizar(g, ahora, meta);
    if (nota.isEmpty) nota = estab.nota;
    if (r != null) alEjecutar?.call(r);
    alCambiar?.call();
  }

  static const nombres = {
    'palma': 'mano abierta', 'puno': 'puño', 'uno': 'un dedo', 'dos': 'dos dedos', 'tres': 'tres dedos',
    'cuatro': 'cuatro dedos', 'pulgar': 'pulgar arriba',
  };

  static String nombre(String? g) {
    if (g == null) return '';
    if (g.contains('+')) {
      final p = g.split('+');
      return 'dos manos: ${nombres[p[0]] ?? p[0]} y ${nombres[p[1]] ?? p[1]}';
    }
    return nombres[g] ?? g;
  }

  /// Texto para la barra de estado.
  String estadoTexto() {
    if (!activo) return '';
    final d = estab.dominante;
    if (d != null && estab.nota.isEmpty) {
      final n = (estab.progreso * 8).floor().clamp(0, 8);
      return '🖐 Veo: ${nombre(d)}  ${'█' * n}${'░' * (8 - n)}  (mantenlo)';
    }
    if (visto != null) return '🖐 Veo: ${nombre(visto)}  (mantenlo firme)';
    if (manos.isEmpty) return '🖐 Gestos activos: no veo ninguna mano (acércala, con buena luz)';
    final n = manos.length;
    return '🖐 Veo $n mano${n == 1 ? '' : 's'}, sin seña: ${nota.isEmpty ? 'esa no es una de la lista' : nota}';
  }
}
