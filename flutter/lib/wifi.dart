import 'dart:async';
import 'dart:io';
import 'dart:math';

import 'package:path_provider/path_provider.dart';

const paginaWifi = '''<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>EduAccesible</title><style>body{font-family:Arial;background:#FAF6EB;color:#2B2650;text-align:center;padding:24px}
button,input{font-size:20px;padding:14px;margin:8px;border-radius:12px;border:2px solid #895DCA}button{background:#895DCA;color:#fff}
#m{font-size:20px;margin-top:18px}</style></head><body><h1>Enviar a EduAccesible</h1>
<p>Código que aparece en la pantalla:</p><input id="c" inputmode="numeric" maxlength="4" size="4"><br>
<input id="f" type="file" accept=".pdf,.docx,.txt,.md,.csv,.png,.jpg,.jpeg,.bmp"><br><button onclick="e()">Enviar</button><div id="m"></div>
<script>async function e(){const f=document.getElementById('f').files[0],m=document.getElementById('m');
if(!f){m.textContent='Elige un archivo';return}m.textContent='Enviando...';
try{const r=await fetch('/subir',{method:'POST',headers:{'X-Nombre':encodeURIComponent(f.name),'X-Codigo':document.getElementById('c').value},body:f});
m.textContent=r.ok?'Enviado. Ya se está leyendo en EduAccesible.':(r.status==403?'Código incorrecto':'No se pudo enviar')}catch(x){m.textContent='Sin conexión'}}</script></body></html>''';

const _permitidas = ['pdf', 'docx', 'txt', 'md', 'csv', 'png', 'jpg', 'jpeg', 'bmp'];

/// Recibe archivos enviados desde el navegador de otro dispositivo en la misma red Wi-Fi.
class ServidorWifi {
  HttpServer? _srv;
  String codigo = '';
  String url = '';
  void Function(String ruta)? alRecibir;

  bool get activo => _srv != null;

  Future<String> _ip() async {
    try {
      for (final i in await NetworkInterface.list(type: InternetAddressType.IPv4)) {
        for (final a in i.addresses) {
          if (!a.isLoopback) return a.address;
        }
      }
    } catch (_) {}
    return '127.0.0.1';
  }

  Future<void> iniciar({int puerto = 8765}) async {
    codigo = Random().nextInt(10000).toString().padLeft(4, '0');
    final srv = await HttpServer.bind(InternetAddress.anyIPv4, puerto);
    _srv = srv;
    url = 'http://${await _ip()}:$puerto';
    final dir = Directory('${(await getApplicationDocumentsDirectory()).path}/entrada');
    await dir.create(recursive: true);
    srv.listen((req) async {
      try {
        if (req.method == 'GET') {
          req.response.headers.contentType = ContentType.html;
          req.response.write(paginaWifi);
        } else if (req.method == 'POST') {
          if (req.headers.value('X-Codigo') != codigo) {
            req.response.statusCode = 403;
          } else {
            var nombre = Uri.decodeComponent(req.headers.value('X-Nombre') ?? 'archivo').split(RegExp(r'[\\/]')).last;
            final ext = nombre.contains('.') ? nombre.split('.').last.toLowerCase() : '';
            if (!_permitidas.contains(ext)) {
              req.response.statusCode = 415;
            } else if (req.contentLength <= 0 || req.contentLength > 60 * 1024 * 1024) {
              req.response.statusCode = 413;
            } else {
              var f = File('${dir.path}/$nombre');
              if (await f.exists()) f = File('${dir.path}/${DateTime.now().millisecondsSinceEpoch}_$nombre');
              final sink = f.openWrite();
              await sink.addStream(req);
              await sink.close();
              req.response.write('ok');
              alRecibir?.call(f.path);
            }
          }
        } else {
          req.response.statusCode = 405;
        }
      } catch (_) {
        req.response.statusCode = 500;
      }
      await req.response.close();
    });
  }

  Future<void> detener() async {
    final s = _srv;
    _srv = null;
    await s?.close(force: true);
  }
}
