import 'dart:io';
import 'package:camera/camera.dart';
import 'package:flutter/material.dart';
import 'package:file_picker/file_picker.dart';
import 'package:image_picker/image_picker.dart';
import 'package:share_plus/share_plus.dart';
import 'config.dart';
import 'documentos.dart';
import 'wifi.dart';
import 'main.dart';
import 'manos.dart';
import 'senas.dart';
import 'servicios.dart';

enum Pant { menu, modo, materiales, ajustes, senas, botones }

const Map<String, String> titulos = {
  'texto': 'Leer texto',
  'letras': 'Letras y palabras',
  'numeros': 'Números',
  'figuras': 'Figuras geométricas',
  'objetos': 'Contar objetos',
};

/// Dibuja las manos que ve la app sobre la cámara: verde = clara, naranja = dudosa (se ignora).
class PuntosManos extends CustomPainter {
  final List<ManoVista> manos;
  final bool espejo;
  PuntosManos(this.manos, this.espejo);
  @override
  void paint(Canvas canvas, Size size) {
    for (final m in manos) {
      final p = Paint()..color = m.clara ? const Color(0xFF00E000) : const Color(0xFFFFA500);
      for (final q in m.puntos) {
        final x = (espejo ? 1 - q[0] : q[0]) * size.width;
        canvas.drawCircle(Offset(x, q[1] * size.height), 4, p);
      }
    }
  }

  @override
  bool shouldRepaint(covariant PuntosManos old) => true;
}

class Inicio extends StatefulWidget {
  const Inicio({super.key});
  @override
  State<Inicio> createState() => _InicioState();
}

class _InicioState extends State<Inicio> {
  final voz = Voz();
  final escucha = Escucha();
  final lector = Lector();
  final materiales = Materiales();
  final manos = Manos();
  final picker = ImagePicker();
  final wifi = ServidorWifi();
  final ajustes = AjustesApp();
  CameraController? cam;
  int indiceCamara = 0;
  Pant pant = Pant.menu;
  String modo = 'texto';
  String resultado = '';
  String estado = '';
  bool procesando = false;
  bool gestosActivos = false;
  bool vozActiva = false;
  bool practica = false;
  bool cambiandoCamara = false;
  List<File> archivos = [];

  CameraDescription? get descCamara => camaras.isEmpty ? null : camaras[indiceCamara % camaras.length];
  bool get esFrontal => descCamara?.lensDirection == CameraLensDirection.front;

  @override
  void initState() {
    super.initState();
    manos.alEjecutar = (s) => ejecutarGesto(s);
    escucha.alParcial = (t) {
      if (mounted) setState(() => estado = '🎤 Oyendo: $t');
    };
    escucha.alError = (e) {
      if (vozActiva && (e.contains('no_match') || e.contains('timeout'))) return; // normal cuando nadie habla
      if (mounted) setState(() => estado = '🎤 ${mensajeErrorVoz(e)}');
    };
    manos.alCambiar = () {
      if (mounted) setState(() {});
    };
    _arrancar();
  }

  Future<void> _arrancar() async {
    await voz.iniciar();
    await ajustes.cargar();
    if (mounted) setState(() {});
    await _abrirCamara();
    voz.hablar('EduAccesible iniciado. Elige una función en el menú.');
  }

  Future<void> _abrirCamara() async {
    final d = descCamara;
    if (d == null) return;
    final c = CameraController(d, ResolutionPreset.high, enableAudio: false);
    try {
      await c.initialize();
      cam = c;
    } catch (e) {
      estado = 'No se pudo abrir la cámara: $e';
    }
    if (mounted) setState(() {});
  }

  @override
  void dispose() {
    wifi.detener();
    escucha.detenerContinua();
    manos.detener(cam);
    cam?.dispose();
    super.dispose();
  }

  // ---------------------------------------------------------------- navegación
  void _ir(Pant p, [String? hablar]) {
    voz.detener();
    setState(() => pant = p);
    if (hablar != null) voz.hablar(hablar);
  }

  void abrirModo(String m) {
    modo = m;
    resultado = 'Apunta la cámara y presiona el botón de capturar.';
    _ir(Pant.modo, '${titulos[m]}. Apunta la cámara y presiona capturar.');
  }

  Future<void> abrirMateriales() async {
    archivos = await materiales.lista();
    _ir(Pant.materiales, 'Materiales guardados.');
  }

  void abrirSenas() {
    final lista = listaSenas();
    _ir(Pant.senas);
    voz.hablar('Estas son las señas. ${lista.map((s) => '${s.nombre}: ${s.como}.').join(' ')}');
  }

  void atras() => pant == Pant.menu ? voz.hablar('Ya estás en el menú principal.') : _ir(Pant.menu, 'Menú principal.');

  // ---------------------------------------------------------------- cámara
  Future<void> cambiarCamara() async {
    if (cambiandoCamara || camaras.length < 2) {
      voz.hablar(camaras.length < 2 ? 'Solo hay una cámara.' : 'Un momento.');
      return;
    }
    cambiandoCamara = true;
    final seguia = gestosActivos;
    await manos.detener(cam);
    final vieja = cam;
    setState(() => cam = null);
    await vieja?.dispose();
    indiceCamara = (indiceCamara + 1) % camaras.length;
    await _abrirCamara();
    if (seguia) await _iniciarManos();
    cambiandoCamara = false;
    voz.hablar(esFrontal ? 'Cámara frontal.' : 'Cámara trasera.');
  }

  // ---------------------------------------------------------------- señas de mano
  Future<bool> _iniciarManos() async {
    if (cam == null || !cam!.value.isInitialized || descCamara == null) return false;
    try {
      await manos.iniciar(cam!, descCamara!);
      return true;
    } catch (e) {
      setState(() => estado = 'Error de gestos: $e');
      return false;
    }
  }

  Future<void> activarGestos(bool activar) async {
    if (!activar) {
      await manos.detener(cam);
      setState(() => gestosActivos = false);
      voz.hablar('Gestos apagados.');
      return;
    }
    if (gestosActivos) {
      voz.hablar('Los gestos ya están activados.');
      return;
    }
    if (!await _iniciarManos()) {
      voz.hablar('No se pudieron iniciar los gestos. Revisa que la cámara esté disponible.');
      return;
    }
    setState(() => gestosActivos = true);
    voz.hablar('Gestos activados. Mantén la seña quieta un poco más de un segundo. Uno a cuatro dedos eligen las '
        'funciones uno a cuatro, la mano abierta cuenta objetos. Materiales: mano abierta y un dedo en la otra. '
        'Ajustes: mano abierta y dos dedos en la otra. Puño repite, dos puños capturan. '
        'Para oír todas las señas di: señas.');
  }

  /// Cada seña tiene su propia función (ver [senas]).
  void ejecutarGesto(String g) {
    final datos = senas[g];
    if (datos == null) return;
    if (datos.orden == 'senas') {
      practica = !practica;
      voz.hablar(practica
          ? 'Modo práctica de señas. Haz una seña y te digo qué hace, sin ejecutarla. Para salir, repite esta misma seña: tres dedos en cada mano.'
          : 'Modo práctica terminado. Las señas vuelven a ejecutar su función.');
      return;
    }
    if (practica && datos.orden != 'silencio') {
      voz.hablar('Esa seña es ${datos.como}. Sirve para ${datos.nombre}.');
      return;
    }
    ejecutarOrden(datos.orden, porGesto: true);
  }

  // ---------------------------------------------------------------- voz siempre activa
  Future<void> alternarVoz(bool activar) async {
    if (!activar) {
      await escucha.detenerContinua();
      setState(() => vozActiva = false);
      voz.hablar('Voz siempre activa apagada.');
      return;
    }
    if (vozActiva) {
      voz.hablar('La voz ya está siempre activa.');
      return;
    }
    final ok = await escucha.iniciarContinua((t) {
      final o = interpretarOrden(t);
      if (mounted) setState(() => estado = '🎤 Oí: $t  →  ${o ?? 'sin orden'}');
      if (o != null) ejecutarOrden(o);
    }, () => voz.hablando);
    if (!ok) {
      voz.hablar('No se pudo usar el micrófono. Revisa el permiso en los ajustes del teléfono.');
      return;
    }
    setState(() => vozActiva = true);
    voz.hablar('Voz siempre activa. Di una orden, por ejemplo capturar, atrás o inicio. Para apagarla di: desactivar voz.');
  }

  // ---------------------------------------------------------------- órdenes (voz, señas y botones ejecutan lo mismo)
  void ejecutarOrden(String o, {bool porGesto = false}) {
    if (o.startsWith('sena:')) {
      voz.hablar(fraseSena(o.substring(5)));
    } else if (o.startsWith('m_')) {
      abrirModo(o.substring(2));
    } else {
      switch (o) {
        case 'materiales': abrirMateriales();
        case 'ajustes': _ir(Pant.ajustes, 'Ajustes.');
        case 'capturar':
          if (porGesto) {
            voz.hablar('Quita las manos. Capturando.');
            Future.delayed(const Duration(milliseconds: 2800), capturar);
          } else {
            capturar();
          }
        case 'repetir': voz.hablar(voz.ultimo.isEmpty ? 'Todavía no hay nada para repetir.' : voz.ultimo, guardar: false);
        case 'silencio': voz.detener();
        case 'inicio': _ir(Pant.menu, 'Menú principal.');
        case 'atras': atras();
        case 'senas_lista': abrirSenas();
        case 'camara': cambiarCamara();
        case 'gestos_on': activarGestos(true);
        case 'gestos_off': activarGestos(false);
        case 'voz': alternarVoz(!vozActiva);
        case 'voz_on': alternarVoz(true);
        case 'voz_off': alternarVoz(false);
        case 'importar': importarImagen();
        case 'wifi': alternarWifi();
        case 'botones': abrirBotones();
        case 'orden': hablarOrden();
        case 'gestos': activarGestos(!gestosActivos);
        default: voz.hablar('No entendí esa orden.');
      }
    }
  }

  static String mensajeErrorVoz(String e) {
    if (e.contains('no_match')) return 'No te entendí. Habla más cerca y claro.';
    if (e.contains('timeout')) return 'No te escuché. Habla justo después de tocar el botón.';
    if (e.contains('permission')) return 'Falta el permiso del micrófono. Actívalo en Ajustes del teléfono.';
    if (e.contains('network') || e.contains('language')) {
      return 'El reconocimiento de voz necesita internet o el paquete de español sin conexión.';
    }
    return 'Error de voz: $e';
  }

  Future<void> hablarOrden() async {
    await voz.detener(); // para que el micrófono no oiga a la app
    setState(() => estado = '🎤 Escuchando... habla ahora');
    final ok = await escucha.escuchar((t) {
      final o = interpretarOrden(t);
      if (mounted) setState(() => estado = '🎤 Oí: "$t"  →  ${o ?? 'sin orden'}');
      if (o != null) {
        ejecutarOrden(o);
      } else {
        voz.hablar('Oí: $t. No es una orden que conozca.', guardar: false);
      }
    });
    if (!ok) {
      setState(() => estado = '🎤 No se pudo iniciar el micrófono');
      voz.hablar('No se pudo usar el micrófono. Revisa el permiso en los ajustes del teléfono.');
    }
  }

  // ---------------------------------------------------------------- botones laterales (editables)
  void ejecutarBoton(int i) => ejecutarOrden(ajustes.botones[i]);

  Future<void> abrirBotones() async {
    _ir(Pant.botones, 'Configurar botones laterales. Elige qué hace cada botón.');
  }

  Future<void> cambiarBoton(int i, String id) async {
    setState(() => ajustes.botones[i] = id);
    await ajustes.guardar();
    voz.hablar('Botón ${i + 1}: ${accionDe(id).nombre}.', guardar: false);
  }

  Future<void> restaurarBotones() async {
    setState(() => ajustes.botones = [...botonesDeFabrica]);
    await ajustes.guardar();
    voz.hablar('Botones restaurados: capturar, repetir, inicio y atrás.');
  }

  // ---------------------------------------------------------------- captura, importar y lectura
  Future<void> capturar() async {
    if (pant != Pant.modo) {
      voz.hablar('Primero elige una función del menú.');
      return;
    }
    if (cam == null || !cam!.value.isInitialized) {
      voz.hablar('La cámara no está disponible.');
      return;
    }
    if (procesando) return;
    final reanudar = gestosActivos;
    try {
      if (reanudar) await manos.detener(cam); // la foto y el análisis de manos no se llevan bien a la vez
      final foto = await cam!.takePicture();
      if (reanudar) await _iniciarManos();
      await analizar(foto.path, desdeCamara: true);
    } catch (e) {
      setState(() => resultado = 'Error: $e');
      voz.hablar('Ocurrió un error al capturar.');
      if (reanudar && !manos.activo) await _iniciarManos();
    }
  }

  /// Importar: imagen de la galería o documento (PDF con texto, Word, texto). Se puede pedir desde cualquier pantalla.
  Future<void> importarImagen() async {
    if (pant != Pant.modo) abrirModo(modo);
    if (!mounted) return;
    voz.hablar('Importar. Elige imagen o documento.', guardar: false);
    await showModalBottomSheet<void>(
      context: context,
      backgroundColor: crema,
      builder: (ctx) => SafeArea(
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          const SizedBox(height: 8),
          const Text('Importar', style: TextStyle(fontSize: 20, fontWeight: FontWeight.bold, color: morado)),
          ListTile(
            leading: const Text('🖼', style: TextStyle(fontSize: 28)),
            title: const Text('Imagen de la galería', style: TextStyle(fontSize: 17, fontWeight: FontWeight.w600)),
            subtitle: const Text('Se analiza según la función abierta'),
            onTap: () {
              Navigator.pop(ctx);
              _elegirImagen();
            },
          ),
          ListTile(
            leading: const Text('📄', style: TextStyle(fontSize: 28)),
            title: const Text('Documento o archivo', style: TextStyle(fontSize: 17, fontWeight: FontWeight.w600)),
            subtitle: const Text('PDF con texto, Word (.docx), texto (.txt) o imagen'),
            onTap: () {
              Navigator.pop(ctx);
              _elegirDocumento();
            },
          ),
          ListTile(
            leading: const Text('📶', style: TextStyle(fontSize: 28)),
            title: const Text('Recibir por Wi-Fi', style: TextStyle(fontSize: 17, fontWeight: FontWeight.w600)),
            subtitle: const Text('Envía archivos desde otro dispositivo'),
            onTap: () {
              Navigator.pop(ctx);
              alternarWifi();
            },
          ),
          const SizedBox(height: 8),
        ]),
      ),
    );
  }

  Future<void> _elegirImagen() async {
    try {
      final x = await picker.pickImage(source: ImageSource.gallery);
      if (x == null) return;
      await analizar(x.path, desdeCamara: false);
    } catch (e) {
      setState(() => resultado = 'Error: $e');
      voz.hablar('No se pudo abrir la imagen.');
    }
  }

  /// Recibir archivos por Wi-Fi desde el navegador de otro dispositivo.
  Future<void> alternarWifi() async {
    if (wifi.activo) {
      await wifi.detener();
      setState(() => resultado = 'Recepción por Wi-Fi apagada.');
      voz.hablar('Recepción por Wi-Fi apagada.');
      return;
    }
    try {
      wifi.alRecibir = (ruta) {
        if (!mounted) return;
        voz.hablar('Llegó un archivo.', guardar: false);
        abrirArchivo(ruta);
      };
      await wifi.iniciar();
    } catch (e) {
      setState(() => resultado = 'No se pudo activar el Wi-Fi: $e');
      voz.hablar('No se pudo activar el Wi-Fi.');
      return;
    }
    if (pant != Pant.modo) abrirModo(modo);
    final dir = wifi.url.replaceAll('http://', '');
    setState(() => resultado = 'Abre en el otro dispositivo (misma red Wi-Fi):\n${wifi.url}\nCódigo: ${wifi.codigo}');
    voz.hablar('Recepción por Wi-Fi activa. En el otro dispositivo, conectado a la misma red, abre el navegador y escribe ${dir.replaceAll('.', ' punto ').replaceAll(':', ' dos puntos ')}. El código es ${wifi.codigo.split('').join(' ')}.');
  }

  Future<void> abrirArchivo(String ruta) async {
    final ext = ruta.split('.').last.toLowerCase();
    if (extensionesImagen.contains(ext)) {
      await analizar(ruta, desdeCamara: false);
    } else {
      await _leerDocumento(ruta);
    }
  }

  Future<void> _elegirDocumento() async {
    try {
      final r = await FilePicker.platform.pickFiles(
          type: FileType.custom, allowedExtensions: [...extensionesTexto, ...extensionesImagen]);
      final ruta = r?.files.single.path;
      if (ruta == null) return;
      final ext = ruta.split('.').last.toLowerCase();
      if (extensionesImagen.contains(ext)) {
        await analizar(ruta, desdeCamara: false);
      } else {
        await _leerDocumento(ruta);
      }
    } catch (e) {
      setState(() => resultado = 'Error: $e');
      voz.hablar('No se pudo abrir el archivo.');
    }
  }

  Future<void> _leerDocumento(String ruta) async {
    if (procesando) return;
    setState(() {
      procesando = true;
      resultado = 'Abriendo el documento...';
    });
    voz.hablar('Abriendo el documento.', guardar: false);
    try {
      final t = await leerDocumento(ruta);
      if (pant != Pant.modo) return;
      if (t.isEmpty) {
        const m = 'No encontré texto en este documento. Si es un PDF escaneado, ábrelo como imagen o tómale una foto.';
        setState(() => resultado = m);
        voz.hablar(m);
      } else {
        setState(() => resultado = t);
        voz.hablar(t);
        await materiales.guardar('documento', t);
      }
    } catch (e) {
      setState(() => resultado = 'No pude abrir el documento: $e');
      voz.hablar('No pude abrir el documento. Puede estar dañado o protegido.');
    } finally {
      if (mounted) setState(() => procesando = false);
    }
  }

  Future<void> analizar(String ruta, {required bool desdeCamara}) async {
    if (procesando) return;
    setState(() {
      procesando = true;
      resultado = 'Analizando...';
    });
    voz.hablar('Analizando.', guardar: false);
    final modoAlEmpezar = modo;
    try {
      String t;
      switch (modoAlEmpezar) {
        case 'letras': t = await lector.letras(ruta);
        case 'numeros': t = await lector.numeros(ruta);
        case 'objetos': t = await lector.objetos(ruta);
        case 'figuras': t = await lector.figuras(ruta, recorte: desdeCamara);
        default: t = await lector.texto(ruta);
      }
      if (pant != Pant.modo) return; // saliste de la función mientras analizaba: no leer el resultado
      setState(() => resultado = t);
      voz.hablar(t);
      if (!t.startsWith('No ') && modoAlEmpezar != 'figuras' && modoAlEmpezar != 'objetos') {
        await materiales.guardar(modoAlEmpezar, t);
      }
    } catch (e) {
      setState(() => resultado = 'Error: $e');
      voz.hablar('Ocurrió un error al analizar.');
    } finally {
      if (mounted) setState(() => procesando = false);
    }
  }

  // ---------------------------------------------------------------- interfaz
  bool get horizontal => MediaQuery.of(context).orientation == Orientation.landscape;

  Widget tarjeta(String icono, String titulo, String? pista, Color color, VoidCallback f, {Color fg = Colors.white}) =>
      Material(
        color: color,
        borderRadius: BorderRadius.circular(22),
        elevation: 2,
        shadowColor: color.withOpacity(0.5),
        child: InkWell(
          borderRadius: BorderRadius.circular(22),
          onTap: f,
          child: Padding(
            padding: const EdgeInsets.all(10),
            child: Column(mainAxisAlignment: MainAxisAlignment.center, children: [
              Text(icono, style: const TextStyle(fontSize: 34)),
              const SizedBox(height: 4),
              Text(titulo,
                  textAlign: TextAlign.center,
                  style: TextStyle(color: fg, fontWeight: FontWeight.bold, fontSize: 16, height: 1.1)),
              if (pista != null) ...[
                const SizedBox(height: 3),
                Text(pista, textAlign: TextAlign.center, style: TextStyle(color: fg.withOpacity(0.85), fontSize: 12)),
              ],
            ]),
          ),
        ),
      );

  Widget pastilla(String icono, String t, VoidCallback f, {bool marcada = false}) => Padding(
        padding: const EdgeInsets.symmetric(horizontal: 4),
        child: ActionChip(
          avatar: Text(icono, style: const TextStyle(fontSize: 16)),
          label: Text(t, style: TextStyle(fontWeight: FontWeight.w600, color: marcada ? Colors.white : texto)),
          backgroundColor: marcada ? morado : Colors.white,
          side: BorderSide(color: marcada ? morado : lila),
          onPressed: f,
        ),
      );

  Widget barraRapida() => SingleChildScrollView(
        scrollDirection: Axis.horizontal,
        padding: const EdgeInsets.symmetric(vertical: 6),
        child: Row(mainAxisAlignment: MainAxisAlignment.center, children: [
          pastilla('🖐', gestosActivos ? 'Gestos: sí' : 'Gestos: no', () => activarGestos(!gestosActivos), marcada: gestosActivos),
          pastilla('🎤', vozActiva ? 'Voz activa' : 'Voz: apagada', () => alternarVoz(!vozActiva), marcada: vozActiva),
          pastilla('🗣', 'Una orden', hablarOrden),
          pastilla('🔄', 'Cámara', cambiarCamara),
          pastilla('✋', 'Señas', abrirSenas),
        ]),
      );

  Widget opcionLarga(String icono, String titulo, String pista, Color color, VoidCallback f, {Color fg = Colors.white}) =>
      Material(
        color: color,
        borderRadius: BorderRadius.circular(18),
        elevation: 2,
        shadowColor: color.withOpacity(0.5),
        child: InkWell(
          borderRadius: BorderRadius.circular(18),
          onTap: f,
          child: Padding(
            padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
            child: Row(children: [
              Container(
                width: 46,
                height: 46,
                alignment: Alignment.center,
                decoration: BoxDecoration(color: Colors.white.withOpacity(0.28), borderRadius: BorderRadius.circular(12)),
                child: Text(icono, style: const TextStyle(fontSize: 26)),
              ),
              const SizedBox(width: 14),
              Expanded(
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Text(titulo, style: TextStyle(color: fg, fontWeight: FontWeight.bold, fontSize: 18, height: 1.1)),
                  Text(pista, style: TextStyle(color: fg.withOpacity(0.85), fontSize: 12)),
                ]),
              ),
            ]),
          ),
        ),
      );

  Widget menu() {
    final opciones = <Widget>[
      opcionLarga('📖', '1. Leer texto', '☝ un dedo', morado, () => abrirModo('texto')),
      opcionLarga('🅰', '2. Letras y palabras', '✌ dos dedos', azul, () => abrirModo('letras')),
      opcionLarga('🔢', '3. Números', 'tres dedos', lila, () => abrirModo('numeros'), fg: texto),
      opcionLarga('🔷', '4. Figuras geométricas', 'cuatro dedos', morado, () => abrirModo('figuras')),
      opcionLarga('📦', '5. Contar objetos', 'mano abierta', azul, () => abrirModo('objetos')),
      opcionLarga('📁', '6. Materiales guardados', 'mano abierta + un dedo', morado, abrirMateriales),
      opcionLarga('⚙', '7. Ajustes', 'mano abierta + dos dedos', lila, () => _ir(Pant.ajustes, 'Ajustes.'), fg: texto),
    ];
    final encabezado = const Padding(
      padding: EdgeInsets.only(top: 2, bottom: 8),
      child: Text('La información también se escucha',
          textAlign: TextAlign.center, style: TextStyle(fontSize: 14, fontStyle: FontStyle.italic, color: texto)),
    );
    return Column(children: [
      encabezado,
      Expanded(
        child: horizontal
            ? GridView.extent(
                maxCrossAxisExtent: 420,
                mainAxisSpacing: 10,
                crossAxisSpacing: 12,
                childAspectRatio: 4.2,
                padding: const EdgeInsets.symmetric(horizontal: 12),
                children: opciones,
              )
            : ListView.separated(
                padding: const EdgeInsets.symmetric(horizontal: 12),
                itemCount: opciones.length,
                separatorBuilder: (_, __) => const SizedBox(height: 10),
                itemBuilder: (_, i) => opciones[i],
              ),
      ),
      barraRapida(),
    ]);
  }

  Widget vistaCamara() {
    if (cam == null || !cam!.value.isInitialized) {
      return const Center(child: Text('Cámara no disponible', style: TextStyle(color: Colors.white)));
    }
    return Center(
      child: Stack(children: [
        CameraPreview(cam!),
        if (modo == 'figuras')
          Positioned.fill(
            child: FractionallySizedBox(
              widthFactor: 0.84,
              heightFactor: 0.84,
              child: Container(decoration: BoxDecoration(border: Border.all(color: const Color(0xFF00C800), width: 2))),
            ),
          ),
        if (gestosActivos) Positioned.fill(child: CustomPaint(painter: PuntosManos(manos.manos, esFrontal))),
      ]),
    );
  }

  Widget tarjetaResultado() => Container(
        width: double.infinity,
        constraints: const BoxConstraints(minHeight: 70),
        padding: const EdgeInsets.all(12),
        decoration: BoxDecoration(color: Colors.white, borderRadius: BorderRadius.circular(16), border: Border.all(color: lila)),
        child: procesando
            ? const Row(children: [
                SizedBox(width: 20, height: 20, child: CircularProgressIndicator(strokeWidth: 2)),
                SizedBox(width: 12),
                Text('Analizando...', style: TextStyle(fontSize: 16, color: texto)),
              ])
            : Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Expanded(child: Text(resultado, style: const TextStyle(fontSize: 16, color: texto, height: 1.25))),
                if (resultado.length > 40 && !resultado.startsWith('Apunta'))
                  IconButton(
                    visualDensity: VisualDensity.compact,
                    icon: const Icon(Icons.share, color: azul),
                    tooltip: 'Compartir',
                    onPressed: () => Share.share(resultado, subject: 'EduAccesible'),
                  ),
              ]),
      );

  Widget botonesModo() => Row(mainAxisAlignment: MainAxisAlignment.spaceEvenly, children: [
        IconButton.filledTonal(onPressed: importarImagen, icon: const Icon(Icons.attach_file), tooltip: 'Importar imagen o documento'),
        IconButton.filledTonal(onPressed: () => ejecutarOrden('repetir'), icon: const Icon(Icons.replay), tooltip: 'Repetir'),
        SizedBox(
          width: 64,
          height: 64,
          child: FilledButton(
            style: FilledButton.styleFrom(backgroundColor: morado, shape: const CircleBorder(), padding: EdgeInsets.zero),
            onPressed: () => capturar(),
            child: const Icon(Icons.camera_alt, size: 30, color: Colors.white),
          ),
        ),
        IconButton.filledTonal(onPressed: cambiarCamara, icon: const Icon(Icons.cameraswitch), tooltip: 'Cambiar cámara'),
        IconButton.filledTonal(onPressed: () => ejecutarOrden('silencio'), icon: const Icon(Icons.volume_off), tooltip: 'Silencio'),
      ]);

  Widget vistaModo() {
    final camara = ClipRRect(
      borderRadius: BorderRadius.circular(20),
      child: Container(color: Colors.black, width: double.infinity, child: vistaCamara()),
    );
    final titulo = Text(titulos[modo] ?? '', style: const TextStyle(fontSize: 20, fontWeight: FontWeight.bold, color: morado));
    if (horizontal) {
      return Padding(
        padding: const EdgeInsets.all(10),
        child: Row(children: [
          Expanded(flex: 5, child: camara),
          const SizedBox(width: 12),
          Expanded(
            flex: 4,
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              titulo,
              const SizedBox(height: 8),
              Expanded(child: SingleChildScrollView(child: tarjetaResultado())),
              const SizedBox(height: 8),
              botonesModo(),
            ]),
          ),
        ]),
      );
    }
    return Padding(
      padding: const EdgeInsets.all(10),
      child: Column(children: [
        titulo,
        const SizedBox(height: 6),
        Expanded(flex: 5, child: camara),
        const SizedBox(height: 8),
        Expanded(flex: 2, child: SingleChildScrollView(child: tarjetaResultado())),
        const SizedBox(height: 8),
        botonesModo(),
      ]),
    );
  }

  Widget vistaMateriales() => Column(children: [
        const Padding(
          padding: EdgeInsets.all(8),
          child: Text('Materiales guardados', style: TextStyle(fontSize: 20, fontWeight: FontWeight.bold, color: morado)),
        ),
        Expanded(
          child: archivos.isEmpty
              ? const Center(child: Text('Todavía no hay materiales.', style: TextStyle(fontSize: 16)))
              : ListView(padding: const EdgeInsets.symmetric(horizontal: 12), children: [
                  for (final f in archivos)
                    Card(
                      color: Colors.white,
                      child: ListTile(
                        title: Text(f.uri.pathSegments.last.replaceAll('.txt', '').split('_').last.toUpperCase(),
                            style: const TextStyle(fontWeight: FontWeight.bold, color: morado)),
                        subtitle: Text(f.readAsStringSync(), maxLines: 2, overflow: TextOverflow.ellipsis),
                        trailing: Row(mainAxisSize: MainAxisSize.min, children: [
                          IconButton(
                            icon: const Icon(Icons.share, color: azul),
                            tooltip: 'Compartir',
                            onPressed: () => Share.share(f.readAsStringSync(), subject: 'EduAccesible'),
                          ),
                          const Icon(Icons.volume_up, color: azul),
                        ]),
                        onTap: () => voz.hablar(f.readAsStringSync()),
                      ),
                    ),
                ]),
        ),
        Padding(
          padding: const EdgeInsets.all(8),
          child: FilledButton.icon(
            style: FilledButton.styleFrom(backgroundColor: morado, padding: const EdgeInsets.symmetric(horizontal: 18, vertical: 12)),
            onPressed: importarImagen,
            icon: const Icon(Icons.attach_file),
            label: const Text('Importar imagen o documento', style: TextStyle(fontSize: 15)),
          ),
        ),
      ]);

  Widget vistaAjustes() {
    final items = <Widget>[
      tarjeta('🖐', gestosActivos ? 'Gestos: activados' : 'Gestos: apagados', 'Señas de mano con la cámara', azul, () => activarGestos(!gestosActivos)),
      tarjeta('🎤', vozActiva ? 'Voz siempre activa: sí' : 'Voz siempre activa: no', 'Órdenes sin tocar la pantalla', morado, () => alternarVoz(!vozActiva)),
      tarjeta('🗣', 'Dar una orden por voz', 'Una sola orden', lila, hablarOrden, fg: texto),
      tarjeta('🔘', 'Botones laterales', 'Cambia lo que hace cada uno', morado, abrirBotones),
      tarjeta('🔄', 'Cambiar de cámara', 'Frontal o trasera', azul, cambiarCamara),
      tarjeta('✋', 'Ver y escuchar las señas', 'Lista completa', morado, abrirSenas),
      tarjeta('⏹', 'Silencio', 'Corta la lectura', lila, () => voz.detener(), fg: texto),
    ];
    return Column(children: [
      const Padding(
        padding: EdgeInsets.all(8),
        child: Text('Ajustes', style: TextStyle(fontSize: 20, fontWeight: FontWeight.bold, color: morado)),
      ),
      Expanded(
        child: GridView.extent(
          maxCrossAxisExtent: 230,
          mainAxisSpacing: 12,
          crossAxisSpacing: 12,
          childAspectRatio: horizontal ? 1.5 : 1.15,
          padding: const EdgeInsets.symmetric(horizontal: 14),
          children: items,
        ),
      ),
      const Padding(
        padding: EdgeInsets.all(12),
        child: Text(
            'La cámara, el micrófono y los audífonos (cable o Bluetooth) son los del propio teléfono. '
            'Para las señas es más cómoda la cámara frontal.',
            textAlign: TextAlign.center,
            style: TextStyle(fontSize: 12)),
      ),
    ]);
  }

  /// Los 4 botones laterales, como en el dispositivo físico. Lo que hacen se puede cambiar en Ajustes.
  Widget barraLateral() {
    const colores = [Color(0xFF5273BA), Color(0xFF895DCA), Color(0xFF5273BA), Color(0xFF895DCA)];
    return Container(
      width: 84,
      margin: const EdgeInsets.fromLTRB(0, 6, 8, 6),
      padding: const EdgeInsets.symmetric(vertical: 8, horizontal: 6),
      decoration: BoxDecoration(color: Colors.white.withOpacity(0.6), borderRadius: BorderRadius.circular(22)),
      child: Column(mainAxisAlignment: MainAxisAlignment.spaceEvenly, children: [
        for (var i = 0; i < 4; i++)
          Expanded(
            child: Padding(
              padding: const EdgeInsets.symmetric(vertical: 4),
              child: Semantics(
                button: true,
                label: '${accionDe(ajustes.botones[i]).nombre}: ${accionDe(ajustes.botones[i]).descripcion}',
                child: Material(
                  color: colores[i],
                  borderRadius: BorderRadius.circular(18),
                  elevation: 2,
                  child: InkWell(
                    borderRadius: BorderRadius.circular(18),
                    onTap: () => ejecutarBoton(i),
                    onLongPress: () => voz.hablar(
                        'Botón ${i + 1}: ${accionDe(ajustes.botones[i]).nombre}, ${accionDe(ajustes.botones[i]).descripcion}.',
                        guardar: false),
                    child: SizedBox.expand(
                      child: FittedBox(
                        fit: BoxFit.scaleDown,
                        child: Padding(
                          padding: const EdgeInsets.all(6),
                          child: Column(mainAxisAlignment: MainAxisAlignment.center, children: [
                            Text(accionDe(ajustes.botones[i]).icono, style: const TextStyle(fontSize: 34)),
                            Text(accionDe(ajustes.botones[i]).nombre,
                                style: const TextStyle(color: Colors.white, fontSize: 11, fontWeight: FontWeight.bold)),
                          ]),
                        ),
                      ),
                    ),
                  ),
                ),
              ),
            ),
          ),
      ]),
    );
  }

  Widget vistaBotones() => ListView(padding: const EdgeInsets.all(14), children: [
        const Text('Botones laterales', style: TextStyle(fontSize: 20, fontWeight: FontWeight.bold, color: morado)),
        const SizedBox(height: 6),
        const Text('Elige qué hace cada botón, de arriba hacia abajo. De fábrica son: capturar, repetir, inicio y atrás, '
            'las funciones que lleva el dispositivo escritas en braille. Mantén pulsado un botón para oír qué hace.',
            style: TextStyle(fontSize: 14)),
        const SizedBox(height: 12),
        for (var i = 0; i < 4; i++)
          Card(
            color: Colors.white,
            child: Padding(
              padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 6),
              child: Row(children: [
                Text('Botón ${i + 1}', style: const TextStyle(fontWeight: FontWeight.bold, color: morado, fontSize: 16)),
                const SizedBox(width: 14),
                Expanded(
                  child: DropdownButton<String>(
                    isExpanded: true,
                    value: ajustes.botones[i],
                    underline: const SizedBox(),
                    items: [
                      for (final a in acciones)
                        DropdownMenuItem(value: a.id, child: Text('${a.icono}  ${a.nombre}', style: const TextStyle(fontSize: 16))),
                    ],
                    onChanged: (v) {
                      if (v != null) cambiarBoton(i, v);
                    },
                  ),
                ),
              ]),
            ),
          ),
        const SizedBox(height: 10),
        FilledButton.icon(
          style: FilledButton.styleFrom(backgroundColor: azul, padding: const EdgeInsets.symmetric(vertical: 14)),
          onPressed: restaurarBotones,
          icon: const Icon(Icons.restore),
          label: const Text('Volver a los de fábrica', style: TextStyle(fontSize: 16)),
        ),
      ]);

  Widget vistaSenas() => ListView(padding: const EdgeInsets.all(16), children: [
        const Text('Señas de mano', style: TextStyle(fontSize: 20, fontWeight: FontWeight.bold, color: morado)),
        const SizedBox(height: 8),
        const Text('Mantén la seña quieta cerca de un segundo y medio. Pregunta por voz: «¿cuál es la seña de materiales?»'),
        const SizedBox(height: 12),
        for (final s in listaSenas())
          Card(
            color: Colors.white,
            child: ListTile(
              title: Text(s.nombre[0].toUpperCase() + s.nombre.substring(1),
                  style: const TextStyle(fontWeight: FontWeight.bold, color: morado)),
              subtitle: Text(s.como),
            ),
          ),
      ]);

  @override
  Widget build(BuildContext context) {
    final cuerpo = switch (pant) {
      Pant.menu => menu(),
      Pant.modo => vistaModo(),
      Pant.materiales => vistaMateriales(),
      Pant.ajustes => vistaAjustes(),
      Pant.senas => vistaSenas(),
      Pant.botones => vistaBotones(),
    };
    final lineas = [if (estado.isNotEmpty) estado, if (gestosActivos) manos.estadoTexto()];
    return PopScope(
      canPop: pant == Pant.menu,
      onPopInvokedWithResult: (ok, _) {
        if (!ok) atras();
      },
      child: Scaffold(
        appBar: AppBar(
          backgroundColor: crema,
          centerTitle: true,
          toolbarHeight: horizontal ? 48 : 56,
          title: const Text.rich(TextSpan(children: [
            TextSpan(text: 'Edu', style: TextStyle(color: azul, fontWeight: FontWeight.bold, fontSize: 26)),
            TextSpan(text: 'Accesible', style: TextStyle(color: morado, fontWeight: FontWeight.bold, fontSize: 26)),
          ])),
          actions: [
            if (pant != Pant.menu) IconButton(icon: const Icon(Icons.home_rounded, color: morado), onPressed: () => ejecutarOrden('inicio')),
          ],
        ),
        body: SafeArea(
          child: Row(children: [
            Expanded(child: cuerpo),
            barraLateral(),
          ]),
        ),
        bottomNavigationBar: lineas.isEmpty
            ? null
            : SafeArea(
                child: Container(
                  width: double.infinity,
                  margin: const EdgeInsets.fromLTRB(10, 0, 10, 8),
                  padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
                  decoration: BoxDecoration(color: lila.withOpacity(0.5), borderRadius: BorderRadius.circular(12)),
                  child: Text(lineas.join('\n'), textAlign: TextAlign.center, style: const TextStyle(fontSize: 13, color: texto)),
                ),
              ),
      ),
    );
  }
}
