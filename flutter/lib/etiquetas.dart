// Nombres en español de las etiquetas más comunes de ML Kit (singular). Las que no estén se dicen en inglés.
const Map<String, String> etiquetasEs = {
  'person': 'persona', 'chair': 'silla', 'table': 'mesa', 'desk': 'escritorio', 'cup': 'taza', 'mug': 'taza',
  'bottle': 'botella', 'water bottle': 'botella de agua', 'glass': 'vaso', 'drinkware': 'vaso', 'plate': 'plato',
  'bowl': 'tazón', 'fork': 'tenedor', 'spoon': 'cuchara', 'knife': 'cuchillo', 'book': 'libro', 'notebook': 'cuaderno',
  'pen': 'lápiz o bolígrafo', 'pencil': 'lápiz', 'paper': 'papel', 'scissors': 'tijeras', 'computer': 'computador',
  'laptop': 'portátil', 'mobile phone': 'teléfono celular', 'phone': 'teléfono', 'smartphone': 'teléfono celular',
  'television': 'televisor', 'monitor': 'monitor', 'keyboard': 'teclado', 'mouse': 'ratón', 'remote control': 'control remoto',
  'clock': 'reloj', 'watch': 'reloj', 'lamp': 'lámpara', 'bed': 'cama', 'couch': 'sofá', 'sofa': 'sofá', 'pillow': 'almohada',
  'door': 'puerta', 'window': 'ventana', 'bag': 'bolso', 'backpack': 'mochila', 'shoe': 'zapato', 'footwear': 'zapato',
  'hat': 'sombrero', 'glasses': 'gafas', 'sunglasses': 'gafas de sol', 'toy': 'juguete', 'ball': 'pelota', 'doll': 'muñeca',
  'car': 'carro', 'bicycle': 'bicicleta', 'bus': 'bus', 'motorcycle': 'moto', 'dog': 'perro', 'cat': 'gato', 'bird': 'pájaro',
  'flower': 'flor', 'plant': 'planta', 'houseplant': 'planta', 'tree': 'árbol', 'fruit': 'fruta', 'apple': 'manzana',
  'banana': 'banano', 'orange': 'naranja', 'food': 'comida', 'bread': 'pan', 'cake': 'torta', 'pizza': 'pizza',
  'box': 'caja', 'bottle cap': 'tapa', 'key': 'llave', 'coin': 'moneda', 'umbrella': 'paraguas', 'candle': 'vela',
  'vase': 'florero', 'picture frame': 'cuadro', 'poster': 'afiche', 'headphones': 'audífonos', 'camera': 'cámara',
  'microphone': 'micrófono', 'speaker': 'parlante', 'wheel': 'rueda', 'tire': 'llanta', 'furniture': 'mueble',
  'shelf': 'estante', 'cabinet': 'armario', 'sink': 'lavamanos', 'toilet': 'inodoro', 'bathroom': 'baño',
};

String nombreEs(String etiqueta, [bool plural = false]) {
  final base = etiquetasEs[etiqueta.toLowerCase()] ?? etiqueta.toLowerCase();
  return plural ? pluralEs(base) : base;
}

String pluralEs(String p) {
  if (p.contains(' ')) {
    final i = p.indexOf(' ');
    return pluralEs(p.substring(0, i)) + p.substring(i); // "botella de agua" -> "botellas de agua"
  }
  if (p.endsWith('z')) return '${p.substring(0, p.length - 1)}ces';
  if (RegExp(r'[aeiouáéó]$').hasMatch(p)) return '${p}s';
  if (p.endsWith('í') || p.endsWith('ú')) return '${p}es';
  return '${p}es';
}
