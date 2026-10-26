import 'dart:convert';
import 'dart:io';
import 'package:archive/archive.dart';
import 'package:flutter/foundation.dart';
import 'package:syncfusion_flutter_pdf/pdf.dart';

/// Extensiones que la app sabe abrir.
const extensionesTexto = ['txt', 'md', 'csv', 'pdf', 'docx'];
const extensionesImagen = ['jpg', 'jpeg', 'png', 'webp', 'bmp'];

String _limpiar(String t) => t
    .replaceAll('\r', '')
    .replaceAll(RegExp(r'[ \t]+'), ' ')
    .replaceAll(RegExp(r' ?\n ?'), '\n')
    .replaceAll(RegExp(r'\n{3,}'), '\n\n')
    .trim();

String _leer(String ruta) {
  final ext = ruta.split('.').last.toLowerCase();
  final bytes = File(ruta).readAsBytesSync();
  String t = '';
  if (ext == 'pdf') {
    final doc = PdfDocument(inputBytes: bytes);
    try {
      t = PdfTextExtractor(doc).extractText();
    } finally {
      doc.dispose();
    }
  } else if (ext == 'docx') {
    final zip = ZipDecoder().decodeBytes(bytes);
    for (final f in zip) {
      if (f.name == 'word/document.xml') {
        var x = utf8.decode(f.content as List<int>, allowMalformed: true);
        x = x.replaceAll('</w:p>', '\n').replaceAll('<w:tab/>', ' ').replaceAll('<w:br/>', '\n');
        x = x.replaceAll(RegExp(r'<[^>]+>'), '');
        t = x
            .replaceAll('&amp;', '&')
            .replaceAll('&lt;', '<')
            .replaceAll('&gt;', '>')
            .replaceAll('&quot;', '"')
            .replaceAll('&apos;', "'");
        break;
      }
    }
  } else {
    t = utf8.decode(bytes, allowMalformed: true);
  }
  return _limpiar(t);
}

/// Lee el texto de un documento (txt, pdf con texto, docx). Devuelve '' si no encuentra texto.
Future<String> leerDocumento(String ruta) => compute(_leer, ruta);
