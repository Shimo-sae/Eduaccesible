import 'dart:async';
import 'dart:io';
import 'dart:math' as math;
import 'package:flutter_tts/flutter_tts.dart';
import 'package:speech_to_text/speech_to_text.dart' as stt;
import 'package:google_mlkit_text_recognition/google_mlkit_text_recognition.dart';
import 'package:google_mlkit_object_detection/google_mlkit_object_detection.dart';
import 'package:google_mlkit_image_labeling/google_mlkit_image_labeling.dart';
import 'package:image/image.dart' as img;
import 'package:path_provider/path_provider.dart';
import 'etiquetas.dart';
import 'figuras.dart';
import 'registro.dart';

/// Voz que lee (TextToSpeech de Android). Se puede cortar con [detener].
class Voz {
  final FlutterTts _tts = FlutterTts();
  String ultimo = '';
  bool hablando = false;

  /// Resumen de la voz elegida (se muestra en la barra de estado al abrir la app).
  String info = '';
  bool hayEspanol = true;
  String _cod = 'es-ES';
  Map<String, String>? _vozEs;

  Future<void> iniciar() async {
    // 1) Motor: el de Google es el que trae buenas voces en español (algunos teléfonos usan uno propio sin español).
    var motor = '';
    try {
      final motores = await _tts.getEngines;
      if (motores is List && motores.any((m) => m.toString() == 'com.google.android.tts')) {
        await _tts.setEngine('com.google.android.tts');
        motor = 'Google';
        await Future.delayed(const Duration(milliseconds: 500)); // el motor tarda un momento en cambiar
      }
    } catch (_) {}
    // 2) Idioma: el primer español que el motor tenga de verdad.
    var fijada = false;
    for (final cod in ['es-CO', 'es-MX', 'es-US', 'es-419', 'es-ES']) {
      try {
        final r = await _tts.isLanguageAvailable(cod);
        if (r == true || r == 1) {
          await _tts.setLanguage(cod);
          _cod = cod;
          fijada = true;
          break;
        }
      } catch (_) {}
    }
    if (!fijada) {
      try {
        await _tts.setLanguage('es-ES');
      } catch (_) {}
    }
    // 3) Voz concreta en español (con la que sí funciona sin internet, si hay)
    var nVoces = 0;
    try {
      final voces = await _tts.getVoices;
      if (voces is List) {
        final es = voces.where((v) {
          final loc = (v is Map ? (v['locale'] ?? '') : '').toString().toLowerCase().replaceAll('_', '-');
          return loc.startsWith('es');
        }).toList();
        nVoces = es.length;
        if (es.isNotEmpty) {
          es.sort((a, b) {
            int pt(dynamic v) {
              final loc = (v['locale'] ?? '').toString().toLowerCase().replaceAll('_', '-');
              var n = 0;
              if (loc.contains('es-co') || loc.contains('es-mx') || loc.contains('es-us') || loc.contains('es-419')) n -= 2;
              if (v['network_required'].toString() == '1') n += 1;
              return n;
            }
            return pt(a).compareTo(pt(b));
          });
          _vozEs = {'name': es.first['name'].toString(), 'locale': es.first['locale'].toString()};
          await _tts.setVoice(_vozEs!);
        }
      }
    } catch (_) {}
    hayEspanol = fijada || nVoces > 0;
    info = hayEspanol
        ? '🔊 Voz: ${motor.isEmpty ? 'del teléfono' : motor}, idioma $_cod, $nVoces voz(es) en español.'
        : '🔊 Este teléfono NO tiene voz en español: se oirá en inglés. Instálala en Ajustes > Sistema > Idiomas > Salida de texto a voz > Google > Instalar datos de voz > Español.';
    await _tts.setSpeechRate(0.5);
    _tts.setStartHandler(() => hablando = true);
    _tts.setCompletionHandler(() => hablando = false);
    _tts.setCancelHandler(() => hablando = false);
    _tts.setErrorHandler((_) => hablando = false);
  }

  /// Divide un texto largo en trozos (Android no deja leer más de ~4000 letras de una vez).
  static List<String> trozos(String t, [int max = 3000]) {
    final res = <String>[];
    var resto = t.trim();
    while (resto.length > max) {
      var corte = resto.lastIndexOf(RegExp(r'[.!?\n]'), max);
      if (corte < max ~/ 2) corte = resto.lastIndexOf(' ', max);
      if (corte <= 0) corte = max;
      res.add(resto.substring(0, corte + 1).trim());
      resto = resto.substring(corte + 1).trim();
    }
    if (resto.isNotEmpty) res.add(resto);
    return res;
  }

  Future<void> hablar(String t, {bool guardar = true}) async {
    if (guardar) ultimo = t;
    hablando = true;
    try {
      await _tts.setQueueMode(0);
    } catch (_) {}
    await _tts.stop();
    hablando = true;
    final partes = trozos(t);
    if (partes.isEmpty) return;
    try {
      await _tts.setLanguage(_cod); // algunos teléfonos vuelven al inglés solos
      if (_vozEs != null) await _tts.setVoice(_vozEs!);
    } catch (_) {}
    await _tts.speak(partes.first);
    if (partes.length > 1) {
      try {
        await _tts.setQueueMode(1); // el resto se pone en fila y se lee seguido
      } catch (_) {}
      for (final p in partes.skip(1)) {
        await _tts.speak(p);
      }
    }
  }

  Future<void> detener() async {
    hablando = false;
    await _tts.stop();
  }
}

/// Reconocimiento de voz del teléfono. Una orden con [escuchar]; o siempre atento con [iniciarContinua].
class Escucha {
  final stt.SpeechToText _stt = stt.SpeechToText();
  bool listo = false;
  bool continua = false;
  String ultimoError = '';
  String? _idioma;
  String _ultimas = '';
  bool _entregado = false;
  void Function(String)? _cb;

  /// Avisos para mostrar en pantalla: lo que se va oyendo y los errores.
  void Function(String)? alParcial;
  void Function(String)? alError;

  Future<bool> iniciar() async {
    if (listo) return true;
    listo = await _stt.initialize(
      onError: (e) {
        ultimoError = e.errorMsg;
        alError?.call(e.errorMsg);
      },
      onStatus: (s) {
        // Algunos teléfonos terminan de escuchar sin avisar "resultado final": se usa lo último que se oyó
        if ((s == 'done' || s == 'notListening') && !_entregado && _ultimas.trim().isNotEmpty) {
          _entregado = true;
          _cb?.call(_ultimas);
        }
      },
    );
    if (listo) {
      try {
        final ls = await _stt.locales();
        String norm(String x) => x.replaceAll('-', '_');
        for (final pref in ['es_CO', 'es_ES', 'es_US', 'es_MX', 'es_419']) {
          final m = ls.where((l) => norm(l.localeId) == pref);
          if (m.isNotEmpty) {
            _idioma = m.first.localeId;
            break;
          }
        }
        _idioma ??= ls.where((l) => l.localeId.toLowerCase().startsWith('es')).map((l) => l.localeId).firstOrNull;
        if (_idioma == null) {
          // Sin español en la lista: se fuerza igual (si se deja vacío usaría el idioma del teléfono, p. ej. inglés,
          // y mezclaría los idiomas). Si el teléfono no lo tiene, avisará con un error claro.
          _idioma = 'es_ES';
          alError?.call('El teléfono no muestra reconocimiento de voz en español. Instálalo en Ajustes > Idioma > Escritura por voz (Google).');
        }
      } catch (_) {
        _idioma ??= 'es_ES';
      }
    }
    return listo;
  }

  Future<void> _escucharUna(void Function(String) cb, {required int segundos, required int pausa}) async {
    _cb = cb;
    _entregado = false;
    _ultimas = '';
    await _stt.listen(
      localeId: _idioma,
      listenFor: Duration(seconds: segundos),
      pauseFor: Duration(seconds: pausa),
      listenOptions: stt.SpeechListenOptions(partialResults: true, cancelOnError: false),
      onResult: (r) {
        _ultimas = r.recognizedWords;
        if (r.finalResult) Registro.anotar('Voz: oí "${r.recognizedWords}" (idioma $_idioma)');
        if (_ultimas.trim().isNotEmpty) alParcial?.call(_ultimas);
        if (r.finalResult && !_entregado && _ultimas.trim().isNotEmpty) {
          _entregado = true;
          cb(_ultimas);
        }
      },
    );
  }

  Future<bool> escuchar(void Function(String) alTerminar) async {
    if (!await iniciar()) return false;
    await _escucharUna(alTerminar, segundos: 10, pausa: 3);
    return true;
  }

  /// Escucha todo el tiempo. [hablando] dice si la app está hablando (para no oírse a sí misma).
  Future<bool> iniciarContinua(void Function(String) alOir, bool Function() hablando) async {
    if (!await iniciar()) return false;
    continua = true;
    () async {
      while (continua) {
        while (continua && hablando()) {
          await Future.delayed(const Duration(milliseconds: 200));
        }
        if (!continua) break;
        try {
          await _escucharUna(alOir, segundos: 30, pausa: 3);
          while (continua && _stt.isListening) {
            await Future.delayed(const Duration(milliseconds: 200));
          }
        } catch (_) {}
        await Future.delayed(const Duration(milliseconds: 500));
      }
    }();
    return true;
  }

  Future<void> detenerContinua() async {
    continua = false;
    try {
      await _stt.stop();
    } catch (_) {}
  }

  Future<void> parar() => _stt.stop();
}

class Lector {
  final TextRecognizer _ocr = TextRecognizer(script: TextRecognitionScript.latin);
  final ObjectDetector _obj = ObjectDetector(
      options: ObjectDetectorOptions(mode: DetectionMode.single, classifyObjects: true, multipleObjects: true));
  final ImageLabeler _etq = ImageLabeler(options: ImageLabelerOptions(confidenceThreshold: 0.5));

  Future<String> _crudo(String ruta) async => (await _ocr.processImage(InputImage.fromFilePath(ruta))).text.trim();

  Future<String> texto(String ruta) async {
    final t = await _crudo(ruta);
    return t.isEmpty ? 'No se detectó texto. Acerca la cámara, mejora la luz y mantén el papel plano.' : t;
  }

  Future<String> letras(String ruta) async {
    final t = await _crudo(ruta);
    final pal = RegExp(r'[A-Za-zÁÉÍÓÚÜÑáéíóúüñ]+').allMatches(t).map((m) => m.group(0)!).toList();
    if (pal.isEmpty) return 'No se detectaron letras. Usa letras grandes y oscuras sobre fondo claro.';
    if (pal.length == 1 && pal[0].length == 1) return 'Letra ${pal[0]}';
    final n = pal.length;
    final partes = [n == 1 ? 'Se detectó 1 palabra.' : 'Se detectaron $n palabras.'];
    for (final p in pal.take(5)) {
      partes.add('$p. Se escribe: ${p.split('').join(', ')}.');
    }
    return partes.join(' ');
  }

  Future<String> numeros(String ruta) async {
    final t = await _crudo(ruta);
    final n = RegExp(r'\d+(?:[.,]\d+)?').allMatches(t).map((m) => m.group(0)!).toList();
    return n.isEmpty ? 'No se detectó ningún número.' : 'Cifra detectada: ${n.join(', ')}';
  }

  Future<String> figuras(String ruta, {required bool recorte}) async =>
      fraseFiguras(await _figurasLog(ruta, recorte));

  Future<List<Figura>> _figurasLog(String ruta, bool recorte) async {
    final f = await detectarFiguras(ruta, recorte: recorte);
    Registro.anotar('Figuras: se detectaron ${f.length} (recorte: $recorte)');
    return f;
  }

  /// Cuenta objetos POR TIPO: ML Kit encuentra dónde hay objetos y a cada uno se le pregunta qué es.
  Future<String> objetos(String ruta) async {
    final objs = await _obj.processImage(InputImage.fromFilePath(ruta));
    Registro.anotar('Objetos: ML Kit encontró ${objs.length} -> ${objs.map((o) => '${o.boundingBox.width.round()}x${o.boundingBox.height.round()} ${o.labels.map((l) => l.text).join("/")}').join(" | ")}');
    if (objs.isEmpty) return 'No se detectaron objetos. Separa los objetos y usa buena luz.';
    final cuenta = <String, int>{};
    img.Image? im;
    try {
      final d = img.decodeImage(await File(ruta).readAsBytes());
      if (d != null) im = img.bakeOrientation(d);
    } catch (_) {}
    final tmp = await getTemporaryDirectory();
    var i = 0;
    for (final o in objs) {
      String nombre = 'objeto';
      try {
        if (im != null) {
          final r = o.boundingBox;
          final x = math.max(0, r.left.round()), y = math.max(0, r.top.round());
          final w = math.min(im.width - x, r.width.round()), h = math.min(im.height - y, r.height.round());
          if (w >= 24 && h >= 24) {
            var rec = img.copyCrop(im, x: x, y: y, width: w, height: h);
            if (math.max(w, h) > 320) {
              rec = w >= h ? img.copyResize(rec, width: 320) : img.copyResize(rec, height: 320);
            }
            final f = File('${tmp.path}/rec_${i++}.jpg')..writeAsBytesSync(img.encodeJpg(rec, quality: 85));
            final et = await _etq.processImage(InputImage.fromFilePath(f.path));
            if (et.isNotEmpty) {
              et.sort((a, b) => b.confidence.compareTo(a.confidence));
              nombre = et.first.label;
            }
            f.deleteSync();
          }
        }
      } catch (_) {}
      cuenta[nombre] = (cuenta[nombre] ?? 0) + 1;
    }
    final partes = [
      for (final e in cuenta.entries.toList()..sort((a, b) => b.value.compareTo(a.value)))
        '${e.value} ${nombreEs(e.key, e.value != 1)}'
    ];
    final detalle = partes.length == 1 ? partes[0] : '${partes.sublist(0, partes.length - 1).join(', ')} y ${partes.last}';
    final total = objs.length;
    return cuenta.length == 1 ? 'Hay $detalle.' : 'Se detectaron $total objetos: $detalle.';
  }
}

/// Materiales guardados: archivos de texto en la carpeta de la app.
class Materiales {
  Future<Directory> _dir() async {
    final base = await getApplicationDocumentsDirectory();
    final d = Directory('${base.path}/materiales');
    if (!await d.exists()) await d.create(recursive: true);
    return d;
  }

  Future<void> guardar(String modo, String texto) async {
    final d = await _dir();
    final f = File('${d.path}/${DateTime.now().millisecondsSinceEpoch}_$modo.txt');
    await f.writeAsString(texto);
  }

  Future<List<File>> lista() async {
    final d = await _dir();
    final l = d.listSync().whereType<File>().toList()..sort((a, b) => b.path.compareTo(a.path));
    return l;
  }
}
