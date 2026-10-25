import 'dart:io';
import 'package:flutter_tts/flutter_tts.dart';
import 'package:speech_to_text/speech_to_text.dart' as stt;
import 'package:google_mlkit_text_recognition/google_mlkit_text_recognition.dart';
import 'package:google_mlkit_object_detection/google_mlkit_object_detection.dart';
import 'package:path_provider/path_provider.dart';

/// Voz que lee (TextToSpeech de Android). Se puede cortar con [detener].
class Voz {
  final FlutterTts _tts = FlutterTts();
  String ultimo = '';
  Future<void> iniciar() async {
    await _tts.setLanguage('es-ES');
    await _tts.setSpeechRate(0.5);
    await _tts.awaitSpeakCompletion(false);
  }

  Future<void> hablar(String t) async {
    ultimo = t;
    await _tts.stop();
    await _tts.speak(t);
  }

  Future<void> detener() => _tts.stop();
}

/// Reconocimiento de voz del teléfono (órdenes). Con internet usa Google; hay voces sin internet descargables.
class Escucha {
  final stt.SpeechToText _stt = stt.SpeechToText();
  bool listo = false;
  Future<bool> iniciar() async => listo = await _stt.initialize();
  Future<void> escuchar(void Function(String) alTerminar) async {
    if (!listo && !await iniciar()) return;
    await _stt.listen(
      localeId: 'es_ES',
      listenFor: const Duration(seconds: 8),
      pauseFor: const Duration(seconds: 2),
      onResult: (r) {
        if (r.finalResult) alTerminar(r.recognizedWords);
      },
    );
  }

  Future<void> parar() => _stt.stop();
}

class Lector {
  final TextRecognizer _ocr = TextRecognizer(script: TextRecognitionScript.latin);
  final ObjectDetector _obj = ObjectDetector(
      options: ObjectDetectorOptions(mode: DetectionMode.single, classifyObjects: true, multipleObjects: true));

  Future<String> texto(String ruta) async => (await _ocr.processImage(InputImage.fromFilePath(ruta))).text.trim();

  Future<String> letras(String ruta) async {
    final t = await texto(ruta);
    final pal = RegExp(r'[A-Za-zÁÉÍÓÚÜÑáéíóúüñ]+').allMatches(t).map((m) => m.group(0)!).toList();
    if (pal.isEmpty) return '';
    return pal.map((p) => p.length == 1 ? 'la letra $p' : '$p, ${p.split('').join(' ')}').join('. ');
  }

  Future<String> numeros(String ruta) async {
    final t = await texto(ruta);
    final n = RegExp(r'\d+(?:[.,]\d+)?').allMatches(t).map((m) => m.group(0)!).toList();
    return n.isEmpty ? '' : n.join(', ');
  }

  Future<String> objetos(String ruta) async {
    final o = await _obj.processImage(InputImage.fromFilePath(ruta));
    if (o.isEmpty) return 'No detecté objetos.';
    return 'Se detectaron ${o.length} objetos.';
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
