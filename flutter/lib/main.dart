import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:camera/camera.dart';
import 'pantallas.dart';

List<CameraDescription> camaras = [];

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  await SystemChrome.setPreferredOrientations(DeviceOrientation.values);
  try {
    camaras = await availableCameras();
  } catch (_) {}
  runApp(const EduApp());
}

const crema = Color(0xFFFAF6EB);
const morado = Color(0xFF895DCA);
const azul = Color(0xFF5273BA);
const lila = Color(0xFFCDB8EA);
const texto = Color(0xFF2B2650);

class EduApp extends StatelessWidget {
  const EduApp({super.key});
  @override
  Widget build(BuildContext context) => MaterialApp(
        title: 'EduAccesible',
        debugShowCheckedModeBanner: false,
        theme: ThemeData(
          useMaterial3: true,
          scaffoldBackgroundColor: crema,
          colorScheme: ColorScheme.fromSeed(seedColor: morado),
        ),
        home: const Inicio(),
      );
}
