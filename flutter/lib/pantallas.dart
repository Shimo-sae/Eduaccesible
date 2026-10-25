import 'dart:io';
import 'package:camera/camera.dart';
import 'package:flutter/material.dart';
import 'main.dart';
import 'senas.dart';
import 'servicios.dart';

enum Pant { menu, modo, materiales, ajustes, senas }

const Map<String, String> titulos = {
  'texto': 'Leer texto',
  'letras': 'Reconocer letras y palabras',
  'numeros': 'Reconocer números',
  'figuras': 'Figuras geométricas',
  'objetos': 'Contar objetos',
};

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
  CameraController? cam;
  Pant pant = Pant.menu;
  String modo = 'texto';
  String resultado = '';
  String estado = '';
  bool procesando = false;
  List<File> archivos = [];

  @override
  void initState() {
    super.initState();
    _arrancar();
  }

  Future<void> _arrancar() async {
    await voz.iniciar();
    // Los permisos de cámara y micrófono los pide el propio plugin de cámara y de voz al usarlos.
    if (camaras.isNotEmpty) {
      cam = CameraController(camaras.first, ResolutionPreset.high, enableAudio: false);
      try {
        await cam!.initialize();
      } catch (e) {
        estado = 'No se pudo abrir la cámara: $e';
      }
      if (mounted) setState(() {});
    }
    voz.hablar('EduAccesible iniciado. Elige una función en el menú.');
  }

  @override
  void dispose() {
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
    resultado = 'Apunta la cámara y presiona Capturar.';
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

  // ---------------------------------------------------------------- órdenes (voz y señas ejecutan lo mismo)
  void ejecutarOrden(String o) {
    if (o.startsWith('sena:')) {
      voz.hablar(fraseSena(o.substring(5)));
    } else if (o.startsWith('m_')) {
      abrirModo(o.substring(2));
    } else {
      switch (o) {
        case 'materiales': abrirMateriales();
        case 'ajustes': _ir(Pant.ajustes, 'Ajustes.');
        case 'capturar': capturar();
        case 'repetir': voz.hablar(voz.ultimo.isEmpty ? 'Todavía no hay nada para repetir.' : voz.ultimo);
        case 'silencio': voz.detener();
        case 'inicio': _ir(Pant.menu, 'Menú principal.');
        case 'atras': atras();
        case 'senas_lista': abrirSenas();
        case 'importar': voz.hablar('Importar imágenes todavía no está en esta versión.');
        default: voz.hablar('Esa orden todavía no está en la versión de celular.');
      }
    }
  }

  Future<void> hablarOrden() async {
    setState(() => estado = '🎤 Escuchando...');
    await escucha.escuchar((t) {
      final o = interpretarOrden(t);
      setState(() => estado = '🎤 Oí: $t  →  ${o ?? 'sin orden'}');
      if (o != null) {
        ejecutarOrden(o);
      } else {
        voz.hablar('No entendí. Intenta de nuevo.');
      }
    });
  }

  // ---------------------------------------------------------------- captura y lectura
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
    setState(() {
      procesando = true;
      resultado = 'Analizando...';
    });
    voz.hablar('Analizando.');
    try {
      final foto = await cam!.takePicture();
      String t;
      switch (modo) {
        case 'letras': t = await lector.letras(foto.path);
        case 'numeros': t = await lector.numeros(foto.path);
        case 'objetos': t = await lector.objetos(foto.path);
        case 'figuras': t = 'Las figuras geométricas todavía no están en la versión de celular.';
        default: t = await lector.texto(foto.path);
      }
      if (t.isEmpty) t = 'No encontré nada. Acerca la cámara y mejora la luz.';
      setState(() => resultado = t);
      voz.hablar(t);
      if (modo != 'figuras' && !t.startsWith('No encontré')) await materiales.guardar(modo, t);
    } catch (e) {
      setState(() => resultado = 'Error: $e');
      voz.hablar('Ocurrió un error al analizar.');
    } finally {
      if (mounted) setState(() => procesando = false);
    }
  }

  // ---------------------------------------------------------------- interfaz
  Widget boton(String t, Color c, VoidCallback f, {Color fg = Colors.white, double size = 17}) => Padding(
        padding: const EdgeInsets.symmetric(vertical: 5, horizontal: 16),
        child: SizedBox(
          width: double.infinity,
          child: FilledButton(
            style: FilledButton.styleFrom(
                backgroundColor: c, foregroundColor: fg, padding: const EdgeInsets.symmetric(vertical: 16),
                shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12))),
            onPressed: f,
            child: Text(t, style: TextStyle(fontSize: size, fontWeight: FontWeight.bold)),
          ),
        ),
      );

  Widget menu() => ListView(children: [
        const SizedBox(height: 8),
        const Center(child: Text('¿Qué quieres hacer?', style: TextStyle(fontSize: 20, fontWeight: FontWeight.bold, color: texto))),
        const SizedBox(height: 8),
        boton('📖  1. Leer texto', morado, () => abrirModo('texto')),
        boton('🅰  2. Reconocer letras y palabras', azul, () => abrirModo('letras')),
        boton('123  3. Reconocer números', lila, () => abrirModo('numeros'), fg: texto),
        boton('🔷  4. Figuras geométricas', morado, () => abrirModo('figuras')),
        boton('🔢  5. Contar objetos', azul, () => abrirModo('objetos')),
        boton('📁  6. Materiales guardados', morado, abrirMateriales),
        boton('⚙  7. Ajustes', lila, () => _ir(Pant.ajustes, 'Ajustes.'), fg: texto),
        const SizedBox(height: 6),
        boton('🎤  Dar una orden por voz', azul, hablarOrden, size: 15),
        boton('🖐  Ver y escuchar las señas', lila, abrirSenas, fg: texto, size: 15),
      ]);

  Widget vistaModo() => Column(children: [
        Text(titulos[modo] ?? '', style: const TextStyle(fontSize: 20, fontWeight: FontWeight.bold, color: morado)),
        Expanded(
          child: Container(
            margin: const EdgeInsets.all(10),
            color: Colors.black,
            child: (cam != null && cam!.value.isInitialized)
                ? Center(child: CameraPreview(cam!))
                : const Center(child: Text('Cámara no disponible', style: TextStyle(color: Colors.white))),
          ),
        ),
        Padding(
          padding: const EdgeInsets.symmetric(horizontal: 16),
          child: Text(resultado, maxLines: 4, overflow: TextOverflow.ellipsis, style: const TextStyle(fontSize: 16, color: texto)),
        ),
        Row(children: [
          Expanded(child: boton('📷 Capturar', azul, capturar, size: 15)),
          Expanded(child: boton('▶ Repetir', morado, () => ejecutarOrden('repetir'), size: 15)),
        ]),
      ]);

  Widget vistaMateriales() => Column(children: [
        const Text('Materiales guardados', style: TextStyle(fontSize: 20, fontWeight: FontWeight.bold, color: morado)),
        Expanded(
          child: archivos.isEmpty
              ? const Center(child: Text('Todavía no hay materiales.'))
              : ListView(children: [
                  for (final f in archivos)
                    ListTile(
                      title: Text(f.uri.pathSegments.last.replaceAll('.txt', '')),
                      subtitle: Text(f.readAsStringSync(), maxLines: 2, overflow: TextOverflow.ellipsis),
                      trailing: const Icon(Icons.volume_up),
                      onTap: () => voz.hablar(f.readAsStringSync()),
                    ),
                ]),
        ),
      ]);

  Widget vistaAjustes() => ListView(children: [
        const Center(child: Text('Ajustes', style: TextStyle(fontSize: 20, fontWeight: FontWeight.bold, color: morado))),
        const SizedBox(height: 8),
        boton('🖐  Ver y escuchar las señas', lila, abrirSenas, fg: texto),
        boton('🗣  Dar una orden por voz', azul, hablarOrden),
        boton('⏹  Silencio', morado, voz.detener),
        const Padding(
          padding: EdgeInsets.all(16),
          child: Text('La cámara y el micrófono son los del propio teléfono. Los audífonos (cable o Bluetooth) se usan '
              'automáticamente como salida de audio.'),
        ),
      ]);

  Widget vistaSenas() => ListView(padding: const EdgeInsets.all(16), children: [
        const Text('Señas de mano', style: TextStyle(fontSize: 20, fontWeight: FontWeight.bold, color: morado)),
        const SizedBox(height: 8),
        const Text('Pregunta por voz: «¿cuál es la seña de materiales?»'),
        const SizedBox(height: 10),
        for (final s in listaSenas()) ...[
          Text(s.nombre[0].toUpperCase() + s.nombre.substring(1),
              style: const TextStyle(fontSize: 16, fontWeight: FontWeight.bold, color: morado)),
          Text('   ${s.como}\n'),
        ],
      ]);

  @override
  Widget build(BuildContext context) {
    final cuerpo = switch (pant) {
      Pant.menu => menu(),
      Pant.modo => vistaModo(),
      Pant.materiales => vistaMateriales(),
      Pant.ajustes => vistaAjustes(),
      Pant.senas => vistaSenas(),
    };
    return PopScope(
      canPop: pant == Pant.menu,
      onPopInvokedWithResult: (ok, _) {
        if (!ok) atras();
      },
      child: Scaffold(
        appBar: AppBar(
          backgroundColor: crema,
          centerTitle: true,
          title: const Text.rich(TextSpan(children: [
            TextSpan(text: 'Edu', style: TextStyle(color: azul, fontWeight: FontWeight.bold, fontSize: 28)),
            TextSpan(text: 'Accesible', style: TextStyle(color: morado, fontWeight: FontWeight.bold, fontSize: 28)),
          ])),
          actions: [
            if (pant != Pant.menu) IconButton(icon: const Icon(Icons.home), onPressed: () => ejecutarOrden('inicio')),
          ],
        ),
        body: SafeArea(child: cuerpo),
        bottomNavigationBar: estado.isEmpty
            ? null
            : Padding(padding: const EdgeInsets.all(8), child: Text(estado, textAlign: TextAlign.center)),
      ),
    );
  }
}
