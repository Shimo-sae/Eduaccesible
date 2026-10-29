import collections
import difflib
import subprocess
import tempfile
import html
import math
import unicodedata
import json
import os
import queue
import re
import shutil
import threading
import sys
import time
import urllib.parse
import urllib.request
import wave
import zipfile
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog

# Video del teléfono por Wi-Fi con poco retraso: sin búfer de FFmpeg y sin analizar el flujo durante segundos.
# Tiene que definirse ANTES de importar cv2.
os.environ.setdefault("OPENCV_FFMPEG_CAPTURE_OPTIONS",
                      "fflags;nobuffer|flags;low_delay|probesize;65536|analyzeduration;500000")

import cv2
import numpy as np
import pytesseract
import pyttsx3
from PIL import Image, ImageTk
from pytesseract import Output

try:  # entrada de audio de la laptop (pip install sounddevice)
    import sounddevice as sd
except Exception:
    sd = None

try:  # voz con internet (opcional, pip install SpeechRecognition). Va aparte: si falta, sounddevice sigue sirviendo
    import speech_recognition as sr
except Exception:
    sr = None

try:  # reconocimiento de voz SIN internet (pip install vosk)
    import vosk
    vosk.SetLogLevel(-1)
except Exception:
    vosk = None

try:
    import winsound
except Exception:
    winsound = None

try:  # gestos de mano (pip install mediapipe==0.10.14)
    import mediapipe as mp
    MP_MANOS = mp.solutions.hands
    MP_ERROR = ""
except Exception as _e:
    mp = None
    MP_MANOS = None
    MP_ERROR = f"{type(_e).__name__}: {_e}"

try:  # motor principal de OCR (pip install rapidocr-onnxruntime)
    from rapidocr_onnxruntime import RapidOCR
except Exception:
    RapidOCR = None

# ---------------------------------------------------------------------------
# Rutas y configuración de Tesseract (Windows)
# ---------------------------------------------------------------------------
_AQUI = os.path.dirname(os.path.abspath(sys.executable if getattr(sys, "frozen", False) else __file__))
# Si el programa trae su propio Tesseract (carpeta "tesseract" junto al .exe, como en el instalador) se usa ese;
# si no, el instalado en Windows.
_TESS_PROPIO = os.path.join(_AQUI, "tesseract")
if os.path.exists(os.path.join(_TESS_PROPIO, "tesseract.exe")):
    RUTA_TESSERACT = os.path.join(_TESS_PROPIO, "tesseract.exe")
    RUTA_TESSDATA = os.path.join(_TESS_PROPIO, "tessdata")
else:
    RUTA_TESSERACT = r'C:\Program Files\Tesseract-OCR\tesseract.exe'
    if not os.path.exists(RUTA_TESSERACT):
        RUTA_TESSERACT = shutil.which('tesseract') or RUTA_TESSERACT
    RUTA_TESSDATA = r'C:\Program Files\Tesseract-OCR\tessdata'
pytesseract.pytesseract.tesseract_cmd = RUTA_TESSERACT
if os.path.isdir(RUTA_TESSDATA):
    os.environ['TESSDATA_PREFIX'] = RUTA_TESSDATA

# Como .exe (PyInstaller) __file__ apunta a una carpeta temporal que se borra al cerrar: los materiales, la
# configuración y los modelos descargados tienen que vivir junto al .exe.
if getattr(sys, "frozen", False):
    BASE_DIR = os.path.dirname(os.path.abspath(sys.executable))
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CARPETA_DEBUG = os.path.join(BASE_DIR, "debug")
CARPETA_MATERIALES = os.path.join(BASE_DIR, "materiales")
CARPETA_ENTRADA = os.path.join(BASE_DIR, "entrada")
os.makedirs(CARPETA_DEBUG, exist_ok=True)
RUTA_LOG = os.path.join(CARPETA_DEBUG, "registro.txt")
VERSION_APP = "v9"
REPO_GITHUB = "Shimo-sae/Eduaccesible"  # de aquí se consulta la última versión publicada (Releases)
URL_VERSION = ""  # opcional: dirección de un archivo de texto con la última versión (por ejemplo "v9"). Vacío = no comprobar


class _Tee:
    """Copia todo lo que la app imprime (y sus errores) en debug\\registro.txt. El programa se abre sin consola,
    y así los problemas quedan escritos y se pueden ver en Ajustes > Diagnóstico."""
    _archivo = None
    _cerrojo = threading.Lock()

    def __init__(self, original):
        self.original = original
        self._inicio_linea = True

    @classmethod
    def abrir(cls):
        try:
            if os.path.exists(RUTA_LOG) and os.path.getsize(RUTA_LOG) > 1_000_000:  # que no crezca sin fin
                with open(RUTA_LOG, encoding="utf-8", errors="ignore") as f:
                    resto = f.read()[-200_000:]
                with open(RUTA_LOG, "w", encoding="utf-8") as f:
                    f.write(resto)
            cls._archivo = open(RUTA_LOG, "a", encoding="utf-8", buffering=1)
            cls._archivo.write(f"\n===== {time.strftime('%Y-%m-%d %H:%M:%S')} inicio {VERSION_APP} =====\n")
        except OSError:
            cls._archivo = None

    def write(self, t):
        try:
            if self.original is not None:
                self.original.write(t)
        except Exception:
            pass
        if self._archivo is not None and t:
            with self._cerrojo:
                try:
                    out = []
                    for parte in t.splitlines(keepends=True):
                        if self._inicio_linea and parte.strip():
                            out.append(time.strftime("%H:%M:%S  "))
                        out.append(parte)
                        self._inicio_linea = parte.endswith("\n")
                    self._archivo.write("".join(out))
                except Exception:
                    pass
        return len(t)

    def flush(self):
        try:
            if self.original is not None:
                self.original.flush()
        except Exception:
            pass

    def isatty(self):
        return False

    encoding = "utf-8"
    errors = "replace"

    def __getattr__(self, nombre):  # lo demás (fileno, buffer...) se le pide al original, si existe
        if nombre != "original" and self.original is not None:
            return getattr(self.original, nombre)
        raise AttributeError(nombre)


_Tee.abrir()
sys.stdout = _Tee(sys.stdout)
sys.stderr = _Tee(sys.stderr)


def cola_registro(n=120):
    """Últimas n líneas del registro."""
    try:
        with open(RUTA_LOG, encoding="utf-8", errors="ignore") as f:
            return "".join(f.readlines()[-n:])
    except OSError:
        return "(sin registro todavía)"


def hay_modo_lento():
    return bool(leer_config().get("lento"))
CARPETA_MODELOS = os.path.join(BASE_DIR, "modelos")
RUTA_CONFIG = os.path.join(BASE_DIR, "config.json")
# Resolución de la cámara. 1280x720 en MJPG es fluido. 1920x1080 solo si tu cámara da 30 cuadros/s en 1080p
# (pruébalo con:  python app.py --diagnostico  que mide los cuadros por segundo de cada opción).
RES_CAMARA = (1280, 720)
# Al conectar IP Webcam, la app le pide al teléfono una resolución/calidad moderada (1080p por Wi-Fi es lo que
# más retraso causa). Es opcional: si el teléfono no acepta el cambio, se ignora. Pon None para no tocar nada.
AJUSTE_IP_WEBCAM = {"video_size": "1280x720", "quality": "60"}
os.makedirs(CARPETA_MATERIALES, exist_ok=True)
os.makedirs(CARPETA_ENTRADA, exist_ok=True)
os.makedirs(CARPETA_MODELOS, exist_ok=True)

# Colores del diseño EduAccesible
CREMA = "#faf6eb"
VERDE = "#895dca"      # morado del logo (botones principales y "Accesible")
NARANJA = "#5273ba"    # azul del logo (botones secundarios y "Edu")
AMARILLO = "#cdb8ea"    # lila suave (botones con texto oscuro)
TEXTO = "#2b2650"
try:  # alto contraste (se elige en Ajustes y se aplica al abrir): fondo blanco, letras negras, botones muy marcados
    with open(RUTA_CONFIG, encoding="utf-8") as _f:
        _cfg0 = json.load(_f)
except Exception:
    _cfg0 = {}
if _cfg0.get("contraste"):
    CREMA, TEXTO, VERDE, NARANJA, AMARILLO = "#ffffff", "#000000", "#000000", "#0033a0", "#ffe600"

MODOS = {
    "texto": "Leer texto",
    "letras": "Reconocer letras y palabras",
    "numeros": "Reconocer números",
    "figuras": "Figuras geométricas",
    "objetos": "Contar objetos",
    "dinero": "Billetes y monedas",
}
ORDEN_MODOS = ["texto", "letras", "numeros", "figuras", "objetos"]


def Interfaz_oscuro(color, f=0.88):
    """Versión un poco más oscura de un color #rrggbb (efecto al pasar el mouse)."""
    try:
        r, g, b = (int(color[i:i + 2], 16) for i in (1, 3, 5))
        return "#%02x%02x%02x" % (int(r * f), int(g * f), int(b * f))
    except Exception:
        return color


def _restablecer_v7():
    """La v6 encendía gestos y voz al abrir y guardaba eso; en computadores lentos todo junto trababa la cámara.
    Una sola vez se vuelve a empezar con ambos apagados (se encienden desde Ajustes o con la voz y se recuerdan)."""
    try:
        with open(RUTA_CONFIG, encoding="utf-8") as f:
            cfg = json.load(f)
    except Exception:
        cfg = {}
    if not cfg.get("defaults_v7"):
        cfg.update({"gestos": False, "voz_continua": False, "defaults_v7": True})
        try:
            with open(RUTA_CONFIG, "w", encoding="utf-8") as f:
                json.dump(cfg, f)
        except OSError:
            pass


def leer_config():
    try:
        with open(RUTA_CONFIG, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def guardar_config(**datos):
    cfg = leer_config()
    cfg.update(datos)
    try:
        with open(RUTA_CONFIG, "w", encoding="utf-8") as f:
            json.dump(cfg, f)
    except OSError as e:
        print(f"No se pudo guardar la configuración: {e}")


_restablecer_v7()


def _aplicar_perfil():
    """Cada perfil (estudiante) tiene su propia carpeta de materiales. 'General' usa la de siempre."""
    global CARPETA_MATERIALES
    cfg = leer_config()
    nombre = cfg.get("perfil", "General")
    if nombre == "General":
        CARPETA_MATERIALES = os.path.join(BASE_DIR, "materiales")
    else:
        CARPETA_MATERIALES = os.path.join(BASE_DIR, "perfiles", nombre, "materiales")
    os.makedirs(CARPETA_MATERIALES, exist_ok=True)


_aplicar_perfil()


def idioma_ocr():
    """Usa español si está instalado; si no, inglés (evita que Tesseract falle)."""
    try:
        instalados = pytesseract.get_languages(config='')
        if 'spa' in instalados and 'eng' in instalados:
            return 'spa+eng'
        if 'spa' in instalados:
            return 'spa'
    except Exception as e:
        print(f"No se pudo leer la lista de idiomas de Tesseract: {e}")
    return 'eng'


# ---------------------------------------------------------------------------
# Voz (hilo aparte para no congelar la interfaz)
# ---------------------------------------------------------------------------
class Voz:
    def __init__(self):
        self.cola = queue.Queue()
        self.salida = leer_config().get("salida")  # None = la salida predeterminada de Windows
        self._parar = threading.Event()
        self._hablando = threading.Event()
        self.ultimo_fin = 0.0
        threading.Thread(target=self._bucle, daemon=True).start()

    hay_espanol = True
    descripcion = "(iniciando)"
    _avisado_espanol = False

    @staticmethod
    def _buscar_espanol(voces):
        """Índice de la mejor voz en español: primero por IDIOMA de la voz (código 0A = español), luego por nombre.
        Prefiere las voces de Latinoamérica (México, EE. UU., Colombia...) sobre la de España."""
        candidatas = []
        for i in range(voces.Count):
            v = voces.Item(i)
            desc = v.GetDescription().lower()
            try:
                langs = [int(x, 16) for x in v.GetAttribute("Language").replace(" ", "").split(";") if x]
            except Exception:
                langs = []
            es = any((l & 0x3FF) == 0x0A for l in langs) or any(k in desc for k in ("spanish", "español", "espanol"))
            if es:
                latam = any(k in desc for k in ("mexic", "méxic", "united states", "colomb", "argent", "latin", "perú", "peru", "chile"))
                candidatas.append((0 if latam else 1, i))
        return min(candidatas)[1] if candidatas else None

    # --- SAPI (voz de Windows) ---
    def _crear_voz(self):
        import win32com.client
        voz = win32com.client.Dispatch("SAPI.SpVoice")
        cfg = leer_config()
        voz.Rate = int(cfg.get("velocidad", -1))   # -10 muy lento ... 10 muy rápido
        voz.Volume = int(cfg.get("volumen", 100))
        voces = voz.GetVoices()
        elegida = self._buscar_espanol(voces)
        if elegida is not None:
            voz.Voice = voces.Item(elegida)
            self.hay_espanol = True
        else:
            # Sin voz en español, Windows lee con la voz en inglés y las palabras salen mezcladas.
            self.hay_espanol = False
        salidas = voz.GetAudioOutputs()
        if self.salida is not None and 0 <= self.salida < salidas.Count:
            voz.AudioOutput = salidas.Item(self.salida)
        return voz

    def _bucle(self):
        """Voz directa de Windows (SAPI): rápida y estable. Si falla, usa pyttsx3."""
        try:
            import pythoncom
            pythoncom.CoInitialize()
            voz = self._crear_voz()
            self.descripcion = voz.Voice.GetDescription()
            print(f"Voz en uso: {self.descripcion}")
            if not self.hay_espanol:
                print("AVISO: Windows no tiene ninguna voz en español instalada.")
        except Exception as e:
            print(f"SAPI no disponible ({e}); se usa pyttsx3.")
            self._trabajar()
            return
        while True:
            item = self.cola.get()
            if item is None:
                break
            if callable(item):  # órdenes internas (cambiar de salida de audio)
                try:
                    voz = item(voz) or voz
                except Exception as e:
                    print(f"Error al cambiar la salida de audio: {e}")
                continue
            try:
                self._parar.clear()
                if self.salida is None and time.time() - self.ultimo_fin > 4.0:
                    # Recrear la voz tras unos segundos de silencio: así sigue a Windows si conectas
                    # audífonos Bluetooth o de cable. Entre frases seguidas no se recrea (ahorra ~0,2 s cada una).
                    voz = self._crear_voz()
                if not self.hay_espanol and not self._avisado_espanol:
                    self._avisado_espanol = True
                    item = ("Atención: este computador no tiene voz en español instalada. Se oirá mezclado con inglés. "
                            "Instálala en Configuración, Hora e idioma, Idioma y región, Español, Opciones, Voz. ") + item
                self._hablando.set()
                voz.Speak(item, 1)  # asíncrono: así se puede cortar a mitad de frase
                while not voz.WaitUntilDone(100):
                    if self._parar.is_set():
                        voz.Speak("", 3)  # 3 = asíncrono + borrar lo que esté sonando
                        break
            except Exception as e:
                print(f"Error de voz: {e}")
            finally:
                self._hablando.clear()
                self.ultimo_fin = time.time()

    def hablar_idioma(self, texto, idioma=0x09):
        """Dice un texto con una voz de otro idioma (0x09 = inglés) si Windows la tiene; luego vuelve a la voz en español."""
        print(f"[VOZ idioma {idioma:#x}] {texto}")

        def trabajo(voz):
            anterior = voz.Voice
            try:
                voces = voz.GetVoices()
                for i in range(voces.Count):
                    try:
                        langs = [int(x, 16) for x in voces.Item(i).GetAttribute("Language").replace(" ", "").split(";") if x]
                    except Exception:
                        langs = []
                    if any((l & 0x3FF) == idioma for l in langs):
                        voz.Voice = voces.Item(i)
                        break
                self._parar.clear()
                self._hablando.set()
                voz.Speak(texto, 1)
                while not voz.WaitUntilDone(100):
                    if self._parar.is_set():
                        voz.Speak("", 3)
                        break
            finally:
                try:
                    voz.Voice = anterior
                except Exception:
                    pass
                self._hablando.clear()
                self.ultimo_fin = time.time()
            return voz
        self.cola.put(trabajo)

    def ajustar(self, vel=0, vol=0):
        """Cambia la velocidad (pasos de 1, de -6 a 6) o el volumen (pasos de 15, de 20 a 100) y lo recuerda."""
        cfg = leer_config()
        v = max(-6, min(6, int(cfg.get("velocidad", -1)) + vel))
        w = max(20, min(100, int(cfg.get("volumen", 100)) + vol))
        guardar_config(velocidad=v, volumen=w)

        def trabajo(voz):
            voz.Rate, voz.Volume = v, w
            return voz
        self.cola.put(trabajo)
        return v, w

    def siguiente_salida(self, avisar):
        """Rota: predeterminada de Windows -> cada dispositivo de audio -> predeterminada."""
        def trabajo(voz):
            salidas = voz.GetAudioOutputs()
            n = salidas.Count
            if n == 0:
                avisar("No se encontró ninguna salida de audio.")
                return None
            opciones = [None] + list(range(n))
            sig = opciones[(opciones.index(self.salida) + 1) % len(opciones)] if self.salida in opciones else None
            self.salida = sig
            guardar_config(salida=sig)
            nuevo = self._crear_voz()
            if sig is None:
                nombre = "la salida predeterminada de Windows"
            else:
                nombre = salidas.Item(sig).GetDescription()
            print(f"Salida de audio: {nombre}")
            nuevo.Speak(f"Audio por {nombre}")
            return nuevo
        self.cola.put(trabajo)

    def _trabajar(self):
        # En Windows, SAPI5 necesita COM inicializado en CADA hilo; sin esto no suena nada
        try:
            import pythoncom
            pythoncom.CoInitialize()
        except Exception:
            try:
                import comtypes
                comtypes.CoInitialize()
            except Exception as e:
                print(f"Aviso COM (instala pywin32 si no hay audio): {e}")

        voz_elegida = False
        while True:
            texto = self.cola.get()
            if texto is None:
                break
            if callable(texto):
                print("Con pyttsx3 no se puede elegir la salida de audio: se usa la predeterminada de Windows.")
                continue
            try:
                # Motor nuevo en cada frase: evita que pyttsx3 se quede mudo tras la primera
                engine = pyttsx3.init()
                engine.setProperty('rate', 140)
                engine.setProperty('volume', 1.0)
                for voice in engine.getProperty('voices'):
                    nombre = voice.name.lower()
                    idiomas = [
                        (l.decode(errors='ignore') if isinstance(l, bytes) else str(l)).lower().lstrip('\x05')
                        for l in (voice.languages or [])
                    ]
                    if ('spanish' in nombre or 'español' in nombre or 'es-' in voice.id.lower()
                            or any(l.startswith('es') for l in idiomas)):
                        engine.setProperty('voice', voice.id)
                        if not voz_elegida:
                            print(f"Voz en uso: {voice.name}")
                            voz_elegida = True
                        break
                engine.say(texto)
                engine.runAndWait()
                engine.stop()
                del engine
            except Exception as e:
                print(f"Error de voz: {e}")

    def hablar(self, texto):
        print(f"[VOZ] {texto}")
        self.cola.put(texto)

    def ocupada(self):
        """True si está hablando o tiene frases en espera."""
        return self._hablando.is_set() or not self.cola.empty()

    def detener(self):
        """Corta lo que se está leyendo y borra lo que estaba en espera."""
        try:
            while True:
                item = self.cola.get_nowait()
                if item is None:  # no perder la orden de cierre
                    self.cola.put(None)
                    break
        except queue.Empty:
            pass
        self._parar.set()

    def cerrar(self):
        self.cola.put(None)


# ---------------------------------------------------------------------------
# OCR: preparación de imagen y búsqueda del mejor resultado
# ---------------------------------------------------------------------------
def preparar_variantes(frame):
    gris = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    alto, ancho = gris.shape
    if ancho < 1800:  # Tesseract necesita texto grande
        gris = cv2.resize(gris, None, fx=1800 / ancho, fy=1800 / ancho, interpolation=cv2.INTER_CUBIC)
    gris = cv2.medianBlur(gris, 3)
    mejorada = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(gris)
    _, otsu = cv2.threshold(mejorada, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    adaptativa = cv2.adaptiveThreshold(mejorada, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                       cv2.THRESH_BINARY, 31, 15)
    return [
        ("mejorada", mejorada),
        ("otsu", otsu),
        ("adaptativa", adaptativa),
        ("otsu_invertida", cv2.bitwise_not(otsu)),  # texto claro sobre fondo oscuro
    ]


def ocr_mejor_resultado(variantes, lang, psms=(6, 3), extra="", suficiente=30):
    mejor_texto, mejor_puntaje, mejor_nombre = "", 0, ""
    for nombre, img in variantes:
        for psm in psms:
            config = f"--oem 3 --psm {psm} {extra}".strip()
            try:
                datos = pytesseract.image_to_data(img, lang=lang, config=config, output_type=Output.DICT)
            except Exception as e:
                print(f"OCR falló ({nombre}, psm {psm}): {e}")
                continue

            palabras, puntaje = [], 0
            for txt, conf in zip(datos['text'], datos['conf']):
                try:
                    conf = float(conf)
                except ValueError:
                    continue
                txt = txt.strip()
                if not txt or conf < 60:
                    continue
                alnum = sum(ch.isalnum() for ch in txt)
                # Descartar ruido: símbolos sueltos, puntos, rayas, etc.
                if alnum == 0 or alnum / len(txt) < 0.6:
                    continue
                palabras.append(txt)
                puntaje += alnum * (conf / 100)

            print(f"DEBUG - {nombre} psm {psm}: puntaje {puntaje:.1f} -> {' '.join(palabras)[:60]}")
            if puntaje > mejor_puntaje:
                mejor_texto, mejor_puntaje, mejor_nombre = " ".join(palabras), puntaje, nombre
            if mejor_puntaje >= suficiente:  # ya es un buen resultado, no seguir probando
                return mejor_texto, mejor_nombre, dict(variantes)
    # Si lo mejor que se encontró es muy poco, es ruido: no hay texto
    if mejor_puntaje < suficiente * 0.13:
        return "", "", dict(variantes)
    return mejor_texto, mejor_nombre, dict(variantes)


# ---------------------------------------------------------------------------
# Motor OCR: RapidOCR (principal) con Tesseract de respaldo
# ---------------------------------------------------------------------------
class MotorOCR:
    """Se carga UNA sola vez al iniciar la app (en otro hilo) para que la primera captura no sea lenta."""

    def __init__(self, lang_tesseract=None):
        self.lang = lang_tesseract  # None: se averigua en el hilo de carga (llamar a tesseract.exe tarda y frenaba el arranque)
        self.rapid = None
        self.nombre = "Tesseract"
        self.listo = threading.Event()

    def cargar(self):
        if self.lang is None:
            self.lang = idioma_ocr()
            print(f"Idioma OCR de respaldo (Tesseract): {self.lang}")
        try:
            if RapidOCR is not None:
                self.rapid = RapidOCR()
                self.rapid(np.full((96, 320, 3), 255, np.uint8))  # "calentar" el motor
                self.nombre = "RapidOCR"
            else:
                print("RapidOCR no está instalado: se usará Tesseract.")
        except Exception as e:
            print(f"RapidOCR no se pudo iniciar ({e}): se usará Tesseract.")
            self.rapid = None
        print(f"Motor OCR: {self.nombre}")
        self.listo.set()

    def _rapid_lineas(self, frame):
        """Devuelve el texto como lista de líneas (de arriba a abajo, de izquierda a derecha)."""
        resultado, _ = self.rapid(frame)
        if not resultado:
            return []
        items = []
        for caja, txt, score in resultado:
            try:
                if float(score) < 0.5:
                    continue
            except (TypeError, ValueError):
                pass
            ys = [p[1] for p in caja]
            xs = [p[0] for p in caja]
            if txt.strip():
                items.append((min(ys), max(ys), min(xs), txt.strip()))
        items.sort(key=lambda t: t[0])
        lineas = []
        for y0, y1, x0, txt in items:
            cy = (y0 + y1) / 2
            for l in lineas:
                if l["y0"] <= cy <= l["y1"]:
                    l["t"].append((x0, txt))
                    break
            else:
                lineas.append({"y0": y0, "y1": y1, "t": [(x0, txt)]})
        lineas.sort(key=lambda l: l["y0"])
        return [" ".join(t for _, t in sorted(l["t"])) for l in lineas]

    def texto(self, frame, psms=(6, 3), suficiente=30):
        """Devuelve (texto, motor_usado)."""
        self.listo.wait(90)
        if self.rapid is not None:
            try:
                t = " ".join(self._rapid_lineas(frame)).strip()
                if t:
                    return t, "RapidOCR"
            except Exception as e:
                print(f"RapidOCR falló ({e}): probando con Tesseract.")
        variantes = preparar_variantes(frame)
        t, nombre, imgs = ocr_mejor_resultado(variantes, self.lang, psms=psms, suficiente=suficiente)
        if nombre:
            cv2.imwrite(os.path.join(CARPETA_DEBUG, "procesada.png"), imgs[nombre])
        return t, "Tesseract"

    def numeros(self, frame):
        self.listo.wait(90)
        permitidos = "0123456789+-$%.,"
        if self.rapid is not None:
            try:
                partes = []
                for linea in self._rapid_lineas(frame):
                    if any(ch.isdigit() for ch in linea):
                        linea = linea.translate(str.maketrans("OolI", "0011"))  # confusiones típicas
                        s = "".join(ch for ch in linea if ch in permitidos or ch == " ").strip()
                        if any(ch.isdigit() for ch in s):
                            partes.append(s)
                if partes:
                    return " ".join(partes)
            except Exception as e:
                print(f"RapidOCR falló ({e}): probando con Tesseract.")
        variantes = preparar_variantes(frame)
        extra = f"-c tessedit_char_whitelist={permitidos}"
        t, nombre, imgs = ocr_mejor_resultado(variantes, 'eng', psms=(6, 7, 11), extra=extra, suficiente=6)
        if nombre:
            cv2.imwrite(os.path.join(CARPETA_DEBUG, "procesada.png"), imgs[nombre])
        return t


# ---------------------------------------------------------------------------
# Figuras geométricas
# ---------------------------------------------------------------------------
NOMBRES_COLOR = ["negro", "blanco", "gris", "rojo", "naranja", "amarillo", "verde", "azul", "morado", "rosa"]


def clases_de_color(hsv):
    """Clasifica cada píxel en un color con nombre (el rojo se maneja bien aunque 'dé la vuelta' en HSV)."""
    h = hsv[..., 0].astype(np.int16)
    s = hsv[..., 1]
    v = hsv[..., 2]
    cond = [v < 70, (s < 40) & (v > 180), s < 40, (h < 8) | (h >= 170),
            h < 22, h < 35, h < 85, h < 130, h < 160]
    return np.select(cond, list(range(9)), default=9).astype(np.uint8)


def clasificar_figura(c):
    peri = cv2.arcLength(c, True)
    area = cv2.contourArea(c)
    if peri == 0 or area == 0:
        return None
    vertices = len(cv2.approxPolyDP(c, 0.03 * peri, True))
    (_, _), radio = cv2.minEnclosingCircle(c)
    ratio_circulo = area / (np.pi * radio * radio) if radio > 0 else 0

    if vertices >= 5 and ratio_circulo > 0.88:
        return "círculo"
    if vertices == 3:
        return "triángulo"
    if vertices == 4:
        (_, _), (w, h), _ = cv2.minAreaRect(c)
        if min(w, h) == 0:
            return None
        return "cuadrado" if min(w, h) / max(w, h) >= 0.88 else "rectángulo"
    if vertices == 5:
        return "pentágono"
    if vertices == 6:
        return "hexágono"
    return "figura irregular"


def _candidatos_figuras(img):
    H, W = img.shape[:2]
    hsv = cv2.cvtColor(cv2.GaussianBlur(img, (5, 5), 0), cv2.COLOR_BGR2HSV)
    cls = clases_de_color(hsv)
    total = H * W
    kernel = np.ones((3, 3), np.uint8)
    cand = []
    for k, nombre in enumerate(NOMBRES_COLOR):
        m = (cls == k).astype(np.uint8) * 255
        m = cv2.morphologyEx(m, cv2.MORPH_OPEN, kernel)
        m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, kernel)
        contornos, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        for c in contornos:
            area = cv2.contourArea(c)
            x, y, w, h = cv2.boundingRect(c)
            if area < total * 0.004 or area > total * 0.90:  # muy pequeño = ruido
                continue
            if x <= 1 or y <= 1 or x + w >= W - 1 or y + h >= H - 1:  # toca el borde: fondo o marco
                continue
            if nombre == "gris":  # los grises solo valen si son formas sólidas (no sombras ni reflejos)
                hull = cv2.contourArea(cv2.convexHull(c))
                if hull == 0 or area / hull < 0.93:
                    continue
            cand.append(dict(c=c, area=area, box=(x, y, w, h), color=nombre))

    # Descartar "contenedores": pantalla, marco u hoja grande que tiene otras figuras dentro
    final = []
    for a in cand:
        neutro = a["color"] in ("blanco", "negro")
        if a["area"] > total * 0.25 or (neutro and a["area"] > total * 0.08):
            x, y, w, h = a["box"]
            if any(b is not a and x <= b["box"][0] + b["box"][2] / 2 <= x + w
                   and y <= b["box"][1] + b["box"][3] / 2 <= y + h for b in cand):
                continue
        final.append(a)
    return final


def detectar_figuras(frame, recorte=True):
    """recorte=True: solo analiza la zona guía verde que se dibuja en la cámara."""
    H, W = frame.shape[:2]
    if recorte:
        x0, x1, y0, y1 = int(W * .08), int(W * .92), int(H * .08), int(H * .92)
    else:
        x0, x1, y0, y1 = 0, W, 0, H
    zona = frame[y0:y1, x0:x1]
    pequeno = cv2.resize(zona, (800, int(zona.shape[0] * 800 / zona.shape[1])))

    figuras = []
    for a in _candidatos_figuras(pequeno):
        forma = clasificar_figura(a["c"])
        if forma:
            figuras.append((forma, a["color"], a["box"]))
    figuras = sorted(figuras, key=lambda t: t[2][0])[:8]  # de izquierda a derecha

    anotada = pequeno.copy()
    for i, (_, _, (x, y, w, h)) in enumerate(figuras, start=1):
        cv2.rectangle(anotada, (x, y), (x + w, y + h), (0, 170, 0), 2)
        cv2.putText(anotada, str(i), (x, max(y - 5, 15)), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 120, 0), 2)
    cv2.imwrite(os.path.join(CARPETA_DEBUG, "figuras.png"), anotada)
    return [(f, c) for f, c, _ in figuras]


# ---------------------------------------------------------------------------
# Contar objetos: detector YOLOX (80 clases del conjunto COCO), se descarga una sola vez (~36 MB)
# ---------------------------------------------------------------------------
URL_MODELO = ("https://media.githubusercontent.com/media/opencv/opencv_zoo/main/models/"
              "object_detection_yolox/object_detection_yolox_2022nov.onnx")
RUTA_MODELO = os.path.join(CARPETA_MODELOS, "yolox_s.onnx")
TAM_MIN_MODELO = 30_000_000

# (singular, plural) en español, en el orden de las clases COCO
CLASES_ES = [
    ("persona", "personas"), ("bicicleta", "bicicletas"), ("carro", "carros"), ("moto", "motos"),
    ("avión", "aviones"), ("bus", "buses"), ("tren", "trenes"), ("camión", "camiones"),
    ("bote", "botes"), ("semáforo", "semáforos"), ("hidrante", "hidrantes"),
    ("señal de pare", "señales de pare"), ("parquímetro", "parquímetros"), ("banca", "bancas"),
    ("pájaro", "pájaros"), ("gato", "gatos"), ("perro", "perros"), ("caballo", "caballos"),
    ("oveja", "ovejas"), ("vaca", "vacas"), ("elefante", "elefantes"), ("oso", "osos"),
    ("cebra", "cebras"), ("jirafa", "jirafas"), ("mochila", "mochilas"), ("paraguas", "paraguas"),
    ("bolso", "bolsos"), ("corbata", "corbatas"), ("maleta", "maletas"), ("frisbi", "frisbis"),
    ("esquí", "esquís"), ("tabla de snowboard", "tablas de snowboard"), ("balón", "balones"),
    ("cometa", "cometas"), ("bate", "bates"), ("guante de béisbol", "guantes de béisbol"),
    ("patineta", "patinetas"), ("tabla de surf", "tablas de surf"), ("raqueta", "raquetas"),
    ("botella", "botellas"), ("copa", "copas"), ("taza", "tazas"), ("tenedor", "tenedores"),
    ("cuchillo", "cuchillos"), ("cuchara", "cucharas"), ("tazón", "tazones"), ("banano", "bananos"),
    ("manzana", "manzanas"), ("sándwich", "sándwiches"), ("naranja", "naranjas"),
    ("brócoli", "brócolis"), ("zanahoria", "zanahorias"), ("perro caliente", "perros calientes"),
    ("pizza", "pizzas"), ("dona", "donas"), ("torta", "tortas"), ("silla", "sillas"),
    ("sofá", "sofás"), ("planta en maceta", "plantas en maceta"), ("cama", "camas"),
    ("mesa", "mesas"), ("inodoro", "inodoros"), ("televisor", "televisores"),
    ("computador portátil", "computadores portátiles"), ("ratón", "ratones"),
    ("control remoto", "controles remotos"), ("teclado", "teclados"),
    ("teléfono celular", "teléfonos celulares"), ("microondas", "microondas"), ("horno", "hornos"),
    ("tostadora", "tostadoras"), ("lavamanos", "lavamanos"), ("nevera", "neveras"),
    ("libro", "libros"), ("reloj", "relojes"), ("florero", "floreros"), ("tijeras", "tijeras"),
    ("oso de peluche", "osos de peluche"), ("secador de pelo", "secadores de pelo"),
    ("cepillo de dientes", "cepillos de dientes"),
]


class DetectorObjetos:
    TAM = 640

    def __init__(self, aviso=None):
        self.aviso = aviso or (lambda t: None)
        self.sesion = None
        self.net = None
        self.listo = threading.Event()
        self.error = ""
        self._preparar_rejilla()

    def _preparar_rejilla(self):
        rejillas, pasos = [], []
        for paso in (8, 16, 32):
            n = self.TAM // paso
            xv, yv = np.meshgrid(np.arange(n), np.arange(n))
            rejillas.append(np.stack((xv, yv), 2).reshape(-1, 2))
            pasos.append(np.full((n * n, 1), paso))
        self.rejilla = np.concatenate(rejillas).astype(np.float32)
        self.pasos = np.concatenate(pasos).astype(np.float32)

    def _descargar(self):
        self.aviso("Descargando el detector de objetos. Solo pasa la primera vez, espera un momento.")
        print(f"Descargando el modelo de objetos (~36 MB) a {RUTA_MODELO} ...")
        parcial = RUTA_MODELO + ".part"
        urllib.request.urlretrieve(URL_MODELO, parcial)
        if os.path.getsize(parcial) < TAM_MIN_MODELO:
            os.remove(parcial)
            raise RuntimeError("la descarga quedó incompleta")
        os.replace(parcial, RUTA_MODELO)

    def cargar(self):
        try:
            if not os.path.exists(RUTA_MODELO) or os.path.getsize(RUTA_MODELO) < TAM_MIN_MODELO:
                self._descargar()
            try:
                import onnxruntime as ort
                self.sesion = ort.InferenceSession(RUTA_MODELO, providers=["CPUExecutionProvider"])
                self.entrada = self.sesion.get_inputs()[0].name
            except Exception as e:  # sin onnxruntime: se usa el motor de OpenCV
                print(f"onnxruntime no disponible para objetos ({e}); se usa OpenCV DNN.")
                self.sesion = None
                self.net = cv2.dnn.readNetFromONNX(RUTA_MODELO)
            self.detectar(np.full((240, 320, 3), 114, np.uint8))  # calentar
            print("Detector de objetos listo.")
        except Exception as e:
            self.error = str(e)
            print(f"No se pudo preparar el detector de objetos: {e}")
        finally:
            self.listo.set()

    def detectar(self, frame, conf=0.45, iou=0.5):
        """Devuelve [(índice_clase, confianza, (x1, y1, x2, y2))] en coordenadas del frame."""
        h, w = frame.shape[:2]
        r = min(self.TAM / h, self.TAM / w)
        nh, nw = int(round(h * r)), int(round(w * r))
        lienzo = np.full((self.TAM, self.TAM, 3), 114, np.uint8)
        lienzo[:nh, :nw] = cv2.resize(frame, (nw, nh), interpolation=cv2.INTER_LINEAR)
        blob = np.ascontiguousarray(lienzo.transpose(2, 0, 1)[None].astype(np.float32))
        if self.sesion is not None:
            salida = self.sesion.run(None, {self.entrada: blob})[0]
        else:
            self.net.setInput(blob)
            salida = self.net.forward()
        salida = np.asarray(salida)[0]
        xy = (salida[:, :2] + self.rejilla) * self.pasos
        wh = np.exp(salida[:, 2:4]) * self.pasos
        puntajes = salida[:, 4:5] * salida[:, 5:]
        clase = puntajes.argmax(1)
        puntaje = puntajes.max(1)
        ok = puntaje > conf
        if not ok.any():
            return []
        xy, wh, clase, puntaje = xy[ok], wh[ok], clase[ok], puntaje[ok]
        x1y1 = (xy - wh / 2) / r
        cajas = np.concatenate([x1y1, wh / r], 1)  # x, y, ancho, alto
        resultado = []
        for c in np.unique(clase):  # supresión de duplicados por clase
            idx = np.where(clase == c)[0]
            keep = cv2.dnn.NMSBoxes(cajas[idx].tolist(), puntaje[idx].tolist(), conf, iou)
            for k in np.array(keep).flatten():
                x, y, bw, bh = cajas[idx[k]]
                x1, y1 = max(0, int(x)), max(0, int(y))
                x2, y2 = min(w - 1, int(x + bw)), min(h - 1, int(y + bh))
                if x2 > x1 and y2 > y1:
                    resultado.append((int(c), float(puntaje[idx[k]]), (x1, y1, x2, y2)))
        return sorted(resultado, key=lambda d: d[2][0])


def frase_conteo(detecciones):
    """'Se detectaron 5 objetos: 3 tazas, 1 libro y 1 teléfono celular.'"""
    cuenta = collections.Counter(d[0] for d in detecciones)
    partes = [f"{n} {CLASES_ES[c][0] if n == 1 else CLASES_ES[c][1]}"
              for c, n in cuenta.most_common()]
    detalle = partes[0] if len(partes) == 1 else ", ".join(partes[:-1]) + " y " + partes[-1]
    total = sum(cuenta.values())
    if len(cuenta) == 1:
        return f"Hay {detalle}."
    return f"Se detectaron {total} objetos: {detalle}."


# ---------------------------------------------------------------------------
# Gestos de mano (MediaPipe Hands): dos manos, y solo se activa un gesto claro, quieto y sostenido
# ---------------------------------------------------------------------------
def par(a, b):
    """Nombre de una seña con DOS manos (el orden no importa): par("uno", "palma") == par("palma", "uno")."""
    return "+".join(sorted((a, b)))


# CADA función tiene su propia seña. Una mano: 1 a 5 dedos, puño, pulgar. Dos manos: combinaciones.
# seña -> (orden, nombre hablado, cómo se hace). "6" y "7" se cuentan como 5+1 y 5+2 (mano abierta + dedos).
SENAS = {
    "uno": ("m_texto", "leer texto", "un dedo levantado"),
    "dos": ("m_letras", "reconocer letras y palabras", "dos dedos levantados"),
    "tres": ("m_numeros", "reconocer números", "tres dedos levantados"),
    "cuatro": ("m_figuras", "figuras geométricas", "cuatro dedos levantados, sin el pulgar"),
    "palma": ("m_objetos", "contar objetos", "una mano completamente abierta"),
    par("palma", "uno"): ("materiales", "materiales guardados",
                          "dos manos: una mano abierta y la otra con un dedo, como contar seis"),
    par("palma", "dos"): ("ajustes", "ajustes",
                          "dos manos: una mano abierta y la otra con dos dedos, como contar siete"),
    par("puno", "puno"): ("capturar", "capturar", "los dos puños cerrados"),
    "puno": ("repetir", "repetir", "un puño cerrado"),
    par("palma", "palma"): ("silencio", "silencio", "las dos manos abiertas, como pidiendo que pare"),
    par("uno", "uno"): ("inicio", "ir al inicio", "dos manos, un dedo levantado en cada una"),
    par("dos", "dos"): ("atras", "volver atrás", "dos manos, dos dedos levantados en cada una"),
    par("tres", "tres"): ("senas", "ayuda de señas",
                          "dos manos, tres dedos levantados en cada una"),
    "pulgar": ("voz", "la voz siempre activa", "el pulgar hacia arriba"),
}
# orden -> seña (para contestar "¿cuál es la seña de...?")
SENA_DE_ORDEN = {datos[0]: sena for sena, datos in SENAS.items()}


def frase_sena(orden):
    """Lo que dice la app cuando preguntas por la seña de algo. orden: nombre de la orden (o 'voz', 'senas')."""
    if orden in ("voz_on", "voz_off"):
        orden = "voz"
    sena = SENA_DE_ORDEN.get(orden)
    if sena is None:
        if orden in ("gestos_on", "gestos_off"):
            return "Los gestos no tienen seña, porque para hacer señas ya tienen que estar activos. Se activan con la tecla G o diciendo: activar gestos."
        return "Esa opción no tiene seña. Está dentro de Ajustes, o se pide por voz."
    _, nombre, como = SENAS[sena]
    return f"La seña de {nombre} es: {como}."


def lista_senas():
    """Todas las señas, en el orden del menú (para leer en voz alta y mostrar en pantalla)."""
    orden = ["m_texto", "m_letras", "m_numeros", "m_figuras", "m_objetos", "materiales", "ajustes",
             "capturar", "repetir", "silencio", "inicio", "atras", "senas", "voz"]
    return [(SENAS[SENA_DE_ORDEN[o]][1], SENAS[SENA_DE_ORDEN[o]][2]) for o in orden]



class Lectura:
    """Lee un texto largo por párrafos: se puede pausar, continuar, adelantar y retroceder."""

    def __init__(self, voz):
        self.voz = voz
        self.partes, self.i, self.gen = [], 0, 0
        self.pausada = False

    @staticmethod
    def dividir(texto, tam=420):
        partes = []
        for bloque in re.split(r"\n\s*\n|\n", texto):
            bloque = bloque.strip()
            if not bloque:
                continue
            partes.extend(trozos_voz(bloque, tam) if len(bloque) > tam else [bloque])
        return partes

    def iniciar(self, texto, desde=0):
        self.partes = self.dividir(texto)
        self.i = max(0, min(desde, len(self.partes) - 1)) if self.partes else 0
        self.pausada = False
        self._arrancar()

    def _arrancar(self):
        self.gen += 1
        self.voz.detener()
        if self.i < len(self.partes):
            threading.Thread(target=self._bucle, args=(self.gen,), daemon=True).start()

    def _bucle(self, gen):
        while gen == self.gen and self.i < len(self.partes):
            self.voz.hablar(self.partes[self.i])
            time.sleep(0.2)
            while gen == self.gen and self.voz.ocupada():
                time.sleep(0.1)
            if gen == self.gen:
                self.i += 1

    def hay(self):
        return bool(self.partes)

    def pausar(self):
        if not self.hay():
            return False
        self.gen += 1
        self.pausada = True
        self.voz.detener()
        return True

    def continuar(self):
        if not self.hay() or self.i >= len(self.partes):
            return False
        self.pausada = False
        self._arrancar()
        return True

    def mover(self, delta):
        if not self.hay():
            return False
        self.i = max(0, min(len(self.partes) - 1, self.i + delta))
        self.pausada = False
        self._arrancar()
        return True

    def detener(self):
        self.gen += 1
        self.pausada = False
        self.voz.detener()

    def estado(self):
        return f"párrafo {min(self.i + 1, len(self.partes))} de {len(self.partes)}" if self.partes else ""


class Gestos:
    """Gestos de mano con MediaPipe. Ve hasta DOS manos, pero solo ejecuta un gesto cuando es claramente intencional:
      - la mano se ve completa (no cortada por el borde), con buena confianza y de tamaño razonable (no lejos);
      - cada dedo está del todo abierto o del todo cerrado (una mano relajada o a medias NO cuenta);
      - la mano se mantiene quieta y con el mismo gesto durante HOLD segundos;
      - con dos manos solo valen las combinaciones de la tabla SENAS (por ejemplo mano abierta + un dedo = 6);
        cualquier otra combinación, o una segunda mano dudosa, se ignora (ambiguo);
      - después de ejecutar uno hay que soltar el gesto antes de que valga otro."""
    HOLD = 1.2        # segundos manteniendo el mismo gesto
    ENFRIAR = 2.5     # segundos de espera después de ejecutar uno
    MIN_SCORE = 0.8   # confianza mínima de MediaPipe de que es una mano
    MIN_TAM = 0.11    # largo de la palma (muñeca-nudillo medio) respecto al alto de la imagen: más pequeño = muy lejos
    MARGEN = 0.02     # la mano no puede tocar el borde de la imagen
    MAX_MOV = 0.9     # cuánto se puede mover la mano durante el HOLD, en largos de palma
    DEDO_ABIERTO = 1.18   # punta/articulación (distancias a la muñeca) por encima: dedo extendido
    DEDO_CERRADO = 0.98   # por debajo: dedo cerrado. Entre los dos: dedo a medias -> sin gesto
    NOMBRES = {"palma": "mano abierta", "puno": "puño", "uno": "un dedo", "dos": "dos dedos",
               "tres": "tres dedos", "cuatro": "cuatro dedos", "pulgar": "pulgar arriba"}

    @classmethod
    def nombre(cls, g):
        """Nombre legible de un gesto de una mano o de dos manos ('palma+uno')."""
        if g is None:
            return ""
        if "+" in g:
            a, b = g.split("+")
            return f"dos manos: {cls.NOMBRES.get(a, a)} y {cls.NOMBRES.get(b, b)}"
        return cls.NOMBRES.get(g, g)

    def __init__(self):
        self.manos = None
        self.puntos = None   # puntos (normalizados) de la primera mano vista, para quien solo necesite una
        self.todas = []      # [(puntos normalizados, valida)] de CADA mano vista, para dibujarlas
        self.nota = ""       # por qué no hay gesto (se muestra en pantalla)
        self.error = ""
        self._meta = None    # (centro x, centro y, largo de palma) de la mano que hace el gesto
        self._muestras = collections.deque()          # (hora, gesto, meta) de la última ventana
        self._ultimas = collections.deque(maxlen=8)   # últimos gestos vistos (para saber si ya soltaste el gesto)
        self._bloqueado_hasta, self._desarmado = 0.0, None
        self.dominante, self.progreso = None, 0.0

    @staticmethod
    def disponible():
        return MP_MANOS is not None

    def iniciar(self):
        if self.manos is None and MP_MANOS is not None:
            # model_complexity=0: el modelo ligero, bastante más rápido y suficiente para estos gestos
            self.manos = MP_MANOS.Hands(static_image_mode=False, max_num_hands=2, model_complexity=0,
                                        min_detection_confidence=0.7, min_tracking_confidence=0.6)
        return self.manos is not None

    @classmethod
    def clasificar(cls, p):
        """p: 21 puntos (x, y) de la mano en el formato de MediaPipe. Devuelve el nombre del gesto o None
        (también None si algún dedo está a medias: así una mano relajada no activa nada)."""
        def d(a, b):
            return ((p[a][0] - p[b][0]) ** 2 + (p[a][1] - p[b][1]) ** 2) ** 0.5
        dedos = []
        for punta, pip in ((8, 6), (12, 10), (16, 14), (20, 18)):  # índice, medio, anular, meñique
            r = d(punta, 0) / max(d(pip, 0), 1e-6)  # distancias a la muñeca: sirve con la mano girada
            if r >= cls.DEDO_ABIERTO:
                dedos.append(True)
            elif r <= cls.DEDO_CERRADO:
                dedos.append(False)
            else:
                return None
        pulgar = d(4, 17) > d(3, 17) * 1.05 and d(4, 5) > d(3, 5)
        indice, medio, anular, menique = dedos
        n = sum(dedos)
        if n == 4 and pulgar:
            return "palma"
        if n == 0:
            # pulgar arriba: el pulgar apunta hacia arriba y los otros cuatro dedos están cerrados
            if pulgar and p[4][1] < p[3][1] < p[2][1] and p[5][1] - p[4][1] > 0.2 * d(0, 9):
                return "pulgar"
            return "puno"
        if n == 4:
            return "cuatro"
        if indice and not (medio or anular or menique):
            return "uno"
        if indice and medio and not (anular or menique):
            return "dos"
        if indice and medio and anular and not menique:
            return "tres"
        return None

    def _mano_clara(self, px, score, ancho, alto):
        """¿Esta mano se ve lo bastante bien como para fiarse de ella? Devuelve (True, '') o (False, motivo)."""
        if score < self.MIN_SCORE:
            return False, "no estoy seguro de que sea una mano"
        tam = ((px[0][0] - px[9][0]) ** 2 + (px[0][1] - px[9][1]) ** 2) ** 0.5
        if tam < self.MIN_TAM * alto:
            return False, "acerca más la mano a la cámara"
        xs, ys = [q[0] for q in px], [q[1] for q in px]
        if (min(xs) < self.MARGEN * ancho or max(xs) > (1 - self.MARGEN) * ancho
                or min(ys) < self.MARGEN * alto or max(ys) > (1 - self.MARGEN) * alto):
            return False, "la mano está cortada por el borde: llévala al centro"
        return True, ""

    def leer(self, frame):
        """Gesto que se ve en el frame (o None). Actualiza self.todas / self.puntos / self.nota."""
        self.todas, self.puntos, self._meta, self.nota = [], None, None, ""
        if self.manos is None:
            return None
        h, w = frame.shape[:2]
        ancho = 384
        alto = int(h * ancho / w)
        peq = cv2.resize(frame, (ancho, alto))
        res = self.manos.process(cv2.cvtColor(peq, cv2.COLOR_BGR2RGB))
        if not res.multi_hand_landmarks:
            return None
        scores = [m.classification[0].score for m in (res.multi_handedness or [])]
        claras, motivos = [], []
        for i, mano in enumerate(res.multi_hand_landmarks):
            lm = mano.landmark
            # En PÍXELES: las coordenadas normalizadas estiran distinto en horizontal y vertical (16:9) y confunden al pulgar
            px = [(l.x * ancho, l.y * alto) for l in lm]
            ok, motivo = self._mano_clara(px, scores[i] if i < len(scores) else 1.0, ancho, alto)
            self.todas.append(([(l.x, l.y) for l in lm], ok))
            if ok:
                claras.append((self.clasificar(px), px))
            else:
                motivos.append(motivo)
        self.puntos = self.todas[0][0]
        if not claras:
            self.nota = motivos[0] if motivos else ""
            return None
        if motivos:
            # Hay una segunda mano que no se ve bien (cortada, lejos...). Si ejecutáramos solo la clara, un "6" con la
            # otra mano medio fuera de la imagen se leería como un "5". Mejor no hacer nada y decirlo.
            self.nota = f"hay otra mano dudosa ({motivos[0]}): muéstrala completa o bájala"
            return None
        if any(g is None for g, _ in claras):
            self.nota = "gesto a medias: abre o cierra los dedos del todo"
            return None
        if len(claras) == 1:
            g = claras[0][0]
        else:
            g = par(claras[0][0], claras[1][0])
            if g not in SENAS:
                self.nota = "esa combinación de dos manos no es una seña (di: señas, para oír la lista)"
                return None
        tams = [((px[0][0] - px[9][0]) ** 2 + (px[0][1] - px[9][1]) ** 2) ** 0.5 for _, px in claras]
        # centro de TODAS las manos que hacen la seña (para saber si se mantuvieron quietas)
        cx = sum(q[0] for _, px in claras for q in px) / (21 * len(claras))
        cy = sum(q[1] for _, px in claras for q in px) / (21 * len(claras))
        self._meta = (cx, cy, max(sum(tams) / len(tams), 1.0))
        return g

    def _quieta(self, g):
        """¿La mano estuvo quieta durante la ventana? (una mano que pasa moviéndose no es un gesto a propósito)"""
        metas = [m for _, gg, m in self._muestras if gg == g and m]
        if len(metas) < 2:
            return True
        xs, ys = [m[0] for m in metas], [m[1] for m in metas]
        tam = sum(m[2] for m in metas) / len(metas)
        return max(max(xs) - min(xs), max(ys) - min(ys)) <= self.MAX_MOV * tam

    def actualizar(self, gesto, ahora):
        """Devuelve el gesto a ejecutar cuando se mantuvo ~HOLD segundos y quieto. Tolera algún cuadro suelto."""
        self._muestras.append((ahora, gesto, self._meta if gesto else None))
        while self._muestras and ahora - self._muestras[0][0] > self.HOLD:
            self._muestras.popleft()
        self._ultimas.append(gesto)
        # Tras ejecutar un gesto, hay que soltarlo (quitar la mano o cambiar) antes de que vuelva a valer
        if self._desarmado is not None:
            ajenos = sum(1 for g in self._ultimas if g != self._desarmado)
            if len(self._ultimas) >= 6 and ajenos >= 5:
                self._desarmado = None
        cuenta = collections.Counter(g for _, g, _ in self._muestras if g)
        self.dominante, self.progreso = None, 0.0
        if cuenta:
            g, n = cuenta.most_common(1)[0]
            span = ahora - self._muestras[0][0]
            frac = n / len(self._muestras)
            if frac >= 0.8:  # el mismo gesto en casi toda la ventana
                self.dominante = g
                quieta = self._quieta(g)
                if not quieta:
                    self.nota = "mantén la mano quieta"
                else:
                    self.progreso = min(1.0, span / (self.HOLD * 0.9)) * min(1.0, frac)
                if (quieta and span >= self.HOLD * 0.9 and len(self._muestras) >= 6 and ahora >= self._bloqueado_hasta
                        and g != self._desarmado):
                    self._muestras.clear()
                    self._bloqueado_hasta = ahora + self.ENFRIAR
                    self._desarmado = g
                    self._ultimas.clear()
                    return g
        return None


# ---------------------------------------------------------------------------
# Micrófono: órdenes por voz
# ---------------------------------------------------------------------------
def _sin_tildes(t):
    return t.lower().translate(str.maketrans("áéíóúüñ", "aeiouun"))


# (palabras clave, orden). Se revisa en este orden: lo más específico primero.
ORDENES = [
    (("ayuda de senas", "lista de senas", "que senas hay", "todas las senas", "senas", "ayuda"), "senas_lista"),
    (("microfono del telefono", "microfono del celular", "microfono telefono", "microfono celular"), "mic_telefono"),
    (("microfono de la laptop", "microfono del computador", "microfono del portatil", "microfono de la computadora",
      "microfono integrado", "microfono laptop", "microfono computador", "microfono portatil"), "mic_laptop"),
    (("desactivar gestos", "apagar gestos", "quitar gestos", "sin gestos", "desactiva gestos"), "gestos_off"),
    (("desactivar voz", "apagar voz", "dejar de escuchar", "no escuches", "modo manual", "desactiva voz",
      "desactivar micrófono", "desactivar microfono", "apagar micrófono", "apagar microfono"), "voz_off"),
    (("activar voz", "voz activa", "voz siempre activa", "escuchar siempre", "escucha siempre", "modo voz", "activa voz",
      "activar micrófono", "activar microfono", "activar escucha"), "voz_on"),
    # "microfono" a secas va DESPUÉS de activar/desactivar; antes, "desactivar microfono" cambiaba de micrófono
    (("cambiar microfono", "otro microfono", "microfono"), "mic_cambiar"),
    (("activar gestos", "activa gestos", "gestos", "gesto"), "gestos_on"),
    (("camara del telefono", "camara del celular", "celular", "telefono"), "telefono"),
    (("cambiar camara", "otra camara", "siguiente camara", "camara", "camaras"), "camara"),
    (("audifonos", "salida de audio", "cambiar audio", "audio"), "audio"),
    (("ajustes", "configuracion", "dispositivos"), "ajustes"),
    (("wifi", "wi fi", "recibir archivos", "recibir por"), "wifi"),
    (("documento", "archivo", "pdf", "word"), "importar_doc"),
    (("importar", "subir imagen", "abrir imagen", "imagen"), "importar"),
    (("mas lento", "mas despacio", "despacio"), "vel_menos"),
    (("mas rapido", "rapido", "mas deprisa"), "vel_mas"),
    (("subir volumen", "mas volumen", "volumen alto", "sube el volumen"), "vol_mas"),
    (("bajar volumen", "menos volumen", "volumen bajo", "baja el volumen"), "vol_menos"),
    (("pausa", "pausar", "pausa lectura"), "pausa"),
    (("continuar", "seguir", "sigue", "reanudar"), "continuar"),
    (("parrafo anterior", "anterior", "retroceder"), "anterior"),
    (("siguiente parrafo", "siguiente", "adelantar", "adelante"), "siguiente"),
    (("ayuda de encuadre", "guia de encuadre", "encuadre"), "encuadre"),
    (("actualizar", "actualizacion", "buscar actualizacion", "nueva version"), "actualizar"),
    (("tutorial", "bienvenida", "como se usa", "instrucciones"), "tutorial"),
    (("de que color es", "que color es", "color", "colores"), "color"),
    (("significado", "que significa", "definicion", "definir"), "significado"),
    (("traducir al espanol", "al espanol"), "traducir_es"),
    (("traducir", "traduccion", "traduce"), "traducir"),
    (("cambiar perfil", "siguiente perfil", "perfil"), "perfil"),
    (("reiniciar cuenta", "borrar cuenta", "cuenta nueva", "empezar cuenta"), "dinero_reiniciar"),
    (("total", "cuanto llevo", "cuanto suma", "suma total"), "dinero_total"),
    (("billetes", "billete", "monedas", "moneda", "dinero", "plata", "cuanta plata", "cuanto dinero"), "m_dinero"),
    (("materiales", "guardados"), "materiales"),
    (("contar", "objetos", "cuantos"), "m_objetos"),
    (("figuras", "geometricas", "formas"), "m_figuras"),
    (("numeros", "numero", "cifras"), "m_numeros"),
    (("letras", "palabras", "abecedario"), "m_letras"),
    (("leer texto", "texto", "leer"), "m_texto"),
    (("capturar", "captura", "foto", "tomar", "escanear"), "capturar"),
    (("repetir", "otra vez", "de nuevo", "repite"), "repetir"),
    (("detener", "silencio", "callate", "calla", "parar", "para", "basta"), "silencio"),
    (("inicio", "menu", "principal"), "inicio"),
    (("atras", "volver", "regresar", "salir"), "atras"),
]


def _vocabulario():
    """palabra suelta -> orden (para corregir pequeños errores de reconocimiento)."""
    voc = {}
    for claves, orden in ORDENES:
        for c in claves:
            for palabra in c.split():
                if len(palabra) >= 5:
                    voc.setdefault(palabra, orden)
    return voc


_RELLENO_SENA = {"sena", "senas", "gesto", "de", "del", "la", "el", "las", "los", "para", "cual", "cuales", "es", "son",
                 "que", "como", "se", "hace", "hago", "haces", "una", "un", "dime", "dame", "repite", "repiteme", "dice",
                 "dices", "me", "puedes", "decir", "quiero", "saber", "dar", "a", "en", "por", "favor"}


def interpretar_orden(texto):
    """Devuelve la orden que se dijo (o None). Si preguntas por una seña ("¿cuál es la seña de materiales?") devuelve
    'sena:<orden>' (por ejemplo 'sena:materiales'); si pides las señas en general, 'senas_lista'."""
    base = _sin_tildes(texto)
    palabras = base.split()
    pregunta_sena = ("sena" in palabras or "senas" in palabras or
                     ("gesto" in palabras and any(p in palabras for p in ("de", "del", "para", "cual", "que", "como"))))
    if pregunta_sena:
        resto = " ".join(p for p in palabras if p not in _RELLENO_SENA)
        if resto.strip():
            if "voz" in resto.split() and not any(k in resto for k in ("microfono", "gestos")):
                return "sena:voz"
            if resto.strip() in ("ayuda", "senas", "ayuda de senas"):
                return "sena:senas"
            objetivo = _orden_base(resto)
            if objetivo and objetivo != "senas_lista":
                return "sena:" + objetivo
        return "senas_lista"
    return _orden_base(texto)


def _orden_base(texto):
    """Interpreta una orden "normal" (sin preguntas por señas). Tolera tildes, palabras partidas y errores leves."""
    base = _sin_tildes(texto)
    t = " " + base + " "
    pegado = base.replace(" ", "")  # "a tras" -> "atras"
    for claves, orden in ORDENES:
        for c in claves:
            if f" {c} " in t or (len(c) > 4 and c in t) or (len(c.replace(" ", "")) >= 5 and c.replace(" ", "") in pegado):
                return orden
    # Último recurso: palabra casi igual a una orden ("capturan" -> "capturar")
    voc = _vocabulario()
    for palabra in base.split():
        cerca = difflib.get_close_matches(palabra, list(voc), n=1, cutoff=0.8)
        if cerca:
            return voc[cerca[0]]
    return None



RUTA_VOSK = os.path.join(CARPETA_MODELOS, "vosk-es")
URL_VOSK = "https://alphacephei.com/vosk/models/vosk-model-small-es-0.42.zip"  # ~40 MB, una sola vez
# Con una lista cerrada de palabras el reconocimiento sin internet acierta muchísimo más (con tildes, como en el modelo)
GRAMATICA = ["capturar", "captura", "foto", "tomar", "escanear", "atrás", "volver", "regresar", "salir",
             "inicio", "menú", "principal", "repetir", "otra vez", "de nuevo", "repite", "silencio", "detener",
             "calla", "parar", "para", "basta", "leer texto", "texto", "leer", "letras", "palabras", "abecedario",
             "números", "número", "cifras", "figuras", "geométricas", "formas", "contar", "objetos", "cuántos",
             "materiales", "guardados", "ajustes", "configuración", "dispositivos", "cámara", "cambiar cámara",
             "otra cámara", "teléfono", "celular", "cámara del teléfono", "audio", "audífonos", "cambiar audio",
             "micrófono del teléfono", "micrófono del celular", "micrófono de la laptop", "micrófono del computador",
             "micrófono", "activar gestos", "desactivar gestos", "apagar gestos", "activar voz", "desactivar voz",
             "apagar voz", "dejar de escuchar", "escuchar siempre", "voz siempre activa", "modo voz", "gestos", "importar", "imagen", "importar imagen", "wifi", "recibir archivos", "documento", "importar documento", "abrir documento", "archivo", "pdf", "word",
             "más lento", "más despacio", "despacio", "más rápido", "rápido", "subir volumen", "más volumen",
             "bajar volumen", "menos volumen", "pausa", "pausar", "continuar", "seguir", "reanudar", "anterior",
             "retroceder", "párrafo anterior", "siguiente", "siguiente párrafo", "adelantar", "ayuda de encuadre",
             "encuadre", "tutorial", "bienvenida", "cómo se usa", "instrucciones", "color", "de qué color es",
             "qué color es", "significado", "traducir", "traducir al español", "cambiar perfil", "perfil",
             "ayuda", "señas", "lista de señas", "qué señas hay", "ayuda de señas", "seña de voz", "seña de ayuda",
             "actualizar", "actualización", "billetes", "billete", "monedas", "moneda", "dinero", "plata", "total", "reiniciar cuenta", "borrar cuenta",
             "[unk]"]
# Preguntas "¿cuál es la seña de ...?" para cada cosa que tiene seña (con tildes, como en el modelo de voz)
for _cosa in ("leer texto", "letras", "números", "figuras", "contar objetos", "materiales", "ajustes", "capturar",
              "repetir", "silencio", "inicio", "atrás", "voz siempre activa"):
    GRAMATICA[-1:-1] = [f"seña de {_cosa}", f"cuál es la seña de {_cosa}"]


class FlujoRed:
    """Micrófono del teléfono: lee el audio WAV que transmite la app IP Webcam y lo entrega a 16 kHz mono."""

    MAX_BUF = 32000  # ~1 s de audio en espera: si el programa se atrasa, se descarta lo viejo en vez de acumular retraso

    def __init__(self, url, espera=3):
        self.url = url
        self.resp = urllib.request.urlopen(url, timeout=espera)
        try:
            self.canales, self.tasa, self.bits = self._leer_cabecera()
        except Exception:
            self.close()
            raise
        if self.bits != 16:
            raise RuntimeError(f"el teléfono envía audio de {self.bits} bits (se necesita 16)")
        self._buf = bytearray()
        self._cond = threading.Condition()
        self._vivo = True
        self._error = None
        self._prev, self._pos = 0.0, 0.0
        threading.Thread(target=self._leer, daemon=True).start()

    def _exacto(self, n):
        datos = b""
        while len(datos) < n:
            trozo = self.resp.read(n - len(datos))
            if not trozo:
                raise RuntimeError("el teléfono cortó la conexión de audio")
            datos += trozo
        return datos

    def _leer_cabecera(self):
        cab = self._exacto(12)
        if cab[:4] != b"RIFF" or cab[8:12] != b"WAVE":
            raise RuntimeError("esa dirección no entrega audio WAV (usa http://IP:8080/audio.wav)")
        canales = tasa = bits = None
        while True:
            h = self._exacto(8)
            tam = int.from_bytes(h[4:], "little")
            if h[:4] == b"fmt ":
                d = self._exacto(tam)
                canales = int.from_bytes(d[2:4], "little")
                tasa = int.from_bytes(d[4:8], "little")
                bits = int.from_bytes(d[14:16], "little")
            elif h[:4] == b"data":
                break
            else:
                self._exacto(min(tam, 1 << 20))
        if not canales or not tasa:
            raise RuntimeError("cabecera de audio incompleta")
        return canales, tasa, bits

    def _a_16k_mono(self, crudo):
        x = np.frombuffer(crudo, np.int16).astype(np.float32)
        if self.canales > 1:
            x = x[: len(x) // self.canales * self.canales].reshape(-1, self.canales).mean(1)
        paso = self.tasa / 16000.0
        if paso > 1.5:  # filtro simple contra el ruido de "aliasing" al bajar la frecuencia
            k = int(round(paso))
            x = np.convolve(x, np.ones(k, np.float32) / k, mode="same")
        x = np.concatenate(([self._prev], x))
        idx = np.arange(self._pos, len(x) - 1, paso)
        salida = np.interp(idx, np.arange(len(x)), x) if len(idx) else np.zeros(0, np.float32)
        self._pos = (idx[-1] + paso if len(idx) else self._pos) - (len(x) - 1)
        self._prev = float(x[-1])
        return np.clip(salida, -32768, 32767).astype(np.int16).tobytes()

    def _leer(self):
        resto = b""
        # read1 devuelve lo que ya llegó; read(4096) esperaba a juntar 4096 bytes (con audio de 8 kHz son 0,25 s de retraso por trozo)
        leer = getattr(self.resp, "read1", self.resp.read)
        try:
            while self._vivo:
                datos = leer(4096)
                if not datos:
                    raise RuntimeError("el teléfono cortó la conexión de audio")
                datos = resto + datos
                util = len(datos) // (2 * self.canales) * (2 * self.canales)
                resto = datos[util:]
                if util:
                    out = self._a_16k_mono(datos[:util])
                    with self._cond:
                        self._buf += out
                        if len(self._buf) > self.MAX_BUF:
                            del self._buf[:-self.MAX_BUF]
                        self._cond.notify_all()
        except Exception as e:
            with self._cond:
                self._error = e
                self._cond.notify_all()

    def vivo(self):
        return self._vivo and self._error is None

    def vaciar(self):
        """Descarta el audio viejo (para reutilizar la conexión sin oír lo anterior)."""
        with self._cond:
            self._buf.clear()

    def read(self, n):
        """n cuadros de audio (16 kHz, mono, int16) -> (bytes, desbordado)."""
        necesarios = n * 2
        limite = time.time() + 5
        with self._cond:
            while len(self._buf) < necesarios:
                if self._error is not None:
                    raise RuntimeError(str(self._error))
                if time.time() > limite:
                    raise RuntimeError("el teléfono no está enviando audio")
                self._cond.wait(0.2)
            datos = bytes(self._buf[:necesarios])
            del self._buf[:necesarios]
        return datos, False

    def start(self):
        pass

    def stop(self):
        self._vivo = False

    def close(self):
        self._vivo = False
        try:
            self.resp.close()
        except Exception:
            pass


def registrar_voz(linea):
    """Anota en debug/voz.log lo que oyó la app (para revisar cuando algo falla)."""
    try:
        with open(os.path.join(CARPETA_DEBUG, "voz.log"), "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%H:%M:%S')}  {linea}\n")
    except OSError:
        pass


class _Prestamo:
    """Conexión de red compartida con el teléfono: stop/close no la cierran, así la siguiente escucha
    la reutiliza al instante (abrir una conexión nueva cada vez tardaba segundos)."""

    def __init__(self, flujo):
        self.f = flujo
        flujo.vaciar()

    def read(self, n):
        return self.f.read(n)

    def start(self):
        pass

    def stop(self):
        pass

    def close(self):
        pass


class Microfono:
    RATE = 16000

    def __init__(self):
        self.modelo = None  # modelo de Vosk (sin internet)
        self.dispositivo = leer_config().get("microfono")  # índice del micrófono; None = predeterminado
        self._red = None    # conexión de audio abierta con el teléfono (se reutiliza)
        self.aviso = None   # función(texto) para avisar a la persona (la pone la app)

    def disponible(self):
        # el micrófono del teléfono no necesita sounddevice; el de la laptop sí
        entrada = sd is not None or isinstance(self.dispositivo, str)
        return entrada and (self.modelo is not None or sr is not None or vosk is not None)

    # ---- micrófono del teléfono (conexión persistente)
    def _red_flujo(self, url):
        f = self._red
        if f is not None and f.url == url and f.vivo():
            return f
        self.cerrar_red()
        self._red = FlujoRed(url)
        return self._red

    def conectar_red(self, url):
        """Abre (o reutiliza) la conexión con el teléfono y espera a que llegue audio. Lanza error si no se puede."""
        f = self._red_flujo(url)
        f.read(1600)
        return f

    def cerrar_red(self):
        f, self._red = self._red, None
        if f is not None:
            f.close()

    def usar_laptop(self):
        """Vuelve al micrófono predeterminado de la laptop (y se acuerda para la próxima vez)."""
        self.dispositivo = None
        guardar_config(microfono=None)
        return self.nombre_dispositivo()

    def preparar(self, aviso=None):
        """Carga (y la primera vez descarga) el reconocedor sin internet. No hace nada si falta vosk."""
        if vosk is None or self.modelo is not None:
            return
        try:
            if not os.path.isdir(os.path.join(RUTA_VOSK, "am")):
                if aviso:
                    aviso("Descargando el reconocedor de voz sin internet. Solo pasa la primera vez.")
                print(f"Descargando el modelo de voz (~40 MB) a {RUTA_VOSK} ...")
                zip_ruta = RUTA_VOSK + ".zip"
                urllib.request.urlretrieve(URL_VOSK, zip_ruta)
                tmp = RUTA_VOSK + "_tmp"
                with zipfile.ZipFile(zip_ruta) as z:
                    z.extractall(tmp)
                os.remove(zip_ruta)
                carpetas = [d for d in os.listdir(tmp) if os.path.isdir(os.path.join(tmp, d))]
                shutil.rmtree(RUTA_VOSK, ignore_errors=True)
                shutil.move(os.path.join(tmp, carpetas[0]), RUTA_VOSK)
                shutil.rmtree(tmp, ignore_errors=True)
            self.modelo = vosk.Model(RUTA_VOSK)
            print("Reconocimiento de voz sin internet: listo.")
        except Exception as e:
            print(f"No se pudo preparar el reconocimiento de voz sin internet: {e}")

    @staticmethod
    def _nivel(bloque):
        return float(np.sqrt(np.mean(bloque.astype(np.float64) ** 2)))

    def _reconocer(self, crudo):
        if sr is not None:  # con internet (Google)
            try:
                return sr.Recognizer().recognize_google(sr.AudioData(crudo, self.RATE, 2), language="es-CO")
            except sr.UnknownValueError:
                return ""
        raise RuntimeError("no hay motor de voz")

    # ---- dispositivos de entrada
    def listar_microfonos(self):
        """[(índice, nombre)] de los micrófonos, sin repetidos de otras APIs de audio de Windows."""
        try:
            api = sd.query_devices(kind="input")["hostapi"]
            return [(i, d["name"]) for i, d in enumerate(sd.query_devices())
                    if d["max_input_channels"] > 0 and d["hostapi"] == api]
        except Exception as e:
            print(f"No se pudo listar los micrófonos: {e}")
            return []

    def nombre_dispositivo(self):
        if isinstance(self.dispositivo, str):
            return "micrófono del teléfono"
        try:
            return sd.query_devices(self.dispositivo if self.dispositivo is not None else sd.default.device[0])["name"]
        except Exception:
            return "predeterminado"

    def siguiente_microfono(self):
        lista = [None] + [i for i, _ in self.listar_microfonos()]
        tel = leer_config().get("telefono_audio")
        if tel:
            lista.append(tel)  # el micrófono del teléfono entra en la rotación
        sig = lista[(lista.index(self.dispositivo) + 1) % len(lista)] if self.dispositivo in lista else None
        self.dispositivo = sig
        guardar_config(microfono=sig)
        return self.nombre_dispositivo()

    def _abrir_flujo(self, bloque):
        """Abre el micrófono a 16 kHz; si el dispositivo no lo admite, usa su frecuencia y remuestrea.
        Si el micrófono elegido ya no existe (por ejemplo, audífonos desconectados), prueba el predeterminado."""
        if isinstance(self.dispositivo, str):  # micrófono del teléfono por Wi-Fi
            try:
                return _Prestamo(self._red_flujo(self.dispositivo)), 1.0
            except Exception as e:
                print(f"Micrófono del teléfono no disponible ({e}).")
                if sd is None:
                    raise RuntimeError(f"no se pudo conectar con el teléfono ({e})")
                # Sin respaldo, la app se quedaba sin micrófono cuando el teléfono no estaba en la red.
                # Solo para esta sesión (no se borra lo guardado): la próxima vez vuelve a intentar con el teléfono.
                self.dispositivo = None
                if self.aviso:
                    self.aviso("No pude conectar con el micrófono del teléfono. Uso el micrófono de la laptop.")
        else:
            self.cerrar_red()  # ya no se usa el teléfono: soltar la conexión (ahorra batería y Wi-Fi)
        primero = None
        candidatos = [self.dispositivo] + ([None] if self.dispositivo is not None else [])
        for disp in candidatos:
            try:
                f = sd.RawInputStream(samplerate=self.RATE, channels=1, dtype="int16", blocksize=bloque, device=disp)
                f.start()
                if disp is not self.dispositivo:
                    print("El micrófono elegido no está disponible: se usa el predeterminado.")
                    self.dispositivo = None
                return f, 1.0
            except Exception as e:
                primero = primero or e
                try:
                    info = sd.query_devices(disp if disp is not None else sd.default.device[0])
                    tasa = int(info["default_samplerate"])
                    f = sd.RawInputStream(samplerate=tasa, channels=1, dtype="int16",
                                          blocksize=int(bloque * tasa / self.RATE), device=disp)
                    f.start()
                    print(f"El micrófono no admite 16 kHz ({e}); se usa {tasa} Hz y se convierte.")
                    if disp is not self.dispositivo:
                        self.dispositivo = None
                    return f, tasa / self.RATE
                except Exception:
                    continue
        raise RuntimeError(f"No se pudo abrir el micrófono: {primero}")

    @staticmethod
    def _a_16k(datos, factor):
        if factor == 1.0:
            return bytes(datos)
        x = np.frombuffer(bytes(datos), np.int16).astype(np.float32)
        n = int(len(x) / factor)
        return np.interp(np.linspace(0, len(x) - 1, n), np.arange(len(x)), x).astype(np.int16).tobytes()

    @staticmethod
    def _ganancia(audio, pico):
        """Sube el volumen hasta ~8000 de pico (máx. x10) si el micrófono está bajo."""
        x = np.frombuffer(audio, np.int16)
        if len(x) == 0:
            return audio, pico
        actual = float(np.abs(x).max())
        pico = max(actual, pico * 0.98)  # el pico baja despacio
        g = min(10.0, max(1.0, 8000.0 / max(pico, 1.0)))
        if g > 1.05:
            x = np.clip(x.astype(np.float32) * g, -32768, 32767).astype(np.int16)
            return x.tobytes(), pico
        return audio, pico

    def escuchar(self, max_seg=7.0, al_oir=None):
        """Devuelve lo que se dijo ('' si no se entendió). 'al_oir(texto)' recibe lo que va entendiendo."""
        if self.modelo is not None:
            return self._escuchar_vosk(max_seg, al_oir)
        return self._escuchar_vad(max_seg)

    def _escuchar_vosk(self, max_seg, al_oir):
        """Flujo continuo hacia Vosk. Termina en cuanto lo que se va entendiendo deja de cambiar
        (no hace falta esperar a que acabe el tiempo máximo)."""
        rec = vosk.KaldiRecognizer(self.modelo, self.RATE, json.dumps(GRAMATICA, ensure_ascii=False))
        bloque = 1600  # 0,1 s
        flujo, factor = self._abrir_flujo(bloque)
        ultimo, t_cambio = "", time.time()
        pico, pico_real = 800.0, 0
        grabado = bytearray()
        parciales = []
        resultado = ""
        t_ini = time.time()
        try:
            fin = t_ini + max_seg
            while time.time() < fin:
                datos, _ = flujo.read(int(bloque * factor))
                audio = self._a_16k(datos, factor)
                grabado += audio
                pico_real = max(pico_real, int(np.abs(np.frombuffer(audio, np.int16)).max()) if len(audio) else 0)
                audio, pico = self._ganancia(audio, pico)
                if rec.AcceptWaveform(audio):
                    t = json.loads(rec.Result()).get("text", "").replace("[unk]", "").strip()
                    if t:
                        resultado = t
                        break
                else:
                    parcial = json.loads(rec.PartialResult()).get("partial", "").replace("[unk]", "").strip()
                    if parcial != ultimo:
                        ultimo, t_cambio = parcial, time.time()
                        if parcial:
                            parciales.append(parcial)
                            if al_oir:
                                al_oir(parcial)
                    elif parcial:
                        quieto = time.time() - t_cambio
                        # ya terminó de hablar: 0,5 s quieto si es una orden conocida, 0,8 s si no
                        if quieto >= (0.4 if interpretar_orden(parcial) else 0.7):
                            t = json.loads(rec.FinalResult()).get("text", "").replace("[unk]", "").strip()
                            resultado = t or parcial
                            break
            else:
                resultado = json.loads(rec.FinalResult()).get("text", "").replace("[unk]", "").strip() or ultimo
            return resultado
        finally:
            flujo.stop()
            flujo.close()
            self._guardar_debug(bytes(grabado), pico_real, parciales, resultado, time.time() - t_ini)

    def escuchar_continuo(self, debe_parar, ocupado, al_texto, al_oir=None):
        """Voz siempre activa: abre el micrófono UNA vez y lo mantiene abierto (abrir y cerrar cada pocos
        segundos falla en Windows). Mientras la app habla ('ocupado') descarta el audio para no oírse a sí misma."""
        rec = vosk.KaldiRecognizer(self.modelo, self.RATE, json.dumps(GRAMATICA, ensure_ascii=False))
        bloque = 1600  # 0,1 s
        flujo, factor = self._abrir_flujo(bloque)
        disp = self.dispositivo  # con qué micrófono se abrió (puede cambiar si hubo respaldo)
        ultimo, t_cambio, pico = "", time.time(), 800.0
        try:
            while not debe_parar():
                if self.dispositivo != disp:
                    return  # cambiaste de micrófono: el bucle de afuera lo vuelve a abrir con el nuevo
                datos, _ = flujo.read(int(bloque * factor))
                if ocupado():  # la app está hablando: no escuchar
                    try:
                        rec.Reset()
                    except Exception:
                        rec = vosk.KaldiRecognizer(self.modelo, self.RATE, json.dumps(GRAMATICA, ensure_ascii=False))
                    ultimo = ""
                    continue
                audio, pico = self._ganancia(self._a_16k(datos, factor), pico)
                texto = ""
                if rec.AcceptWaveform(audio):
                    texto = json.loads(rec.Result()).get("text", "").replace("[unk]", "").strip()
                else:
                    parcial = json.loads(rec.PartialResult()).get("partial", "").replace("[unk]", "").strip()
                    if parcial != ultimo:
                        ultimo, t_cambio = parcial, time.time()
                        if parcial and al_oir:
                            al_oir(parcial)
                    elif parcial and time.time() - t_cambio >= (0.4 if interpretar_orden(parcial) else 0.7):
                        texto = json.loads(rec.FinalResult()).get("text", "").replace("[unk]", "").strip() or parcial
                if texto:
                    ultimo = ""
                    try:
                        rec.Reset()
                    except Exception:
                        pass
                    al_texto(texto)
        finally:
            flujo.stop()
            flujo.close()

    def _guardar_debug(self, crudo, pico, parciales, resultado, seg):
        """Guarda lo último que se grabó (debug/ultimo_audio.wav) y una línea en debug/voz.log."""
        try:
            with wave.open(os.path.join(CARPETA_DEBUG, "ultimo_audio.wav"), "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(self.RATE)
                w.writeframes(crudo)
        except Exception:
            pass
        registrar_voz(f"mic={self.nombre_dispositivo()!r} pico={pico} duró={seg:.1f}s "
                      f"parciales={parciales[-3:]} final={resultado!r} orden={interpretar_orden(resultado) if resultado else None}")

    def _escuchar_vad(self, max_seg):
        """Sin Vosk (solo con internet): graba hasta el silencio y se lo manda a Google."""
        bloque = int(self.RATE * 0.1)
        previo, datos, hablando, silencio = collections.deque(maxlen=3), [], False, 0
        flujo, factor = self._abrir_flujo(bloque)
        try:
            ruido = [self._nivel(np.frombuffer(flujo.read(int(bloque * factor))[0], np.int16)) for _ in range(4)]
            umbral = max(150.0, float(np.mean(ruido)) * 2.5)
            for _ in range(int(max_seg / 0.1)):
                b = np.frombuffer(self._a_16k(flujo.read(int(bloque * factor))[0], factor), np.int16).copy()
                if self._nivel(b) > umbral:
                    if not hablando:
                        datos.extend(previo)
                    hablando, silencio = True, 0
                    datos.append(b)
                elif hablando:
                    datos.append(b)
                    silencio += 1
                    if silencio >= 8:
                        break
                else:
                    previo.append(b)
        finally:
            flujo.stop()
            flujo.close()
        if not hablando:
            return ""
        return self._reconocer(np.concatenate(datos).astype(np.int16).tobytes())

class CamaraMJPEG:
    """Video MJPEG del teléfono (IP Webcam, DroidCam...) leído directamente por HTTP.
    Más rápido que pasar por OpenCV/FFmpeg: guarda solo el ÚLTIMO cuadro (nunca se atrasa) y el JPEG se decodifica
    únicamente cuando alguien lo pide (en el menú no se decodifica nada). Imita lo mínimo de cv2.VideoCapture."""

    def __init__(self, url, espera=4):
        self.url = url
        self.ancho = self.alto = 0
        self._cond = threading.Condition()
        self._jpg, self._n, self._visto = None, 0, 0
        self._error, self._vivo = None, True
        self.resp = urllib.request.urlopen(url, timeout=espera)
        threading.Thread(target=self._leer, daemon=True).start()
        if not self._esperar(espera):  # que llegue un cuadro de verdad
            self.release()
            raise RuntimeError(str(self._error or "el teléfono no envía video MJPEG"))

    @staticmethod
    def _largo(buf, ini):
        """Largo del JPEG según la cabecera 'Content-Length' de su parte (0 si no hay)."""
        cab = bytes(buf[max(0, ini - 300):ini])
        i = cab.rfind(b"Content-Length:")
        if i < 0:
            return 0
        digitos = cab[i + 15:].split(b"\r", 1)[0].strip()
        return int(digitos) if digitos.isdigit() else 0

    def _leer(self):
        leer = getattr(self.resp, "read1", self.resp.read)
        buf = bytearray()
        try:
            while self._vivo:
                datos = leer(65536)
                if not datos:
                    raise RuntimeError("el teléfono cortó el video")
                buf += datos
                ultimo = None
                while True:  # puede haber varios cuadros completos juntos: solo importa el último
                    ini = buf.find(b"\xff\xd8")
                    if ini < 0:
                        if len(buf) > 300:
                            del buf[:-300]
                        break
                    largo = self._largo(buf, ini)
                    if largo:
                        fin = ini + largo
                        completo = len(buf) >= fin
                    else:
                        f = buf.find(b"\xff\xd9", ini + 2)
                        fin, completo = f + 2, f >= 0
                    if not completo:
                        del buf[:max(0, ini - 300)]  # conservar la cabecera para leer el largo en la próxima vuelta
                        break
                    ultimo = bytes(buf[ini:fin])
                    del buf[:fin]
                if ultimo is not None:
                    with self._cond:
                        self._jpg, self._n = ultimo, self._n + 1
                        self._cond.notify_all()
                if len(buf) > 8_000_000:  # seguridad: algo no es MJPEG
                    buf.clear()
        except Exception as e:
            with self._cond:
                self._error = e
                self._cond.notify_all()

    def _esperar(self, segundos):
        limite = time.time() + segundos
        with self._cond:
            while self._n <= self._visto:
                if self._error is not None or not self._vivo or time.time() > limite:
                    return False
                self._cond.wait(0.1)
            self._visto = self._n
        return True

    # ---- lo mínimo de cv2.VideoCapture que usa la app
    def isOpened(self):
        return self._vivo and self._error is None

    def grab(self):
        return self._esperar(5)

    def retrieve(self):
        with self._cond:
            jpg = self._jpg
        if jpg is None:
            return False, None
        img = cv2.imdecode(np.frombuffer(jpg, np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            return False, None
        self.alto, self.ancho = img.shape[:2]
        return True, img

    def read(self):
        return self.retrieve() if self.grab() else (False, None)

    def get(self, prop):
        return {3: self.ancho, 4: self.alto}.get(int(prop), 0)

    def set(self, prop, valor):
        return False

    def release(self):
        self._vivo = False
        try:
            self.resp.close()
        except Exception:
            pass


class LectorCamara:
    """Lee la cámara en su propio hilo: la ventana nunca se queda esperando a que llegue un cuadro."""

    SEG_PARA_PERDIDA = 3.0  # segundos seguidos sin cuadros en una cámara de red = conexión perdida

    def __init__(self, cap, necesita, red=False, al_perder=None):
        self.cap = cap
        self.necesita = necesita  # función: ¿hace falta mirar la cámara ahora?
        self.red = red            # cámara del teléfono (flujo por Wi-Fi)
        self.al_perder = al_perder
        self.frame = None
        self.n = 0
        self.fps = 0.0
        self._vivo = True
        self._hilo = threading.Thread(target=self._bucle, daemon=True)
        self._hilo.start()

    def _bucle(self):
        t0, cuenta = time.time(), 0
        t_ok, avisado = time.time(), False
        while self._vivo:
            try:
                if self.red:
                    # Por Wi-Fi hay que consumir los cuadros AL RITMO del teléfono. Si se leen más lento (como hacía el
                    # modo "menú", 20 por segundo contra ~30 que llegan), se acumulan y el video se atrasa cada vez más.
                    # grab() espera el siguiente cuadro, así que este bucle sigue solo el ritmo del flujo.
                    ok = self.cap.grab()
                    if ok and self.necesita():
                        ok, f = self.cap.retrieve()
                        if ok and f is not None:
                            self.frame = f
                            self.n += 1
                            cuenta += 1
                    if ok:
                        t_ok, avisado = time.time(), False
                    else:
                        time.sleep(0.05)
                        if not avisado and time.time() - t_ok > self.SEG_PARA_PERDIDA and self.al_perder and self._vivo:
                            avisado = True  # una sola vez por lector
                            self.al_perder()
                elif self.necesita():
                    ok, f = self.cap.read()
                    if ok and f is not None:
                        self.frame = f
                        self.n += 1
                        cuenta += 1
                    else:
                        time.sleep(0.02)
                else:  # en el menú y sin gestos: solo "vaciar" la cámara, casi sin gastar procesador
                    self.cap.grab()
                    time.sleep(0.05)
                ahora = time.time()
                if ahora - t0 >= 2.0:
                    self.fps = cuenta / (ahora - t0)
                    t0, cuenta = ahora, 0
            except Exception as e:
                print(f"Lector de cámara detenido: {e}")
                break

    def ultimo(self):
        return self.frame, self.n

    def parar(self, espera=None):
        """Detiene el hilo. Una cámara de red puede estar bloqueada hasta 5 s esperando al teléfono, así que se
        espera un poco más antes de que se suelte la cámara. Devuelve True si el hilo ya terminó."""
        self._vivo = False
        if espera is None:
            espera = 6.0 if self.red else 1.0
        if self._hilo.is_alive() and self._hilo is not threading.current_thread():
            self._hilo.join(espera)
        return not self._hilo.is_alive()


# ---------------------------------------------------------------------------
# Aplicación
# ---------------------------------------------------------------------------
class EduAccesibleApp:
    ANCHO_VIDEO, ALTO_VIDEO = 560, 315
    _cap = None
    lector = None

    @property
    def cap(self):
        return self._cap

    @cap.setter
    def cap(self, valor):
        if self.lector is not None:
            self.lector.parar()
            self.lector = None
        self._cap = valor
        if valor is not None:
            self.lector = LectorCamara(valor, lambda: self.pantalla == "modo" or self.gestos_activos,
                                       red=isinstance(self.indice_camara, str), al_perder=self._camara_perdida)

    def __init__(self, root):
        self.root = root
        self.root.title("EduAccesible - La información también se escucha")
        for _ico in (os.path.join(os.path.dirname(os.path.abspath(sys.argv[0])), "logo.ico"), os.path.join(BASE_DIR, "logo.ico")):
            if os.path.exists(_ico):
                try:
                    self.root.iconbitmap(_ico)
                except Exception:
                    pass
                break
        self.root.geometry("980x700")
        self.root.minsize(900, 640)
        self.root.config(bg=CREMA)

        self.voz = Voz()
        self.lectura = Lectura(self.voz)
        self.ultimo_texto, self.ultima_palabra = "", ""
        self.ayuda_encuadre = bool(leer_config().get("encuadre"))
        self._t_encuadre, self._msg_encuadre, self._t_msg_encuadre = 0.0, "", 0.0
        self.ocr = MotorOCR()
        threading.Thread(target=self.ocr.cargar, daemon=True).start()  # carga en segundo plano
        self.detector = DetectorObjetos(aviso=lambda t: self.voz.hablar(t))
        self.mic = Microfono()
        self.mic.aviso = lambda t: self.anunciar(t)
        threading.Thread(target=self._preparar_mic, daemon=True).start()
        self._detector_iniciado = False  # el detector de objetos se carga solo cuando lo necesitas
        self.cambiando_camara = False
        self.indice_camara = leer_config().get("camara", 0)
        self.escuchando = False
        self.voz_continua = False
        self.modo_lento = hay_modo_lento()
        self._lentos, self._avisado_lento = 0, False
        self._gen = 0              # sube cada vez que se cambia de pantalla
        self._gen_analisis = None  # a qué "pantalla" pertenece el análisis en curso
        self.gestos = Gestos()
        self.gestos_activos = False
        self.modo_practica = False  # seña de ayuda: dice qué hace cada seña sin ejecutarla
        self._ev_gestos = threading.Event()
        self._frame_gestos = None
        self._visto, self._error_gestos, self._texto_gestos = None, "", ""
        self._fps_gestos = 0.0
        self._ultimo_n = -1
        self._t_fps = time.time()
        threading.Thread(target=self._bucle_gestos, daemon=True).start()
        self.modo_actual = "texto"
        self.pantalla = "menu"
        self.ultimo_frame = None
        self.frames_recientes = collections.deque(maxlen=8)  # para elegir el más nítido
        self.ultimo_audio = ""
        self.procesando = False
        self.cola_ui = queue.Queue()  # para actualizar la interfaz desde otros hilos

        self._construir_interfaz()

        self.root.bind("<Key>", self.tecla)
        self.root.bind("<Escape>", lambda e: self.atras())
        self.root.protocol("WM_DELETE_WINDOW", self.cerrar)

        self.actualizar_video()
        self._bombear_ui()
        self.wifi = ServidorWifi(CARPETA_ENTRADA)
        self._entrada_vista = set(os.listdir(CARPETA_ENTRADA))  # lo que ya estaba no se vuelve a leer
        self.root.after(4000, self.vigilar_entrada)
        if leer_config().get("letra_grande"):
            self._aplicar_letra(True)
        if not leer_config().get("bienvenida_vista"):
            guardar_config(bienvenida_vista=True)
            self.root.after(2500, self.tutorial)  # primera vez: explica cómo se usa
        else:
            self.voz.hablar("EduAccesible iniciado. Elige una función en el menú.")
        self.root.after(15000, self.autoprueba)
        threading.Thread(target=self.buscar_version, daemon=True).start()
        # La cámara se abre en segundo plano: antes la ventana no aparecía hasta que terminaba (hasta 5 s si la
        # última cámara era la del teléfono y no respondía).
        threading.Thread(target=self._abrir_camara_inicial, daemon=True).start()

    def _abrir_camara_inicial(self):
        cap = self.abrir_camara_auto()
        if cap is None:
            self.ui(lambda: self.video_label.config(text="Cámara no disponible", fg="white", font=("Segoe UI", 16, "bold")))
            self.voz.hablar("No se pudo abrir la cámara. Puedes importar imágenes desde materiales.")
            return
        self.cap = cap
        if leer_config().get("gestos"):  # los gestos necesitan la cámara ya abierta
            self.ui(lambda: self.alternar_gestos(True, silencioso=True))

    # ---------------------------- Interfaz --------------------------------
    @staticmethod
    def boton(padre, texto, color, comando, fg="white", fuente=15, **kw):
        b = tk.Button(padre, text=texto, command=comando, bg=color, fg=fg,
                      activebackground=Interfaz_oscuro(color), activeforeground=fg,
                      font=("Segoe UI", fuente, "bold"), relief="flat", bd=0,
                      cursor="hand2", highlightthickness=1, highlightbackground=CREMA, highlightcolor=TEXTO, **kw)
        b.bind("<Enter>", lambda e: b.config(bg=Interfaz_oscuro(color)))   # resalta el botón bajo el mouse
        b.bind("<Leave>", lambda e: b.config(bg=color))
        return b

    def _construir_interfaz(self):
        cab = tk.Frame(self.root, bg=CREMA)
        cab.pack(pady=(10, 0))
        tk.Label(cab, text="Edu", font=("Segoe UI", 30, "bold"), fg=NARANJA, bg=CREMA).pack(side="left")
        tk.Label(cab, text="Accesible", font=("Segoe UI", 30, "bold"), fg=VERDE, bg=CREMA).pack(side="left")
        tk.Label(self.root, text="La información también se escucha",
                 font=("Segoe UI", 13, "italic"), fg=TEXTO, bg=CREMA).pack(pady=(0, 6))

        self.lbl_estado = tk.Label(self.root, text="", font=("Segoe UI", 13, "bold"), fg=TEXTO, bg=CREMA)
        self.lbl_estado.pack(side="bottom", fill="x", pady=(0, 6))

        cuerpo = tk.Frame(self.root, bg=CREMA)
        cuerpo.pack(fill="both", expand=True, padx=15, pady=5)

        # Botones laterales grandes (cámara, play, inicio, atrás)
        barra = tk.Frame(cuerpo, bg=CREMA)
        barra.pack(side="right", fill="y", padx=(12, 0))
        for texto, color, cmd in [("📷\nCapturar", NARANJA, self.capturar),
                                  ("▶\nRepetir", VERDE, self.repetir),
                                  ("🏠\nInicio", NARANJA, self.ir_inicio),
                                  ("↩\nAtrás", VERDE, self.atras)]:
            b = self.boton(barra, texto, color, cmd, fuente=13, width=9)
            b.pack(pady=7, ipady=14)
            self._botones_barra = getattr(self, "_botones_barra", []) + [b]
        self._compactar_barra(leer_config().get("letra_grande", False))

        self.contenido = tk.Frame(cuerpo, bg=CREMA)
        self.contenido.pack(side="left", fill="both", expand=True)
        self.pantallas = {
            "menu": self._pantalla_menu(),
            "modo": self._pantalla_modo(),
            "materiales": self._pantalla_materiales(),
            "ajustes": self._pantalla_ajustes(),
            "senas": self._pantalla_senas(),
        }
        self.mostrar("menu")

    def _pantalla_menu(self):
        ext, f = self._marco_scroll()
        tk.Label(f, text="¿Qué quieres hacer?", font=("Segoe UI", 18, "bold"), fg=TEXTO, bg=CREMA).pack(pady=(5, 10))
        opciones = [
            ("📖  1. Leer texto   ☝ 1 dedo", VERDE, "white", lambda: self.abrir_modo("texto")),
            ("🅰  2. Reconocer letras y palabras   ✌ 2 dedos", NARANJA, "white", lambda: self.abrir_modo("letras")),
            ("123  3. Reconocer números   3 dedos", AMARILLO, TEXTO, lambda: self.abrir_modo("numeros")),
            ("🔷  4. Figuras geométricas   4 dedos", VERDE, "white", lambda: self.abrir_modo("figuras")),
            ("🔢  5. Contar objetos   🖐 mano abierta", NARANJA, "white", lambda: self.abrir_modo("objetos")),
            ("📁  6. Materiales guardados   🖐+☝ dos manos", VERDE, "white", self.abrir_materiales),
            ("⚙  7. Ajustes   🖐+✌ dos manos", AMARILLO, TEXTO, self.abrir_ajustes),
            ("💵  8. Billetes y monedas (Colombia)", VERDE, "white", lambda: self.abrir_modo("dinero")),
        ]
        for texto, color, fg, cmd in opciones:
            self.boton(f, texto, color, cmd, fg=fg, fuente=16).pack(fill="x", padx=20, pady=5, ipady=9)
        tk.Label(f, text="Otras señas: 👊 repetir · 👊👊 capturar · 🖐🖐 silencio · ☝☝ inicio · ✌✌ atrás · 👍 voz activa · 3+3 dedos ayuda. "
                         "Pregunta: «¿cuál es la seña de materiales?»",
                 font=("Segoe UI", 10, "bold"), fg=VERDE, bg=CREMA, wraplength=620).pack(pady=(4, 0))
        tk.Label(f, text="Atajos: 1-7 elegir · C capturar · R repetir · V orden por voz · J señas · H voz siempre activa · I cambiar micrófono · L micrófono laptop · S silencio · M inicio · Esc atrás",
                 font=("Segoe UI", 10), fg=TEXTO, bg=CREMA, wraplength=620).pack(pady=8)
        return ext

    def _pantalla_modo(self):
        ext, f = self._marco_scroll()
        self.lbl_titulo_modo = tk.Label(f, text="", font=("Segoe UI", 18, "bold"), fg=VERDE, bg=CREMA)
        self.lbl_titulo_modo.pack(pady=(0, 6))
        self.video_label = tk.Label(f, bg="#000000", bd=2, relief="solid")
        self.video_label.pack()
        self.lbl_resultado = tk.Label(f, text="", font=("Segoe UI", 15), fg=TEXTO, bg=CREMA,
                                      wraplength=560, justify="left", height=5)
        self.lbl_resultado.pack(pady=(10, 4), fill="x")
        fila = tk.Frame(f, bg=CREMA)
        fila.pack(pady=4)
        # Los botones se acomodan en una cuadrícula: con letra grande bajan de renglón en vez de salirse de la pantalla.
        todos = [("🖼 Imagen", NARANJA, "white", self.importar_imagen), ("📄 Documento", NARANJA, "white", self.importar_documento),
                 ("🎤 Hablar (V)", VERDE, "white", self.escuchar_orden),
                 ("📚 Significado", VERDE, "white", self.decir_significado), ("🌐 Traducir", NARANJA, "white", lambda: self.traducir_ultimo("es", "en")),
                 ("⏮ Anterior (B)", AMARILLO, TEXTO, lambda: self.mover_lectura(-1)), ("⏯ Pausa (P)", AMARILLO, TEXTO, self.pausar_lectura),
                 ("⏭ Siguiente (N)", AMARILLO, TEXTO, lambda: self.mover_lectura(1)),
                 ("🐢 Más lento", AMARILLO, TEXTO, lambda: self.cambiar_voz(vel=-1)), ("🐇 Más rápido", AMARILLO, TEXTO, lambda: self.cambiar_voz(vel=1))]
        for i, (txt, color, fg, cmd) in enumerate(todos):
            self.boton(fila, txt, color, cmd, fg=fg, fuente=11).grid(row=i // 3, column=i % 3, padx=4, pady=3, ipady=4, ipadx=6, sticky="ew")
        return ext

    def _marco_scroll(self):
        """Pantalla con barra de desplazamiento (rueda del mouse incluida): si el contenido no cabe, se puede bajar."""
        ext = tk.Frame(self.contenido, bg=CREMA)
        lienzo = tk.Canvas(ext, bg=CREMA, highlightthickness=0)
        barra = tk.Scrollbar(ext, orient="vertical", command=lienzo.yview)
        lienzo.configure(yscrollcommand=barra.set)
        barra.pack(side="right", fill="y")
        lienzo.pack(side="left", fill="both", expand=True)
        interno = tk.Frame(lienzo, bg=CREMA)
        ventana = lienzo.create_window((0, 0), window=interno, anchor="nw")
        interno.bind("<Configure>", lambda e: lienzo.configure(scrollregion=lienzo.bbox("all")))
        lienzo.bind("<Configure>", lambda e: lienzo.itemconfigure(ventana, width=e.width))

        def rueda(e):
            if ext.winfo_ismapped() and interno.winfo_reqheight() > lienzo.winfo_height():
                lienzo.yview_scroll(int(-e.delta / 120) or (-1 if e.delta > 0 else 1), "units")
        lienzo.bind_all("<MouseWheel>", rueda, add="+")
        return ext, interno

    def _pantalla_ajustes(self):
        ext, f = self._marco_scroll()
        tk.Label(f, text="Ajustes", font=("Segoe UI", 18, "bold"), fg=VERDE, bg=CREMA).pack(pady=(0, 8))
        for texto, color, fg, cmd in [
            ("🔄  Cambiar cámara  (K)", VERDE, "white", self.cambiar_camara),
            ("📱  Teléfono: cámara y micrófono a la vez", NARANJA, "white", self.conectar_telefono_completo),
            ("📷  Solo la cámara del teléfono", AMARILLO, TEXTO, self.conectar_telefono),
            ("🎧  Salida de audio / audífonos  (A)", VERDE, "white", self.cambiar_audio),
            ("🖐  Gestos de mano: apagados  (G)", NARANJA, "white", self.alternar_gestos),
            ("🎤  Voz siempre activa: apagada  (H)", AMARILLO, TEXTO, self.alternar_voz_continua),
            ("🗣  Dar una orden por voz  (V)", VERDE, "white", self.escuchar_orden),
            ("🖐  Ver y escuchar las señas  (J)", AMARILLO, TEXTO, self.abrir_senas),
            ("🎙  Cambiar micrófono  (I)", NARANJA, "white", self.cambiar_microfono),
            ("💻  Micrófono de la laptop  (L)", VERDE, "white", self.usar_mic_laptop),
            ("🐢  Voz más lenta", VERDE, "white", lambda: self.cambiar_voz(vel=-1)),
            ("🐇  Voz más rápida", NARANJA, "white", lambda: self.cambiar_voz(vel=1)),
            ("🔉  Bajar volumen", AMARILLO, TEXTO, lambda: self.cambiar_voz(vol=-15)),
            ("🔊  Subir volumen", VERDE, "white", lambda: self.cambiar_voz(vol=15)),
            ("🎯  Ayuda de encuadre: " + ("activada" if leer_config().get("encuadre") else "apagada"), NARANJA, "white", self.alternar_encuadre),
            ("🔠  Letra grande: " + ("sí" if leer_config().get("letra_grande") else "no"), AMARILLO, TEXTO, self.alternar_letra),
            ("◐  Alto contraste: " + ("activado" if leer_config().get("contraste") else "apagado") + " (reinicia)", VERDE, "white", self.alternar_contraste),
            ("🎨  ¿De qué color es? (apunta al centro)", NARANJA, "white", self.decir_color),
            ("👤  Perfil: " + leer_config().get("perfil", "General"), AMARILLO, TEXTO, self.cambiar_perfil),
            ("📖  Tutorial hablado", VERDE, "white", self.tutorial),
            ("🐢  Modo equipo lento: " + ("activado" if hay_modo_lento() else "apagado"), NARANJA, "white", self.alternar_lento),
            ("🔄  Buscar actualización  (" + VERSION_APP + ")", VERDE, "white", self.pedir_actualizacion),
            ("🛠  Diagnóstico (para enviar si algo falla)", AMARILLO, TEXTO, self.abrir_diagnostico),
            ("📱  Micrófono del teléfono (por Wi-Fi)", AMARILLO, TEXTO, self.conectar_mic_telefono),
        ]:
            b = self.boton(f, texto, color, cmd, fg=fg, fuente=13)
            b.pack(fill="x", padx=30, pady=3, ipady=6)
            if "Gestos" in texto:
                self.btn_gestos = b
            if "siempre activa" in texto:
                self.btn_voz = b
            if "equipo lento" in texto:
                self.btn_lento = b
            if "encuadre" in texto:
                self.btn_encuadre = b
            if "Letra grande" in texto:
                self.btn_letra = b
            if "Alto contraste" in texto:
                self.btn_contraste = b
            if "Perfil:" in texto:
                self.btn_perfil = b
            if "actualización" in texto:
                self.btn_actualizar = b
        return ext

    def _pantalla_senas(self):
        f = tk.Frame(self.contenido, bg=CREMA)
        tk.Label(f, text="Señas de mano", font=("Segoe UI", 18, "bold"), fg=VERDE, bg=CREMA).pack(pady=(0, 4))
        tk.Label(f, text="Mantén la seña quieta 1 segundo. Pregunta: «¿cuál es la seña de ...?»",
                 font=("Segoe UI", 11), fg=TEXTO, bg=CREMA).pack()
        marco = tk.Frame(f, bg=CREMA)
        marco.pack(fill="both", expand=True, padx=10, pady=6)
        scroll = tk.Scrollbar(marco)
        scroll.pack(side="right", fill="y")
        self.txt_senas = tk.Text(marco, font=("Segoe UI", 13), wrap="word", height=14, bg="white", fg=TEXTO,
                                 relief="flat", yscrollcommand=scroll.set, state="disabled")
        self.txt_senas.tag_configure("t", font=("Segoe UI", 14, "bold"), foreground=VERDE)
        self.txt_senas.pack(side="left", fill="both", expand=True)
        scroll.config(command=self.txt_senas.yview)
        return f

    def _pantalla_materiales(self):
        ext, f = self._marco_scroll()
        tk.Label(f, text="Materiales guardados", font=("Segoe UI", 18, "bold"), fg=VERDE, bg=CREMA).pack(pady=(0, 4))
        busq = tk.Frame(f, bg=CREMA)
        busq.pack(fill="x", padx=12)
        tk.Label(busq, text="🔎 Buscar:", font=("Segoe UI", 12), fg=TEXTO, bg=CREMA).pack(side="left")
        self.var_busqueda = tk.StringVar()
        self.var_busqueda.trace_add("write", lambda *a: self.refrescar_materiales())
        tk.Entry(busq, textvariable=self.var_busqueda, font=("Segoe UI", 12)).pack(side="left", fill="x", expand=True, padx=6)
        marco = tk.Frame(f, bg=CREMA)
        marco.pack(fill="both", expand=True, padx=10, pady=4)
        scroll = tk.Scrollbar(marco)
        scroll.pack(side="right", fill="y")
        self.lista = tk.Listbox(marco, font=("Segoe UI", 12), yscrollcommand=scroll.set, height=8,
                                selectbackground=VERDE, exportselection=False)
        self.lista.pack(side="left", fill="both", expand=True)
        scroll.config(command=self.lista.yview)
        self.lista.bind("<Double-Button-1>", lambda e: self.escuchar_material())

        fila = tk.Frame(f, bg=CREMA)
        fila.pack(pady=6)
        botones = [
            ("🔊 Escuchar", VERDE, "white", self.escuchar_material),
            ("⭐ Favorito", AMARILLO, TEXTO, self.favorito_material),
            ("🗑 Borrar", NARANJA, "white", self.borrar_material),
            ("🖼 Imagen", NARANJA, "white", self.importar_imagen),
            ("📄 Documento", NARANJA, "white", self.importar_documento),
            ("📶 Recibir por Wi-Fi", VERDE, "white", self.alternar_wifi),
            ("📂 Materiales", AMARILLO, TEXTO, self.abrir_carpeta),
            ("💾 Guardar/copiar texto", AMARILLO, TEXTO, self.compartir_texto),
            ("👤 Perfil", VERDE, "white", self.nuevo_perfil),
        ]
        for i, (texto, color, fg, cmd) in enumerate(botones):
            self.boton(fila, texto, color, cmd, fg=fg, fuente=11).grid(row=i // 3, column=i % 3, padx=4, pady=3, ipady=5, ipadx=4, sticky="ew")
        return ext

    def mostrar(self, nombre):
        for p in self.pantallas.values():
            p.pack_forget()
        self.pantallas[nombre].pack(fill="both", expand=True)
        self.pantalla = nombre

    # ---------------------- Hilos -> interfaz (seguro) --------------------
    def ui(self, fn):
        self.cola_ui.put(fn)

    def _bombear_ui(self):
        try:
            while True:
                self.cola_ui.get_nowait()()
        except queue.Empty:
            pass
        self.root.after(50, self._bombear_ui)

    # ----------------------------- Cámara ---------------------------------
    def _abrir_indice(self, indice):
        """Abre la cámara 'indice' (número, o dirección http:// del teléfono) con la mayor resolución posible."""
        if isinstance(indice, str):
            return self._abrir_red(indice)
        _res = (640, 480) if self.modo_lento else RES_CAMARA  # modo equipo lento: menos píxeles que procesar
        # Varios intentos: algunas cámaras no dan imagen con MJPG o con 720p (pantalla negra). Se acepta la primera que
        # entregue imagen de verdad, no negra.
        intentos = []
        for mjpg, res in ((True, _res), (False, _res), (True, (640, 480)), (False, (640, 480))):
            if (mjpg, res) not in intentos:
                intentos.append((mjpg, res))
        for backend in (cv2.CAP_DSHOW, cv2.CAP_MSMF, cv2.CAP_ANY):
            for mjpg, res in intentos:
                cap = cv2.VideoCapture(indice, backend)
                if not cap.isOpened():
                    cap.release()
                    break  # este backend no puede con esta cámara: pasar al siguiente
                if mjpg:  # la cámara comprime el video y llega fluido (sin esto, en 720p muchas dan 5-10 cuadros/s)
                    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
                cap.set(cv2.CAP_PROP_FRAME_WIDTH, res[0])
                cap.set(cv2.CAP_PROP_FRAME_HEIGHT, res[1])
                cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                cap.set(cv2.CAP_PROP_AUTOFOCUS, 1)  # si la cámara lo soporta
                if self._esperar_imagen(cap):
                    t = time.time()
                    for _ in range(10):
                        cap.read()
                    fps = 10 / max(time.time() - t, 1e-3)
                    print(f"Cámara {indice} abierta (backend {backend}, {'MJPG' if mjpg else 'sin MJPG'}), "
                          f"{int(cap.get(3))}x{int(cap.get(4))}, ~{fps:.0f} cuadros/s")
                    return cap
                print(f"Cámara {indice}: sin imagen (backend {backend}, {'MJPG' if mjpg else 'sin MJPG'}, {res}); pruebo otra forma.")
                cap.release()
        return None

    @staticmethod
    def _esperar_imagen(cap, maximo=3.0):
        """True cuando la cámara ya entrega imagen no negra (muchas tardan ~1 s en ajustar la luz y al inicio salen negras)."""
        fin = time.time() + maximo
        while time.time() < fin:
            ok, frame = cap.read()
            if ok and frame is not None and frame.size and float(frame.mean()) > 6:
                return True
            time.sleep(0.04)
        return False

    @staticmethod
    def _ajustar_ip_webcam(url):
        """IP Webcam permite cambiar su resolución y calidad por HTTP. Menos pixeles = menos retraso por Wi-Fi.
        Es opcional y silencioso: si el teléfono no responde o no acepta el valor, no pasa nada."""
        if not AJUSTE_IP_WEBCAM:
            return
        try:
            p = urllib.parse.urlsplit(url)
            if not p.path.startswith("/video"):
                return
            base = f"{p.scheme}://{p.netloc}"
            for clave, valor in AJUSTE_IP_WEBCAM.items():
                urllib.request.urlopen(f"{base}/settings/{clave}?set={valor}", timeout=2).close()
        except Exception as e:
            print(f"No se pudo ajustar IP Webcam (no es grave): {e}")

    @classmethod
    def _abrir_red(cls, url):
        """Cámara por Wi-Fi (app del teléfono). Con tiempo límite para no congelarse si el teléfono no responde."""
        cls._ajustar_ip_webcam(url)
        p = urllib.parse.urlsplit(url)
        if p.path.startswith("/video") or p.path.lower().endswith((".mjpg", ".mjpeg")):
            try:  # lector propio: el más rápido para IP Webcam / DroidCam
                cam = CamaraMJPEG(url)
                ok, frame = cam.retrieve()
                if ok:
                    print(f"Cámara de red abierta (lector MJPEG directo): {url} ({frame.shape[1]}x{frame.shape[0]})")
                    return cam
                cam.release()
            except Exception as e:
                print(f"El lector MJPEG directo no sirvió ({e}); se usa OpenCV/FFmpeg.")
        try:
            cap = cv2.VideoCapture(url, cv2.CAP_FFMPEG, [cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 5000,
                                                         cv2.CAP_PROP_READ_TIMEOUT_MSEC, 5000])
        except Exception:
            cap = cv2.VideoCapture(url)
        if not cap.isOpened():
            cap.release()
            return None
        try:
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)  # menos retraso
        except Exception:
            pass
        ok, frame = cap.read()
        if ok and frame is not None:
            print(f"Cámara de red abierta: {url} ({frame.shape[1]}x{frame.shape[0]})")
            return cap
        cap.release()
        return None

    @staticmethod
    def _nombre_camara(ident, camaras):
        if isinstance(ident, str):
            return "del teléfono"
        return str(camaras.index(ident) + 1) if ident in camaras else str(ident + 1)

    def listar_camaras(self, maximo=6):
        """Índices de las cámaras conectadas ahora mismo (se vuelve a buscar cada vez: admite USB nuevas)."""
        encontradas, seguidos = [], 0
        for i in range(maximo):
            cap = cv2.VideoCapture(i, cv2.CAP_DSHOW)
            if cap.isOpened() and cap.read()[0]:
                encontradas.append(i)
                seguidos = 0
            else:
                seguidos += 1
            cap.release()
            if seguidos >= 2:  # los índices son consecutivos: dos huecos seguidos y no hay más (ahorra varios segundos)
                break
        tel = leer_config().get("telefono")
        if tel:
            encontradas.append(tel)  # la cámara del teléfono guardada también entra en la rotación
        return encontradas

    def abrir_camara_auto(self):
        """Arranque: la última cámara usada; si ya no está, prueba las demás."""
        orden = [self.indice_camara] + [i for i in range(4) if i != self.indice_camara]
        for i in orden:
            cap = self._abrir_indice(i)
            if cap is not None:
                self.indice_camara = i
                return cap
        return None

    @staticmethod
    def normalizar_url(texto):
        t = texto.strip()
        if not t:
            return ""
        if "://" not in t:
            t = "http://" + t
        resto = t.split("://", 1)[1]
        if "/" not in resto:  # solo escribió IP:puerto -> ruta típica de IP Webcam / DroidCam
            t += "/video"
        return t

    def conectar_telefono(self):
        if self.cambiando_camara:
            return
        actual = leer_config().get("telefono", "http://192.168.")
        texto = simpledialog.askstring(
            "Cámara del teléfono",
            "Escribe la dirección que muestra la app del teléfono\n(por ejemplo 192.168.1.20:8080):",
            initialvalue=actual, parent=self.root)
        url = self.normalizar_url(texto or "")
        if not url:
            return
        self.cambiando_camara = True
        self.voz.hablar("Conectando con el teléfono.")
        threading.Thread(target=self._conectar_telefono, args=(url,), daemon=True).start()

    def _poner_camara_red(self, url):
        """Abre la cámara del teléfono y la deja como cámara activa. True si funcionó (no anuncia nada)."""
        cap = self._abrir_red(url)
        if cap is None:
            return False
        viejo, self.cap = self.cap, None
        time.sleep(0.2)
        if viejo is not None:
            viejo.release()
        self.indice_camara = url
        guardar_config(telefono=url, camara=url)
        self.frames_recientes.clear()
        self.cap = cap
        return True

    def _conectar_telefono(self, url):
        try:
            if self._poner_camara_red(url):
                self.anunciar("Cámara del teléfono conectada.")
            else:
                self.anunciar("No se pudo conectar con el teléfono. Revisa que la app esté abierta y que el "
                              "teléfono y el computador estén en la misma red Wi-Fi.")
        finally:
            self.cambiando_camara = False

    # ---- cámara + micrófono del teléfono a la vez
    @staticmethod
    def _direcciones_telefono(texto):
        """'192.168.1.20:8080' -> (dirección del video, dirección del audio) de IP Webcam. (None, None) si no sirve."""
        t = (texto or "").strip()
        if not t:
            return None, None
        if "://" not in t:
            t = "http://" + t
        p = urllib.parse.urlsplit(t)
        if not p.netloc:
            return None, None
        base = f"{p.scheme}://{p.netloc}"
        return base + (p.path if p.path.startswith("/video") else "/video"), base + "/audio.wav"

    def conectar_telefono_completo(self, rapido=False):
        """Conecta la cámara Y el micrófono del teléfono al mismo tiempo, con una sola dirección.
        rapido=True (órdenes de voz): si ya hay una dirección guardada, no pregunta nada y se conecta directo."""
        if self.cambiando_camara or self.escuchando:
            return
        guardada = leer_config().get("telefono")
        if rapido and isinstance(guardada, str) and guardada:
            video, audio = self._direcciones_telefono(guardada)
        else:
            sugerida = (urllib.parse.urlsplit(guardada).netloc if isinstance(guardada, str) and guardada
                        else "192.168.")
            texto = simpledialog.askstring(
                "Teléfono: cámara y micrófono",
                "Escribe la dirección que muestra IP Webcam\n(por ejemplo 192.168.1.20:8080).\n"
                "Se conectan la cámara y el micrófono a la vez:", initialvalue=sugerida, parent=self.root)
            video, audio = self._direcciones_telefono(texto)
        if not video:
            return
        self.cambiando_camara = True
        self.escuchando = True  # mientras se conecta, la voz siempre activa no debe oír
        self.voz.hablar("Conectando la cámara y el micrófono del teléfono.")
        threading.Thread(target=self._conectar_telefono_completo, args=(video, audio), daemon=True).start()

    def _conectar_telefono_completo(self, video, audio):
        res = {"cam": False, "mic": False}

        def cam():
            try:
                res["cam"] = self._poner_camara_red(video)
            except Exception as e:
                print(f"Cámara del teléfono: {e}")

        def mic():
            try:
                self.mic.conectar_red(audio)
                self.mic.dispositivo = audio  # la voz siempre activa detecta el cambio y reabre con el teléfono
                guardar_config(microfono=audio, telefono_audio=audio)
                res["mic"] = True
            except Exception as e:
                print(f"Micrófono del teléfono: {e}")

        try:
            hilos = [threading.Thread(target=cam, daemon=True), threading.Thread(target=mic, daemon=True)]
            for h in hilos:  # en paralelo: tarda lo de la más lenta, no la suma de las dos
                h.start()
            for h in hilos:
                h.join()
            if res["cam"] and res["mic"]:
                self.estado("📱 Teléfono: cámara y micrófono conectados")
                self.anunciar("Cámara y micrófono del teléfono conectados.")
            elif res["cam"]:
                self.anunciar("Cámara del teléfono conectada, pero no el micrófono. Revisa que el audio esté "
                              "activado en IP Webcam.")
            elif res["mic"]:
                self.anunciar("Micrófono del teléfono conectado, pero no la cámara. Revisa que el video esté "
                              "activado en IP Webcam.")
            else:
                self.anunciar("No se pudo conectar con el teléfono. Revisa que IP Webcam esté abierta con el servidor "
                              "iniciado y que el teléfono y el computador estén en la misma red Wi-Fi.")
        finally:
            self.cambiando_camara = False
            self.escuchando = False

    def _camara_perdida(self):
        """Lo llama el lector (desde su hilo) cuando el teléfono lleva ~3 s sin mandar cuadros."""
        if self.cambiando_camara or not isinstance(self.indice_camara, str):
            return
        self.cambiando_camara = True
        threading.Thread(target=self._reconectar_telefono, args=(self.indice_camara,), daemon=True).start()

    def _reconectar_telefono(self, url):
        try:
            self.anunciar("Se perdió la conexión con la cámara del teléfono. Reconectando.")
            cap = self._abrir_red(url)
            nuevo_indice = url
            if cap is None:  # no volvió: usar una cámara de la laptop para no quedarse sin imagen
                for i in range(4):
                    cap = self._abrir_indice(i)
                    if cap is not None:
                        nuevo_indice = i  # solo esta sesión: lo guardado sigue siendo el teléfono
                        break
                self.anunciar("No se pudo reconectar con el teléfono. Uso la cámara de la laptop."
                              if cap is not None else "No se pudo reconectar con el teléfono ni abrir otra cámara.")
            viejo, self.cap = self.cap, None
            time.sleep(0.2)
            if viejo is not None:
                viejo.release()
            if cap is not None:
                self.indice_camara = nuevo_indice
                self.frames_recientes.clear()
                self.cap = cap
        finally:
            self.cambiando_camara = False

    def conectar_mic_telefono(self):
        if self.escuchando or self.cambiando_camara:
            return
        cfg = leer_config()
        sugerida = cfg.get("telefono_audio")
        if not sugerida:
            cam = cfg.get("telefono", "")
            if isinstance(cam, str) and "://" in cam:
                sugerida = cam.split("://", 1)[0] + "://" + cam.split("://", 1)[1].split("/", 1)[0] + "/audio.wav"
            else:
                sugerida = "http://192.168."
        texto = simpledialog.askstring(
            "Micrófono del teléfono",
            "Dirección del audio del teléfono.\nCon IP Webcam es la misma dirección de la cámara, terminada en /audio.wav\n"
            "(por ejemplo 192.168.1.20:8080/audio.wav):", initialvalue=sugerida, parent=self.root)
        t = (texto or "").strip()
        if not t:
            return
        if "://" not in t:
            t = "http://" + t
        if "/" not in t.split("://", 1)[1]:
            t += "/audio.wav"
        self.escuchando = True
        self.anunciar("Probando el micrófono del teléfono.")
        threading.Thread(target=self._conectar_mic_telefono, args=(t,), daemon=True).start()

    def _conectar_mic_telefono(self, url):
        try:
            self.mic.conectar_red(url)  # comprueba que llegue audio de verdad y deja la conexión abierta para usarla
            self.mic.dispositivo = url  # la voz siempre activa detecta el cambio y reabre con el teléfono
            guardar_config(microfono=url, telefono_audio=url)
            self.estado("🎤 Micrófono del teléfono conectado")
            self.anunciar("Micrófono del teléfono conectado. Ahora las órdenes por voz se oyen por el teléfono.")
        except Exception as e:
            print(f"Micrófono del teléfono: {e}")
            self.anunciar("No se pudo conectar con el micrófono del teléfono. Revisa que IP Webcam esté abierta, "
                          "que el audio esté activado en sus ajustes y que estén en la misma red Wi-Fi.")
        finally:
            self.escuchando = False

    def cambiar_microfono(self):
        if sd is None:
            self.anunciar("Falta instalar sounddevice para usar el micrófono de la laptop.")
            return
        nombre = self.mic.siguiente_microfono()
        print(f"Micrófono: {nombre}")
        self.anunciar(f"Micrófono: {nombre}")

    def usar_mic_laptop(self):
        """Pasa al micrófono de la laptop sin tener que dar vueltas por la lista (útil si estabas con el teléfono)."""
        if sd is None:
            self.anunciar("Falta instalar sounddevice para usar el micrófono de la laptop.")
            return
        nombre = self.mic.usar_laptop()
        print(f"Micrófono: {nombre}")
        self.estado(f"🎤 Micrófono de la laptop: {nombre}")
        self.anunciar(f"Micrófono de la laptop: {nombre}")

    def escuchar_orden(self):
        if self.escuchando:
            return
        if self.voz_continua:
            self.anunciar("La voz ya está siempre activa. Solo di la orden.")
            return
        if not self.mic.disponible():
            print("Para usar el micrófono sin internet instala: pip install vosk sounddevice")
            print("(con internet también sirve: pip install SpeechRecognition sounddevice)")
            self.anunciar("El micrófono necesita instalar un paquete. Mira la consola.")
            return
        self.escuchando = True
        self.voz.detener()
        self.lbl_resultado.config(text="🎤 Escuchando...")
        threading.Thread(target=self._escuchar_orden, daemon=True).start()

    def _escuchar_orden(self):
        try:
            time.sleep(0.25)  # que se apague lo que sonaba, para no grabar la propia voz
            if winsound is not None:
                try:
                    winsound.Beep(880, 150)  # pitido: "ya puedes hablar"
                except Exception:
                    pass
            self.estado(f"🎤 Escuchando por: {self.mic.nombre_dispositivo()}")
            texto = self.mic.escuchar(al_oir=lambda t: self.estado(f"🎤 Oigo: {t}"))
            print(f"DEBUG - micrófono: {texto!r}")
            orden = interpretar_orden(texto) if texto else None
            self.estado(f"🎤 Oí: {texto or '(nada)'}  →  {orden or 'sin orden'}")
            if orden:
                self.ui(lambda: self.ejecutar_orden(orden))
            elif texto:
                self.anunciar(f"No entendí la orden {texto}. Prueba con: capturar, atrás, inicio, repetir o silencio.")
            else:
                self.anunciar("No te escuché. Presiona V y habla después del pitido.")
        except Exception as e:
            import traceback
            traceback.print_exc()
            print(f"Error del micrófono: {e}")
            self.estado(f"🎤 Error: {e}"[:100])
            if isinstance(self.mic.dispositivo, str):
                self.anunciar("No se pudo usar el micrófono del teléfono. Revisa que la app esté abierta, "
                              "que el audio esté activado y que estén en la misma red Wi-Fi.")
            else:
                self.anunciar("No pude usar el micrófono. Mira el mensaje de error en la consola.")
        finally:
            self.escuchando = False

    def ejecutar_orden(self, orden):
        print(f"Orden por voz: {orden}")
        registrar_voz(f"EJECUTA orden={orden} (pantalla {self.pantalla})")
        if orden.startswith("sena:"):
            self.decir_sena(orden[5:])
        elif orden.startswith("m_"):
            self.abrir_modo(orden[2:])
        else:
            {"camara": self.cambiar_camara, "telefono": lambda: self.conectar_telefono_completo(rapido=True),
             "audio": self.cambiar_audio,
             "gestos_on": lambda: self.alternar_gestos(True), "gestos_off": lambda: self.alternar_gestos(False),
             "mic_telefono": self.conectar_mic_telefono,
             "mic_laptop": self.usar_mic_laptop,
             "mic_cambiar": self.cambiar_microfono,
             "voz_on": lambda: self.alternar_voz_continua(True), "voz_off": lambda: self.alternar_voz_continua(False), "ajustes": self.abrir_ajustes, "importar": self.importar_imagen, "importar_doc": self.importar_documento, "wifi": self.alternar_wifi,
             "materiales": self.abrir_materiales, "capturar": self.capturar, "repetir": self.repetir,
             "silencio": self.silencio, "inicio": self.ir_inicio, "atras": self.atras,
             "vel_menos": lambda: self.cambiar_voz(vel=-1), "vel_mas": lambda: self.cambiar_voz(vel=1),
             "vol_mas": lambda: self.cambiar_voz(vol=15), "vol_menos": lambda: self.cambiar_voz(vol=-15),
             "pausa": self.pausar_lectura, "continuar": self.continuar_lectura,
             "siguiente": lambda: self.mover_lectura(1), "anterior": lambda: self.mover_lectura(-1),
             "encuadre": self.alternar_encuadre, "tutorial": self.tutorial, "color": self.decir_color,
             "significado": self.decir_significado, "actualizar": self.pedir_actualizacion, "dinero_total": self.decir_total_dinero, "dinero_reiniciar": self.reiniciar_dinero, "traducir": lambda: self.traducir_ultimo("es", "en"),
             "traducir_es": lambda: self.traducir_ultimo("en", "es"), "perfil": self.cambiar_perfil,
             "senas_lista": self.abrir_senas}[orden]()

    def alternar_gestos(self, activar=None, silencioso=False):
        """activar=None: cambia al contrario. True/False: lo deja exactamente así (lo usan las órdenes por voz)."""
        if activar is None:
            activar = not self.gestos_activos
        if not activar:
            self.gestos_activos = False
            guardar_config(gestos=False)
            self._texto_boton_gestos("apagados")
            self.anunciar("Gestos apagados.")
            return
        if self.gestos_activos:
            self.anunciar("Los gestos ya están activados.")
            return
        if not Gestos.disponible():
            print("Para usar gestos instala: pip install mediapipe==0.10.14")
            print(f"Detalle del error de mediapipe: {MP_ERROR}")
            self.anunciar("Los gestos necesitan instalar mediapipe. Mira la consola.")
            return
        if self.cap is None:
            self.anunciar("Los gestos necesitan la cámara.")
            return
        try:
            self.gestos.iniciar()
        except Exception as e:
            print(f"No se pudo iniciar los gestos: {e}")
            self.anunciar("No se pudieron iniciar los gestos.")
            return
        self.gestos_activos = True
        guardar_config(gestos=True)
        self._texto_boton_gestos("activados")
        if silencioso:
            self.anunciar("Gestos activados.")
            return
        self.anunciar("Gestos activados. Mantén la seña quieta un poco más de un segundo. Uno a cuatro dedos eligen las "
                      "funciones uno a cuatro, la mano abierta cuenta objetos. Materiales: mano abierta y un dedo en la otra. "
                      "Ajustes: mano abierta y dos dedos en la otra. Puño repite, dos puños capturan. "
                      "Para oír todas las señas di: señas, o presiona J.")

    # ---- voz siempre activa (escucha continua, solo con reconocimiento sin internet)
    def alternar_voz_continua(self, activar=None, silencioso=False):
        if activar is None:
            activar = not self.voz_continua
        if not activar:
            self.voz_continua = False
            guardar_config(voz_continua=False)
            self._texto_boton_voz("apagada")
            self.anunciar("Voz siempre activa apagada.")
            return
        if self.voz_continua:
            self.anunciar("La voz ya está siempre activa.")
            return
        if self.mic.modelo is None:
            print("La voz siempre activa necesita el reconocimiento sin internet: pip install vosk sounddevice")
            self.anunciar("La voz siempre activa necesita el reconocimiento sin internet. Instala vosk y "
                          "espera a que termine de descargar el modelo.")
            return
        self.voz_continua = True
        guardar_config(voz_continua=True)
        self._texto_boton_voz("activa")
        threading.Thread(target=self._bucle_voz_continua, daemon=True).start()
        if silencioso:
            self.anunciar("Voz siempre activa.")
        else:
            self.anunciar("Voz siempre activa. Di una orden, por ejemplo capturar, atrás o inicio. "
                          "Para apagarla di: desactivar voz. Se recomienda usar audífonos.")

    def _bucle_voz_continua(self):
        fallos = 0
        while self.voz_continua:
            try:
                self.estado(f"🎤 Voz activa por {self.mic.nombre_dispositivo()}: te escucho (di una orden)")
                self.mic.escuchar_continuo(
                    debe_parar=lambda: not self.voz_continua,
                    ocupado=lambda: self.voz.ocupada() or self.escuchando or time.time() - self.voz.ultimo_fin < 0.6,
                    al_texto=self._orden_oida,
                    al_oir=lambda t: self.estado(f"🎤 Oigo: {t}"))
                fallos = 0
            except Exception as e:
                import traceback
                traceback.print_exc()
                registrar_voz(f"ERROR voz continua: {e!r}")
                fallos += 1
                self.estado(f"🎤 Error del micrófono ({fallos}/3): {e}"[:110])
                if fallos >= 3:
                    self.voz_continua = False
                    guardar_config(voz_continua=False)
                    self.ui(lambda: self._texto_boton_voz("apagada"))
                    self.anunciar("La voz siempre activa se detuvo por un error del micrófono. "
                                  "Mira el mensaje de error en la parte de abajo.")
                    break
                time.sleep(1.5)  # reintentar: a veces Windows tarda en liberar el micrófono

    def _orden_oida(self, texto):
        orden = interpretar_orden(texto)
        print(f"DEBUG - voz continua: {texto!r} -> {orden}")
        registrar_voz(f"continua mic={self.mic.nombre_dispositivo()!r} oyó={texto!r} orden={orden}")
        self.estado(f"🎤 Oí: {texto}  →  {orden or 'sin orden'}")
        if orden:
            self.ui(lambda o=orden: self.ejecutar_orden(o))

    def _texto_boton_voz(self, estado):
        b = getattr(self, "btn_voz", None)
        if b is not None:
            b.config(text=f"🎤  Voz siempre activa: {estado}  (H)")

    def _texto_boton_gestos(self, estado):
        b = getattr(self, "btn_gestos", None)
        if b is not None:
            b.config(text=f"🖐  Gestos de mano: {estado}  (G)")

    def decir_sena(self, orden):
        """Dice cuál es la seña de algo (por voz: "¿cuál es la seña de materiales?"). Queda guardado: el puño lo repite."""
        self.anunciar(frase_sena(orden))

    def ejecutar_gesto(self, g):
        """Cada seña tiene su propia función, igual en todas las pantallas (ver SENAS)."""
        print(f"Gesto: {g} (pantalla {self.pantalla})")
        datos = SENAS.get(g)
        if datos is None:
            return
        orden, nombre, como = datos
        if orden == "senas":  # seña de ayuda: entra y sale del modo práctica
            self.modo_practica = not self.modo_practica
            if self.modo_practica:
                self.anunciar("Modo práctica de señas. Haz una seña y te digo qué hace, sin ejecutarla. "
                              "Para salir, repite esta misma seña: tres dedos en cada mano. "
                              "Di: señas, para oír la lista completa.")
            else:
                self.anunciar("Modo práctica terminado. Las señas vuelven a ejecutar su función.")
            return
        if self.modo_practica:
            self.anunciar(f"Esa seña es {como}. Sirve para {nombre}.")
            return
        if orden == "voz":
            self.alternar_voz_continua()
        elif orden == "capturar":
            if self.pantalla != "modo":
                self.anunciar("Primero elige una función del menú.")
            else:
                self.voz.hablar("Quita las manos. Capturando.")
                self.root.after(2800, self.capturar)  # tiempo para retirar las manos de la imagen
        elif orden.startswith("m_"):
            self.abrir_modo(orden[2:])
        else:
            {"materiales": self.abrir_materiales, "ajustes": self.abrir_ajustes, "repetir": self.repetir,
             "silencio": self.voz.detener, "inicio": self.ir_inicio, "atras": self.atras}[orden]()

    def abrir_senas(self):
        """Pantalla con todas las señas; también las lee en voz alta (la voz se puede cortar con: silencio, o la tecla S)."""
        self._salir_de_pantalla()
        self.mostrar("senas")
        items = lista_senas()
        self.txt_senas.config(state="normal")
        self.txt_senas.delete("1.0", "end")
        for nombre, como in items:
            self.txt_senas.insert("end", f"{nombre.split(',')[0].capitalize()}\n", "t")
            self.txt_senas.insert("end", f"     {como}\n\n")
        self.txt_senas.config(state="disabled")
        habla = "Estas son las señas. " + " ".join(f"{n}: {c}." for n, c in items)
        self.ultimo_audio = habla
        self.voz.hablar(habla)

    def cambiar_audio(self):
        self.voz.siguiente_salida(lambda t: self.anunciar(t))

    def cambiar_camara(self):
        if self.cambiando_camara:
            return
        self.cambiando_camara = True
        self.voz.hablar("Buscando cámaras.")
        threading.Thread(target=self._cambiar_camara, daemon=True).start()

    def _cambiar_camara(self):
        try:
            viejo, self.cap = self.cap, None  # el video se pausa mientras se cambia
            time.sleep(0.2)
            if viejo is not None:
                viejo.release()
            camaras = self.listar_camaras()
            print(f"Cámaras encontradas: {camaras}")
            if not camaras:
                self.cap = self._abrir_indice(self.indice_camara)
                self.anunciar("No se encontró ninguna cámara. Revisa la conexión.")
                return
            if self.indice_camara in camaras:
                siguiente = camaras[(camaras.index(self.indice_camara) + 1) % len(camaras)]
            else:
                siguiente = camaras[0]
            cap = self._abrir_indice(siguiente)
            if cap is None:  # no abrió: volver a la anterior
                cap = self._abrir_indice(self.indice_camara)
                self.cap = cap
                self.anunciar(f"No se pudo abrir la cámara {self._nombre_camara(siguiente, camaras)}. "
                              "Si es la del teléfono, revisa que la app esté abierta y en la misma red Wi-Fi.")
                return
            self.indice_camara = siguiente
            guardar_config(camara=siguiente)
            self.frames_recientes.clear()
            self.cap = cap
            ancho, alto = int(cap.get(3)), int(cap.get(4))
            if len(camaras) == 1:
                self.anunciar(f"Solo hay una cámara conectada, {ancho} por {alto}.")
            else:
                if isinstance(siguiente, str):
                    self.anunciar(f"Cámara del teléfono, {ancho} por {alto}.")
                else:
                    pos = camaras.index(siguiente) + 1
                    self.anunciar(f"Cámara {pos} de {len(camaras)}, {ancho} por {alto}.")
        finally:
            self.cambiando_camara = False

    def _vigilar_camara(self, lector, n):
        """Si la cámara USB lleva varios segundos sin entregar cuadros mientras se necesita, se vuelve a abrir sola."""
        ahora = time.time()
        if not (self.pantalla == "modo" or self.gestos_activos):
            self._t_cuadro = ahora  # en el menú no se leen cuadros: no es una falla
            return
        if n != getattr(self, "_n_vigilado", -1) or self.cambiando_camara:
            self._n_vigilado, self._t_cuadro = n, ahora
            return
        if (self.pantalla == "modo" or self.gestos_activos) and isinstance(self.indice_camara, int) \
                and ahora - getattr(self, "_t_cuadro", ahora) > 6 and ahora - getattr(self, "_t_reabierta", 0) > 20:
            self._t_reabierta = self._t_cuadro = ahora
            self.cambiando_camara = True
            print("Cámara sin imágenes desde hace 6 s: se vuelve a abrir.")
            self.voz.hablar("La cámara dejó de responder. La estoy reiniciando.")
            threading.Thread(target=self._reabrir_camara, daemon=True).start()

    def _reabrir_camara(self):
        try:
            viejo, self.cap = self.cap, None
            time.sleep(0.3)
            if viejo is not None:
                viejo.release()
            cap = self._abrir_indice(self.indice_camara) or self.abrir_camara_auto()
            self.frames_recientes.clear()
            self.cap = cap
            if cap is None:
                self.anunciar("No pude reabrir la cámara. Revisa que no la use otro programa, o usa Cambiar cámara.")
        finally:
            self.cambiando_camara = False

    def actualizar_video(self):
        lector = self.lector
        if lector is not None:
            frame, n = lector.ultimo()
            self._vigilar_camara(lector, n)
            if frame is not None and n != self._ultimo_n:
                self._ultimo_n = n
                self.ultimo_frame = frame
                self.frames_recientes.append(frame)
                if self.ayuda_encuadre and self.pantalla == "modo" and self.modo_actual in ("texto", "letras", "numeros") \
                        and time.time() - self._t_encuadre > 3:
                    self._t_encuadre = time.time()
                    self._revisar_encuadre(frame)
                if self.gestos_activos:
                    self._frame_gestos = frame  # el hilo de gestos lo toma cuando termine el anterior
                    self._ev_gestos.set()
                if self.pantalla == "modo" and not (self.modo_lento and n % 2):  # en modo lento se dibuja un cuadro de cada dos
                    vista = cv2.cvtColor(cv2.resize(frame, (self.ANCHO_VIDEO, self.ALTO_VIDEO),
                                                    interpolation=cv2.INTER_LINEAR), cv2.COLOR_BGR2RGB)
                    if self.gestos_activos:  # dibujar las manos que ve la app: verde = clara, naranja = dudosa (se ignora)
                        for puntos, clara in list(self.gestos.todas):
                            color = (0, 255, 0) if clara else (255, 165, 0)
                            for (px, py) in puntos:
                                cv2.circle(vista, (int(px * self.ANCHO_VIDEO), int(py * self.ALTO_VIDEO)), 4, color, -1)
                    if self.modo_actual == "figuras":  # zona guía: solo se analiza lo que quede adentro
                        cv2.rectangle(vista, (int(self.ANCHO_VIDEO * .08), int(self.ALTO_VIDEO * .08)),
                                      (int(self.ANCHO_VIDEO * .92), int(self.ALTO_VIDEO * .92)), (0, 200, 0), 2)
                    imgtk = ImageTk.PhotoImage(image=Image.fromarray(vista))
                    self.video_label.imgtk = imgtk
                    self.video_label.configure(image=imgtk)
            if self.gestos_activos:
                self._mostrar_estado_gestos()
            ahora = time.time()
            if ahora - self._t_fps > 5 and lector.fps:
                self._t_fps = ahora
                print(f"[rendimiento] cámara {lector.fps:.0f} cuadros/s"
                      + (f" | gestos {self._fps_gestos:.0f}/s" if self.gestos_activos else ""))
                # Si la cámara va muy lenta dos veces seguidas, se sugiere el modo equipo lento (una sola vez)
                if lector.fps < 12 and self.pantalla == "modo" and not self.modo_lento and not self._avisado_lento:
                    self._lentos += 1
                    if self._lentos >= 2:
                        self._avisado_lento = True
                        self.voz.hablar("Este computador va lento. Puedes activar el modo equipo lento en Ajustes.")
                else:
                    self._lentos = 0
        self.root.after(15, self.actualizar_video)

    # ---- gestos en su propio hilo (así la ventana no se pega)
    def _bucle_gestos(self):
        t0, cuenta = time.time(), 0
        ultimo = 0.0
        while True:
            self._ev_gestos.wait()
            self._ev_gestos.clear()
            if not self.gestos_activos:
                continue
            # Ahorro de procesador: con una mano a la vista se analiza ~15 veces por segundo (de sobra para una seña
            # que se mantiene 1,2 s); sin manos, ~6 veces por segundo, y se acelera apenas aparece una.
            espera = (0.12 if (self.gestos.todas or self._visto) else 0.3) if self.modo_lento else (0.066 if (self.gestos.todas or self._visto) else 0.16)
            falta = ultimo + espera - time.time()
            if falta > 0:
                time.sleep(falta)
            ultimo = time.time()
            try:
                self._visto = self.gestos.leer(self._frame_gestos)
                g = self.gestos.actualizar(self._visto, time.time())
                self._error_gestos = ""
                cuenta += 1
                if time.time() - t0 >= 2:
                    self._fps_gestos, t0, cuenta = cuenta / (time.time() - t0), time.time(), 0
                if g:
                    self.ui(lambda g=g: self.ejecutar_gesto(g))
            except Exception as e:
                print(f"Error de gestos: {e}")
                self._error_gestos = str(e)
                time.sleep(0.5)

    def _mostrar_estado_gestos(self):
        if self._error_gestos:
            texto = f"🖐 Error de gestos: {self._error_gestos}"[:90]
        elif self.gestos.dominante:
            av = self.gestos.progreso
            texto = (f"🖐 Veo: {Gestos.nombre(self.gestos.dominante)}  "
                     + "█" * int(av * 8) + "░" * (8 - int(av * 8)) + "  (mantenlo)")
        elif self._visto:
            texto = f"🖐 Veo: {Gestos.nombre(self._visto)}  (mantenlo firme)"
        elif not self.gestos.todas:
            texto = "🖐 Gestos activos: no veo ninguna mano (acércala a la cámara, con buena luz)"
        else:
            n = len(self.gestos.todas)
            texto = (f"🖐 Veo {n} mano{'s' if n != 1 else ''}, sin gesto: "
                     f"{self.gestos.nota or 'ese gesto no es uno de los de la lista'}")
        if texto != self._texto_gestos:  # no repintar si no cambió
            self._texto_gestos = texto
            self.lbl_estado.config(text=texto)

    # --------------------------- Navegación -------------------------------
    def estado(self, texto):
        """Línea de estado inferior (se puede llamar desde cualquier hilo)."""
        self.ui(lambda: self.lbl_estado.config(text=texto))

    def _salir_de_pantalla(self):
        """Al cambiar de pantalla: corta lo que se está leyendo y descarta resultados pendientes."""
        self._gen += 1
        self.lectura.detener()

    def abrir_modo(self, modo):
        self._salir_de_pantalla()
        self.modo_actual = modo
        self.lbl_titulo_modo.config(text=MODOS[modo])
        self.lbl_resultado.config(text="Apunta la cámara y presiona Capturar.")
        self.mostrar("modo")
        if modo == "objetos":
            self._asegurar_detector()  # que se vaya cargando mientras apuntas la cámara
        self.voz.hablar(f"{MODOS[modo]}. Apunta la cámara y presiona capturar.")

    def abrir_ajustes(self):
        self._salir_de_pantalla()
        self.mostrar("ajustes")
        self.voz.hablar("Ajustes. Cámara, teléfono, audio, gestos y micrófono.")

    def abrir_materiales(self):
        self._salir_de_pantalla()
        self.refrescar_materiales()
        self.mostrar("materiales")
        self.voz.hablar("Materiales guardados.")

    def ir_inicio(self):
        self._salir_de_pantalla()
        self.mostrar("menu")
        self.voz.hablar("Menú principal.")

    def atras(self):
        if self.pantalla == "menu":
            self.voz.hablar("Ya estás en el menú principal.")
        else:
            self.ir_inicio()

    def _decir(self, texto):
        """Textos largos se leen por párrafos (con pausa, adelantar y retroceder); los cortos, de una vez."""
        if len(texto) > 380:
            self.lectura.iniciar(texto)
        else:
            self.lectura.detener()
            self.voz.hablar(texto)

    def silencio(self):
        self.lectura.detener()

    def pausar_lectura(self):
        if self.lectura.pausada:
            return self.continuar_lectura()
        if self.lectura.pausar():
            self.estado("⏸ Pausa. Di «continuar» o pulsa P.")
        else:
            self.voz.hablar("No hay nada que pausar.")

    def continuar_lectura(self):
        if self.lectura.continuar():
            self.estado("▶ " + self.lectura.estado())
        else:
            self.voz.hablar("No hay una lectura para continuar.")

    def mover_lectura(self, delta):
        if self.lectura.mover(delta):
            self.estado("📖 " + self.lectura.estado())
        else:
            self.voz.hablar("No hay un texto largo leyéndose.")

    def cambiar_voz(self, vel=0, vol=0):
        v, w = self.voz.ajustar(vel, vol)
        if vel:
            self.voz.hablar(f"Voz más {'rápida' if vel > 0 else 'lenta'}. Velocidad {v + 7} de 13.")
        else:
            self.voz.hablar(f"Volumen {w} por ciento.")

    def repetir(self):
        if self.ultimo_audio:
            self._decir(self.ultimo_audio)
        else:
            self.voz.hablar("Todavía no hay nada para repetir.")

    def tecla(self, event):
        k = (event.char or "").lower()
        if k == "c":
            self.capturar()
        elif k == "r":
            self.repetir()
        elif k == "m":
            self.ir_inicio()
        elif k == "k":
            self.cambiar_camara()
        elif k == "a":
            self.cambiar_audio()
        elif k == "g":
            self.alternar_gestos()
        elif k == "v":
            self.escuchar_orden()
        elif k == "h":
            self.alternar_voz_continua()
        elif k == "i":
            self.cambiar_microfono()
        elif k == "l":
            self.usar_mic_laptop()
        elif k == "s":
            self.silencio()
        elif k == "p":
            self.pausar_lectura()
        elif k == "n":
            self.mover_lectura(1)
        elif k == "b":
            self.mover_lectura(-1)
        elif k == "e":
            self.alternar_encuadre()
        elif k in ("j", "?"):
            self.abrir_senas()
        elif self.pantalla == "menu" and k and k in "12345678":
            if k == "8":
                self.abrir_modo("dinero")
            elif k == "6":
                self.abrir_materiales()
            elif k == "7":
                self.abrir_ajustes()
            else:
                self.abrir_modo(ORDEN_MODOS[int(k) - 1])

    # ----------------------------- Captura --------------------------------
    def capturar(self):
        if self.pantalla != "modo":
            self.voz.hablar("Primero elige una función del menú.")
            return
        if self.cap is None or self.ultimo_frame is None:
            self.voz.hablar("La cámara no está disponible.")
            return
        # Elegir el fotograma más nítido (varianza del Laplaciano) entre los últimos
        candidatos = list(self.frames_recientes) or [self.ultimo_frame]
        def _nitidez(f):  # a 640 px de ancho basta para comparar y es mucho más rápido que en 1080p
            g = cv2.cvtColor(f, cv2.COLOR_BGR2GRAY)
            g = cv2.resize(g, (640, max(1, int(g.shape[0] * 640 / g.shape[1]))), interpolation=cv2.INTER_AREA)
            return cv2.Laplacian(g, cv2.CV_64F).var()
        nitidez = [_nitidez(f) for f in candidatos]
        frame = candidatos[int(np.argmax(nitidez))].copy()
        print(f"Nitidez de la captura: {max(nitidez):.0f} (menos de ~100 suele ser imagen borrosa)")
        cv2.imwrite(os.path.join(CARPETA_DEBUG, "captura.png"), frame)
        if self.modo_actual in ("texto", "letras", "numeros", "dinero"):
            aviso, ok = calidad_imagen(frame)
            if not ok:
                self.voz.hablar(aviso + " Aun así la voy a analizar.")
        self.lanzar_analisis(frame, self.modo_actual, desde_camara=True)

    def lanzar_analisis(self, frame, modo, desde_camara=False):
        if self.procesando:
            return
        self.lectura.detener()
        self.procesando = True
        if not self.ocr.listo.is_set():
            self.voz.hablar("Cargando el lector. Un momento.")
        else:
            self.voz.hablar("Analizando.")
        self.lbl_resultado.config(text="Analizando...")
        self._gen_analisis = self._gen
        threading.Thread(target=self._analizar, args=(frame, modo, desde_camara), daemon=True).start()

    def _terminar(self):
        self.procesando = False

    def anunciar(self, texto, guardar_modo=None):
        if self._gen_analisis is not None and self._gen_analisis != self._gen:
            return  # la persona ya salió de esa opción: no leer el resultado
        self.ultimo_audio = texto
        self._decir(texto)
        self.ui(lambda: self.lbl_resultado.config(text=texto))
        if guardar_modo:
            self.guardar_material(guardar_modo, texto)

    def _analizar(self, frame, modo, desde_camara=False):
        try:
            if modo == "texto":
                self._modo_texto(frame)
            elif modo == "letras":
                self._modo_letras(frame)
            elif modo == "numeros":
                self._modo_numeros(frame)
            elif modo == "figuras":
                self._modo_figuras(frame, desde_camara)
            elif modo == "objetos":
                self._modo_objetos(frame)
            elif modo == "dinero":
                self._modo_dinero(frame)
        except Exception as e:
            print(f"Error al analizar: {e}")
            self.anunciar("Ocurrió un error al analizar la imagen.")
        finally:
            self._gen_analisis = None
            self.ui(self._terminar)

    @staticmethod
    def _limpiar(texto):
        return " ".join(texto.replace('—', ' ').replace('_', ' ').replace('|', ' ').split())

    def _leer(self, frame, psms, suficiente=30):
        texto, motor = self.ocr.texto(frame, psms, suficiente)
        print(f"DEBUG - motor {motor}: {texto!r}")
        return self._limpiar(texto)

    def _modo_texto(self, frame):
        texto = self._leer(frame, psms=(6, 3))
        print(f"DEBUG - Texto final: '{texto}'")
        if len(texto) > 1:
            self.ultimo_texto = texto
            cuentas = operaciones_habladas(texto)
            self.anunciar(f"El texto dice: {texto}" + (f" Cuentas que encontré: {cuentas}" if cuentas else ""), guardar_modo="texto")
        else:
            self.anunciar("No se detectó texto. Acerca el papel, enfoca bien y usa buena luz.")

    def _modo_letras(self, frame):
        texto = self._leer(frame, psms=(6, 10), suficiente=8)
        palabras = texto.split()
        if not palabras:
            self.anunciar("No se detectaron letras. Usa letras grandes y oscuras sobre fondo claro.")
            return
        if len(texto.replace(" ", "")) == 1:
            self.anunciar(f"Letra {texto}", guardar_modo="letras")
            return
        self.ultima_palabra = re.sub(r"[^\wáéíóúüñÁÉÍÓÚÜÑ]", "", palabras[0])
        self.ultimo_texto = texto
        n = len(palabras)
        partes = [f"Se detectó {n} palabra." if n == 1 else f"Se detectaron {n} palabras."]
        for p in palabras[:5]:
            partes.append(f"{p}. Se escribe: {', '.join(p)}.")
        self.anunciar(" ".join(partes), guardar_modo="letras")

    def _modo_numeros(self, frame):
        texto = self._limpiar(self.ocr.numeros(frame))
        print(f"DEBUG - números: {texto!r}")
        if texto:
            self.anunciar(f"Cifra detectada: {texto}", guardar_modo="numeros")
        else:
            self.anunciar("No se detectó ningún número.")

    def _leer_moneda(self, recorte):
        """Número que lleva una moneda (recorte del círculo), con el contraste mejorado."""
        g = cv2.cvtColor(recorte, cv2.COLOR_BGR2GRAY)
        g = cv2.resize(g, (240, 240), interpolation=cv2.INTER_CUBIC)
        g = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(4, 4)).apply(g)
        return self.ocr.numeros(cv2.cvtColor(g, cv2.COLOR_GRAY2BGR))

    def _sumar_dinero(self, valor):
        self.total_dinero = getattr(self, "total_dinero", 0) + valor
        self.n_dinero = getattr(self, "n_dinero", 0) + 1
        if self.n_dinero > 1:
            return f" Cuenta acumulada: {pesos_hablados(self.total_dinero)}. Para empezar de nuevo di: reiniciar cuenta."
        return " Si sigues con más, la app va sumando. Para ver el total di: total."

    def decir_total_dinero(self):
        t = getattr(self, "total_dinero", 0)
        self.anunciar(f"Llevas {pesos_hablados(t)}." if t else "Todavía no hay nada sumado.")

    def reiniciar_dinero(self):
        self.total_dinero, self.n_dinero = 0, 0
        self.anunciar("Cuenta en cero.")

    def _modo_dinero(self, frame):
        try:
            texto, _ = self.ocr.texto(frame, (11, 6), 30)
        except Exception as e:
            print(f"Dinero (texto): {e}")
            texto = ""
        if not valores_en_texto(texto, BILLETES):
            try:
                texto += " " + self.ocr.numeros(frame)
            except Exception as e:
                print(f"Dinero (números): {e}")
        color = color_dominante_billete(frame)
        print(f"DEBUG - dinero: texto={texto!r} color={color}")
        if valores_en_texto(texto, BILLETES):
            frase, valor = identificar_billete(texto, color)
            if valor:
                frase += self._sumar_dinero(valor)
            self.anunciar(frase, guardar_modo="dinero")
            return
        monedas = identificar_monedas(frame, self._leer_moneda)
        if monedas:
            frase, total = frase_monedas(monedas)
            if total:
                frase += self._sumar_dinero(total)
            self.anunciar(frase, guardar_modo="dinero")
            return
        frase, valor = identificar_billete(texto, color)
        if valor:
            frase += self._sumar_dinero(valor)
        self.anunciar(frase)

    def _modo_figuras(self, frame, desde_camara=False):
        figuras = detectar_figuras(frame, recorte=desde_camara)
        if not figuras:
            self.anunciar("No se detectaron figuras. Coloca la figura sobre un fondo liso y con buena luz.")
        elif len(figuras) == 1:
            forma, color = figuras[0]
            self.anunciar(f"Se detectó un {forma} {color}.")
        else:
            detalle = ", ".join(f"{forma} {color}" for forma, color in figuras)
            self.anunciar(f"Se detectaron {len(figuras)} figuras, de izquierda a derecha: {detalle}.")

    def _preparar_mic(self):
        # En paralelo con el OCR (antes esperaba a que el OCR terminara + 2 s): la voz es la entrada principal de la
        # app y debe estar lista cuanto antes. Corre en su propio hilo, así que no frena la ventana.
        self.mic.preparar(lambda t: self.voz.hablar(t))
        if leer_config().get("voz_continua") and self.mic.modelo is not None:
            self.ui(lambda: self.alternar_voz_continua(True, silencioso=True))

    def _asegurar_detector(self):
        """Carga el detector de objetos la primera vez que se necesita (no al abrir la app)."""
        if not self._detector_iniciado:
            self._detector_iniciado = True
            threading.Thread(target=self.detector.cargar, daemon=True).start()

    def _modo_objetos(self, frame):
        self._asegurar_detector()
        if not self.detector.listo.is_set():
            self.voz.hablar("Preparando el detector de objetos.")
            self.detector.listo.wait(300)
        if self.detector.error:
            self.anunciar("El detector de objetos no está disponible. Conéctate a internet una vez para descargarlo.")
            return
        detecciones = self.detector.detectar(frame)
        anotada = frame.copy()
        for c, puntaje, (x1, y1, x2, y2) in detecciones:
            cv2.rectangle(anotada, (x1, y1), (x2, y2), (0, 170, 0), 3)
            cv2.putText(anotada, f"{CLASES_ES[c][0]} {puntaje:.0%}", (x1, max(y1 - 8, 20)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 120, 0), 2)
        cv2.imwrite(os.path.join(CARPETA_DEBUG, "objetos.png"), anotada)
        print(f"DEBUG - objetos: {[(CLASES_ES[c][0], round(p, 2)) for c, p, _ in detecciones]}")
        if detecciones:
            self.anunciar(frase_conteo(detecciones), guardar_modo="objetos")
            return
        # Sin objetos conocidos (el modelo no sabe de lápices, fichas, etc.): contar piezas de color sueltas
        h, w = frame.shape[:2]
        pequeno = cv2.resize(frame, (800, int(h * 800 / w)))
        piezas = [a for a in _candidatos_figuras(pequeno) if a["color"] not in ("blanco", "negro", "gris")]
        if piezas:
            n = len(piezas)
            self.anunciar(f"No reconocí objetos por su nombre, pero veo {n} pieza{'s' if n != 1 else ''} de color.",
                          guardar_modo="objetos")
        else:
            self.anunciar("No se detectaron objetos. Acerca la cámara, usa buena luz y un fondo liso.")

    # ----------------------------- Materiales -----------------------------
    def guardar_material(self, modo, texto):
        nombre = nombre_material(modo, texto)
        try:
            with open(os.path.join(CARPETA_MATERIALES, nombre), "w", encoding="utf-8") as f:
                f.write(texto)
            self.ui(self.refrescar_materiales)
        except OSError as e:
            print(f"No se pudo guardar el material: {e}")

    def refrescar_materiales(self):
        self.lista.delete(0, "end")
        consulta = ""
        try:
            consulta = self.var_busqueda.get().strip().lower()
        except Exception:
            pass
        archivos = sorted((a for a in os.listdir(CARPETA_MATERIALES) if a.endswith(".txt")), reverse=True)
        archivos.sort(key=lambda a: not a.startswith("★"))  # los favoritos arriba (el orden por fecha se conserva)
        self._archivos = []
        for a in archivos:
            if consulta:
                dentro = a.lower()
                if consulta not in dentro:
                    try:
                        with open(os.path.join(CARPETA_MATERIALES, a), encoding="utf-8", errors="ignore") as f:
                            dentro = f.read(6000).lower()
                    except OSError:
                        continue
                    if consulta not in dentro:
                        continue
            self._archivos.append(a)
            self.lista.insert("end", nombre_bonito(a))

    def _material_elegido(self):
        sel = self.lista.curselection()
        if not sel or sel[0] >= len(getattr(self, "_archivos", [])):
            self.voz.hablar("Selecciona un material de la lista.")
            return None
        return self._archivos[sel[0]]

    def favorito_material(self):
        a = self._material_elegido()
        if not a:
            return
        nuevo = a.lstrip("★_") if a.startswith("★") else "★_" + a
        try:
            os.rename(os.path.join(CARPETA_MATERIALES, a), os.path.join(CARPETA_MATERIALES, nuevo))
        except OSError as e:
            print(f"Favorito: {e}")
            return
        self.refrescar_materiales()
        self.voz.hablar("Quitado de favoritos." if a.startswith("★") else "Marcado como favorito.")

    def borrar_material(self):
        a = self._material_elegido()
        if not a:
            return
        if messagebox.askyesno("Borrar material", f"¿Borrar «{nombre_bonito(a)}»?"):
            try:
                os.remove(os.path.join(CARPETA_MATERIALES, a))
            except OSError as e:
                print(f"Borrar: {e}")
            self.refrescar_materiales()
            self.voz.hablar("Material borrado.")

    def escuchar_material(self):
        a = self._material_elegido()
        if not a:
            return
        with open(os.path.join(CARPETA_MATERIALES, a), encoding="utf-8") as f:
            texto = f.read()
        self.ultimo_texto = texto
        self.anunciar(texto)

    def importar_imagen(self):
        ruta = filedialog.askopenfilename(title="Importar imagen",
                                          filetypes=[("Imágenes", "*.png *.jpg *.jpeg *.bmp")])
        if not ruta:
            return
        frame = cv2.imdecode(np.fromfile(ruta, np.uint8), cv2.IMREAD_COLOR)  # soporta rutas con tildes
        if frame is None:
            messagebox.showerror("Imagen", "No se pudo abrir la imagen.")
            return
        modo = self.modo_actual if self.pantalla == "modo" else "texto"
        self.lanzar_analisis(frame, modo)

    def importar_documento(self):
        ruta = filedialog.askopenfilename(
            title="Importar documento",
            filetypes=[("Documentos e imágenes", "*.pdf *.docx *.txt *.md *.csv *.png *.jpg *.jpeg *.bmp"),
                       ("Documentos", "*.pdf *.docx *.txt *.md *.csv"), ("Todos", "*.*")])
        if ruta:
            self.abrir_archivo(ruta)

    def abrir_archivo(self, ruta):
        ext = os.path.splitext(ruta)[1].lower()
        if ext in EXT_IMG:
            frame = cv2.imdecode(np.fromfile(ruta, np.uint8), cv2.IMREAD_COLOR)
            if frame is None:
                self.voz.hablar("No se pudo abrir la imagen.")
                return
            self.lanzar_analisis(frame, self.modo_actual if self.pantalla == "modo" else "texto")
            return
        if ext not in EXT_DOC:
            self.voz.hablar("Ese tipo de archivo no es compatible. Usa PDF, Word, texto o imagen.")
            return
        if self.procesando:
            return
        self.procesando = True
        self.voz.hablar("Abriendo el documento.")
        self.lbl_resultado.config(text="Abriendo el documento...")
        self._gen_analisis = self._gen
        threading.Thread(target=self._leer_doc_hilo, args=(ruta,), daemon=True).start()

    def _leer_doc_hilo(self, ruta):
        try:
            def ocr_pag(bgr):
                if not self.ocr.listo.wait(60):
                    return ""
                return self._leer(bgr, (6, 3))

            def prog(i, n):
                self.ui(lambda: self.lbl_resultado.config(text=f"Leyendo página {i} de {n}..."))

            texto = leer_documento(ruta, ocr_pag, prog)
            if not texto:
                self.anunciar("No encontré texto en este documento.")
                return
            if self._gen_analisis is not None and self._gen_analisis != self._gen:
                return
            self.ultimo_audio = texto
            self.ui(lambda: self.lbl_resultado.config(text=texto[:600] + ("..." if len(texto) > 600 else "")))
            self.ultimo_texto = texto
            self.lectura.iniciar(texto)
            self.guardar_material("documento", texto)
        except Exception as e:
            print(f"Error al leer documento: {e}")
            self.anunciar(f"No pude abrir el documento. {e}" if isinstance(e, ValueError) else "No pude abrir el documento. Puede estar dañado.")
        finally:
            self._gen_analisis = None
            self.ui(self._terminar)

    def vigilar_entrada(self):
        """Conexión con dispositivos: todo archivo que se copie a la carpeta Entrada se recibe y se guarda en Materiales."""
        try:
            for a in os.listdir(CARPETA_ENTRADA):
                ruta = os.path.join(CARPETA_ENTRADA, a)
                if not os.path.isfile(ruta) or a in self._entrada_vista or not a.lower().endswith(EXT_DOC + EXT_IMG):
                    continue
                if time.time() - os.path.getmtime(ruta) < 2:  # aún se está copiando
                    continue
                self._entrada_vista.add(a)
                self.voz.hablar(f"Llegó un archivo: {os.path.splitext(a)[0]}. Se abrirá ahora." if self.pantalla != "modo" or not self.procesando else f"Llegó un archivo: {a}.")
                if not self.procesando:
                    self.abrir_archivo(ruta)
        except OSError:
            pass
        self.root.after(3000, self.vigilar_entrada)


    # ------------------------- Ayuda, color, significado -------------------------
    TUTORIAL = ("Bienvenido a EduAccesible. Esta aplicación lee en voz alta lo que le muestras a la cámara. "
                "Hay siete opciones: uno, leer texto. Dos, letras y palabras. Tres, números. Cuatro, figuras geométricas. "
                "Cinco, contar objetos. Seis, materiales guardados. Siete, ajustes. "
                "Para elegir una, di su nombre, pulsa su número, o haz la seña con la mano: un dedo, dos dedos, tres dedos, cuatro dedos, mano abierta. "
                "Después apunta la cámara y di capturar, o pulsa la letra C. "
                "Puedes decir repetir, silencio, pausa, continuar, siguiente, anterior, más lento o más rápido. "
                "Para volver di inicio o atrás. Para oír todas las señas di señas. Para oír esta ayuda otra vez di tutorial.")

    def tutorial(self):
        self.ultimo_audio = self.TUTORIAL
        self.lbl_resultado.config(text=self.TUTORIAL)
        self.lectura.iniciar(self.TUTORIAL)

    def alternar_encuadre(self):
        self.ayuda_encuadre = not self.ayuda_encuadre
        guardar_config(encuadre=self.ayuda_encuadre)
        if getattr(self, "btn_encuadre", None) is not None:
            self.btn_encuadre.config(text="🎯  Ayuda de encuadre: " + ("activada" if self.ayuda_encuadre else "apagada"))
        self._msg_encuadre = ""
        self.voz.hablar("Ayuda de encuadre activada. Te diré si hay poca luz o si la imagen está borrosa." if self.ayuda_encuadre
                        else "Ayuda de encuadre apagada.")

    def _revisar_encuadre(self, frame):
        msg, ok = calidad_imagen(frame)
        if not ok:
            aviso = msg
        else:
            aviso = "Se ve bien. Puedes capturar."
        ahora = time.time()
        if aviso != self._msg_encuadre or ahora - self._t_msg_encuadre > 20:
            if aviso == "Se ve bien. Puedes capturar." and self._msg_encuadre == "":
                self._msg_encuadre = aviso
                return  # no avisar que "se ve bien" si nunca hubo un problema
            self._msg_encuadre, self._t_msg_encuadre = aviso, ahora
            self.estado("🎯 " + aviso)
            if not self.voz.ocupada():
                self.voz.hablar(aviso)

    def decir_color(self):
        if self.pantalla != "modo":
            self.abrir_modo("texto")
            self.root.after(1800, self.decir_color)
            return
        if self.ultimo_frame is None:
            self.voz.hablar("La cámara no está disponible.")
            return
        c = color_del_centro(self.ultimo_frame)
        self.anunciar(f"El color del centro es {c}.")

    def _consulta_en_hilo(self, trabajo):
        def correr():
            try:
                trabajo()
            except Exception as e:
                print(f"Consulta: {e}")
                self.anunciar("No pude hacer la consulta. Revisa la conexión a internet.")
        threading.Thread(target=correr, daemon=True).start()

    def decir_significado(self):
        palabra = self.ultima_palabra
        if not palabra and self.ultimo_texto:
            palabras = [re.sub(r"[^\wáéíóúüñÁÉÍÓÚÜÑ]", "", w) for w in self.ultimo_texto.split()]
            palabra = max(palabras, key=len) if palabras else ""
        if not palabra:
            self.voz.hablar("Primero lee una palabra con la opción dos, letras y palabras, y luego di significado.")
            return
        self.voz.hablar(f"Buscando el significado de {palabra}.")

        def trabajo():
            r = buscar_significado(palabra)
            self.anunciar(f"{palabra}: {r}" if r else f"No encontré el significado de {palabra}. Prueba con otra palabra o revisa internet.")
        self._consulta_en_hilo(trabajo)

    def traducir_ultimo(self, de, a):
        texto = self.ultimo_texto or ""
        if not texto:
            self.voz.hablar("Primero lee un texto y luego di traducir.")
            return
        self.voz.hablar("Traduciendo.")

        def trabajo():
            r = traducir_texto(texto, de, a)
            if not r:
                self.anunciar("No pude traducir. Revisa la conexión a internet.")
            elif a == "en":
                self.ultimo_audio = r
                self.ui(lambda: self.lbl_resultado.config(text=r))
                self.lectura.detener()
                self.voz.hablar("En inglés:")
                self.voz.hablar_idioma(r, 0x09)
            else:
                self.anunciar(r)
        self._consulta_en_hilo(trabajo)

    # ----------------------------- Perfiles -----------------------------
    def cambiar_perfil(self, nuevo=None):
        cfg = leer_config()
        perfiles = list(cfg.get("perfiles") or ["General"])
        actual = cfg.get("perfil", "General")
        if nuevo:
            nuevo = " ".join(re.sub(r'[<>:"/\\|?*]', " ", nuevo).split())[:30]
            if not nuevo:
                return
            if nuevo not in perfiles:
                perfiles.append(nuevo)
        else:
            nuevo = perfiles[(perfiles.index(actual) + 1) % len(perfiles)] if actual in perfiles else perfiles[0]
        guardar_config(perfiles=perfiles, perfil=nuevo)
        _aplicar_perfil()
        self.refrescar_materiales()
        if getattr(self, "btn_perfil", None) is not None:
            self.btn_perfil.config(text=f"👤  Perfil: {nuevo}")
        self.voz.hablar(f"Perfil {nuevo}.")

    def nuevo_perfil(self):
        n = simpledialog.askstring("Perfil nuevo", "Nombre del estudiante o perfil:", parent=self.root)
        if n:
            self.cambiar_perfil(nuevo=n)

    # ------------------------ Letra grande y contraste ------------------------
    def alternar_letra(self):
        grande = not leer_config().get("letra_grande", False)
        guardar_config(letra_grande=grande)
        self._aplicar_letra(grande)
        if getattr(self, "btn_letra", None) is not None:
            self.btn_letra.config(text="🔠  Letra grande: " + ("sí" if grande else "no"))
        self.voz.hablar("Letra grande activada." if grande else "Letra normal.")

    def _compactar_barra(self, grande):
        """Con letra grande los 4 botones laterales ocuparían más que la ventana: se hacen más bajos."""
        for b in getattr(self, "_botones_barra", []):
            b.pack_configure(pady=3 if grande else 7, ipady=3 if grande else 14)

    def _aplicar_letra(self, grande):
        self._compactar_barra(grande)
        try:
            if not hasattr(self, "_escala_base"):
                self._escala_base = float(self.root.tk.call("tk", "scaling"))
            self.root.tk.call("tk", "scaling", self._escala_base * (1.2 if grande else 1.0))
        except Exception as e:
            print(f"Letra grande: {e}")

    def alternar_contraste(self):
        alto = not leer_config().get("contraste", False)
        guardar_config(contraste=alto)
        if getattr(self, "btn_contraste", None) is not None:
            self.btn_contraste.config(text="◐  Alto contraste: " + ("activado (reinicia)" if alto else "apagado (reinicia)"))
        self.voz.hablar("Alto contraste activado. Cierra y abre la aplicación para verlo." if alto
                        else "Alto contraste apagado. Cierra y abre la aplicación para verlo.")

    # ------------------------- Pruebas al arrancar -------------------------
    def autoprueba(self):
        problemas = []
        if self.cap is None:
            problemas.append("no encuentro la cámara")
        if not getattr(self.voz, "hay_espanol", True):
            problemas.append("falta la voz en español de Windows")
        if not self.mic.disponible():
            problemas.append("no hay micrófono o reconocimiento de voz")
        if not Gestos.disponible():
            problemas.append("los gestos no están disponibles")
        if problemas:
            self.voz.hablar("Atención: " + ", ".join(problemas) + ". Abre Ajustes, Diagnóstico, para más detalles.")

    # ---------------------------- Actualizaciones ----------------------------
    nueva_version = None
    btn_actualizar = None

    def buscar_version(self, manual=False):
        """Mira en GitHub (Releases) si hay una versión más nueva que VERSION_APP."""
        tag, url = ultima_version()
        if not tag:
            if manual:
                self.anunciar("No pude revisar si hay actualizaciones. Mira tu conexión a internet.")
            return
        if url and _numeros_version(tag) > _numeros_version(VERSION_APP):
            self.nueva_version = (tag, url)
            self.ui(self._ofrecer_actualizacion)
        elif manual:
            self.anunciar(f"Ya tienes la última versión, {VERSION_APP}.")

    def _ofrecer_actualizacion(self):
        tag = self.nueva_version[0]
        if self.btn_actualizar is not None:
            self.btn_actualizar.config(text=f"⬇  Actualizar a {tag}")
        self.voz.hablar(f"Hay una versión nueva de EduAccesible: {tag}. Di actualizar, o toca el botón Actualizar en Ajustes.")

    def pedir_actualizacion(self):
        if not self.nueva_version:
            self.voz.hablar("Buscando actualizaciones.")
            threading.Thread(target=lambda: self.buscar_version(manual=True), daemon=True).start()
            return
        tag, url = self.nueva_version
        if messagebox.askyesno("Actualizar", f"¿Instalar la versión {tag}?\nLa aplicación se cerrará y se volverá a abrir. "
                                             "Tus materiales y ajustes se conservan.", parent=self.root):
            threading.Thread(target=self._descargar_e_instalar, args=(url,), daemon=True).start()

    def _descargar_e_instalar(self, url):
        try:
            destino = os.path.join(tempfile.gettempdir(), "EduAccesible-Instalador-nuevo.exe")
            self.anunciar("Descargando la actualización. Puede tardar unos minutos.")
            req = urllib.request.Request(url, headers={"User-Agent": "EduAccesible"})
            with urllib.request.urlopen(req, timeout=30) as r, open(destino, "wb") as f:
                total, leido, ultimo = int(r.headers.get("Content-Length") or 0), 0, 0.0
                while True:
                    trozo = r.read(1 << 20)
                    if not trozo:
                        break
                    f.write(trozo)
                    leido += len(trozo)
                    if total and time.time() - ultimo > 2:
                        ultimo = time.time()
                        self.estado(f"⬇ Descargando la actualización: {leido * 100 // total} %")
            if os.path.getsize(destino) < 20_000_000:
                raise IOError("la descarga quedó incompleta")
            self.ui(lambda: self._lanzar_instalador(destino))
        except Exception as e:
            print(f"Actualización: {e}")
            self.anunciar("No pude descargar la actualización. Revisa tu conexión a internet e inténtalo otra vez.")

    def _lanzar_instalador(self, destino):
        self.voz.hablar("Instalando la actualización. La aplicación se reiniciará sola.")
        subprocess.Popen([destino, "/SILENT", "/CLOSEAPPLICATIONS", "/RESTARTAPPLICATIONS"], close_fds=True)
        self.root.after(2500, self.cerrar)

    def alternar_lento(self):
        self.modo_lento = not self.modo_lento
        guardar_config(lento=self.modo_lento)
        if getattr(self, "btn_lento", None) is not None:
            self.btn_lento.config(text="🐢  Modo equipo lento: " + ("activado" if self.modo_lento else "apagado"))
        if self.modo_lento:
            self.voz.hablar("Modo equipo lento activado. Cierra y abre la aplicación para que la cámara use menos resolución.")
        else:
            self.voz.hablar("Modo equipo lento apagado. Cierra y abre la aplicación para volver a la resolución normal.")

    def texto_diagnostico(self):
        def g(f, defecto="?"):
            try:
                return f()
            except Exception:
                return defecto
        cap = getattr(self, "_cap", None)
        res = g(lambda: f"{int(cap.get(3))}x{int(cap.get(4))}") if cap is not None else "sin cámara"
        lector = getattr(self, "lector", None)
        lineas = [
            f"EduAccesible {VERSION_APP} - diagnóstico",
            f"Windows: {g(lambda: sys.getwindowsversion().build, '?')} | Python {sys.version.split()[0]} | OpenCV {cv2.__version__} | núcleos {os.cpu_count()}",
            f"Modo equipo lento: {'sí' if self.modo_lento else 'no'} | perfil: {leer_config().get('perfil', 'General')} | velocidad de voz {leer_config().get('velocidad', -1)} | volumen {leer_config().get('volumen', 100)}",
            f"Cámara: {getattr(self, 'indice_camara', '?')} | resolución real {res} | cuadros/s {g(lambda: f'{lector.fps:.0f}') if lector else 'sin lector'}",
            f"Gestos: {'activos' if self.gestos_activos else 'apagados'} | análisis/s {g(lambda: f'{self._fps_gestos:.0f}')} | MediaPipe {'disponible' if MP_MANOS is not None else 'NO disponible: ' + MP_ERROR}",
            f"Estado de gestos: {g(lambda: self._texto_gestos)}",
            f"Voz que habla: {getattr(self.voz, 'descripcion', '?')} | español instalado: {'sí' if getattr(self.voz, 'hay_espanol', True) else 'NO'}",
            f"Voz continua: {'activa' if self.voz_continua else 'apagada'} | modelo de voz cargado: {'sí' if getattr(self.mic, 'modelo', None) is not None else 'no'}",
            f"Lector de texto listo: {'sí' if g(lambda: self.ocr.listo.is_set(), False) else 'todavía no'}",
            f"Wi-Fi: {'activo ' + self.wifi.url if self.wifi and self.wifi.activo() else 'apagado'}",
            f"Carpeta: {BASE_DIR}",
            "",
            "--- Registro (últimas líneas) ---",
            cola_registro(150),
        ]
        return "\n".join(lineas)

    def abrir_diagnostico(self):
        print("--- Diagnóstico abierto ---")
        texto = self.texto_diagnostico()
        v = tk.Toplevel(self.root)
        v.title("Diagnóstico de EduAccesible")
        v.geometry("820x560")
        v.configure(bg=CREMA)
        marco = tk.Frame(v, bg=CREMA)
        marco.pack(fill="both", expand=True, padx=10, pady=10)
        barra = tk.Scrollbar(marco)
        barra.pack(side="right", fill="y")
        caja = tk.Text(marco, wrap="word", font=("Consolas", 10), yscrollcommand=barra.set, bg="white", fg=TEXTO)
        caja.pack(side="left", fill="both", expand=True)
        barra.config(command=caja.yview)
        caja.insert("1.0", texto)
        caja.see("end")

        def copiar():
            self.root.clipboard_clear()
            self.root.clipboard_append(texto)
            self.voz.hablar("Diagnóstico copiado. Pégalo en un mensaje para enviarlo.")

        def abrir_carpeta():
            try:
                os.startfile(CARPETA_DEBUG)
            except Exception:
                messagebox.showinfo("Diagnóstico", f"Carpeta: {CARPETA_DEBUG}")
        fila = tk.Frame(v, bg=CREMA)
        fila.pack(pady=(0, 10))
        self.boton(fila, "📋 Copiar todo", VERDE, copiar, fuente=12).pack(side="left", padx=6, ipady=4, ipadx=10)
        self.boton(fila, "📂 Abrir carpeta del registro", NARANJA, abrir_carpeta, fuente=12).pack(side="left", padx=6, ipady=4, ipadx=10)
        self.boton(fila, "Cerrar", AMARILLO, v.destroy, fg=TEXTO, fuente=12).pack(side="left", padx=6, ipady=4, ipadx=10)

    def alternar_wifi(self):
        if self.wifi.activo():
            self.wifi.detener()
            self.voz.hablar("Recepción por Wi-Fi apagada.")
            self.lbl_resultado.config(text="Recepción por Wi-Fi apagada.")
            return
        try:
            self.wifi.iniciar()
        except OSError as e:
            self.voz.hablar("No se pudo activar el Wi-Fi. Puede que el puerto esté ocupado.")
            print(e)
            return
        c = " ".join(self.wifi.codigo)
        t = f"Para enviar archivos, abre en el celular la dirección {self.wifi.url} y escribe el código {self.wifi.codigo}."
        self.lbl_resultado.config(text=t)
        self.mostrar_qr()
        self.voz.hablar(f"Recepción por Wi-Fi activa. En el celular, conectado a la misma red, abre el navegador y escribe {self.wifi.url.replace('http://', '').replace('.', ' punto ').replace(':', ' dos puntos ')}. El código es {c}. Si Windows pregunta por el firewall, elige Permitir.")

    def mostrar_qr(self):
        """Ventana con un código QR: el celular lo escanea y abre la página con el código ya escrito."""
        v = tk.Toplevel(self.root)
        v.title("Recibir por Wi-Fi")
        v.configure(bg=CREMA)
        tk.Label(v, text="Escanea con la cámara del celular", font=("Segoe UI", 15, "bold"), fg=VERDE, bg=CREMA).pack(padx=20, pady=(14, 6))
        try:
            import segno
            matriz = [list(f) for f in segno.make(self.wifi.url_qr, error="m").matrix]
            n, c, borde = len(matriz), 7, 4
            lienzo = tk.Canvas(v, width=(n + 2 * borde) * c, height=(n + 2 * borde) * c, bg="white", highlightthickness=0)
            lienzo.pack(padx=20, pady=6)
            for y, fila in enumerate(matriz):
                for x, oscuro in enumerate(fila):
                    if oscuro:
                        lienzo.create_rectangle((x + borde) * c, (y + borde) * c, (x + borde + 1) * c, (y + borde + 1) * c, fill="black", width=0)
        except Exception as e:
            print(f"QR no disponible: {e}")
        tk.Label(v, text=f"O escribe en el navegador:\n{self.wifi.url}\nCódigo: {self.wifi.codigo}\n\nEl celular debe estar en la misma red Wi-Fi.\nSi Windows pregunta por el firewall, elige Permitir.",
                 font=("Segoe UI", 12), fg=TEXTO, bg=CREMA, justify="center").pack(padx=20, pady=6)
        self.boton(v, "Cerrar", AMARILLO, v.destroy, fg=TEXTO, fuente=12).pack(pady=(4, 14), ipadx=20, ipady=4)

    def abrir_entrada(self):
        try:
            os.startfile(CARPETA_ENTRADA)
        except Exception:
            messagebox.showinfo("Entrada", f"Carpeta: {CARPETA_ENTRADA}")

    def compartir_texto(self):
        t = getattr(self, "ultimo_audio", "") or ""
        if not t:
            self.voz.hablar("Todavía no hay nada para compartir.")
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(t)
        ruta = filedialog.asksaveasfilename(title="Guardar texto leído", defaultextension=".txt", filetypes=[("Texto", "*.txt")])
        if ruta:
            with open(ruta, "w", encoding="utf-8") as f:
                f.write(t)
            self.voz.hablar("Texto guardado.")
        else:
            self.voz.hablar("Texto copiado. Puedes pegarlo en otro programa.")

    def abrir_carpeta(self):
        try:
            os.startfile(CARPETA_MATERIALES)
        except Exception:
            messagebox.showinfo("Materiales", f"Carpeta: {CARPETA_MATERIALES}")

    # ------------------------------ Cierre --------------------------------
    def cerrar(self):
        self.voz_continua = False  # termina el bucle del micrófono
        lector, self.lector = self.lector, None
        cap, self._cap = self._cap, None
        parado = lector.parar(1.0) if lector is not None else True  # sin congelar el cierre si el teléfono no responde
        if cap is not None and parado:  # soltar la cámara con el hilo aún leyendo puede cerrar el programa de golpe
            cap.release()
        self.mic.cerrar_red()
        self.wifi.detener()
        self.voz.cerrar()
        if self.wifi:
            self.wifi.detener()
        self.root.destroy()



# ---------------------------------------------------------------------------
# Documentos (PDF, Word, texto)
# ---------------------------------------------------------------------------
EXT_TEXTO = (".txt", ".md", ".csv")
EXT_DOC = EXT_TEXTO + (".pdf", ".docx")
EXT_IMG = (".png", ".jpg", ".jpeg", ".bmp")


def _limpiar_doc(t):
    lineas = [" ".join(l.split()) for l in t.replace("\r", "\n").split("\n")]
    out, vacias = [], 0
    for l in lineas:
        if l:
            out.append(l)
            vacias = 0
        else:
            vacias += 1
            if vacias == 1 and out:
                out.append("")
    return "\n".join(out).strip()


def leer_docx(ruta):
    import docx
    d = docx.Document(ruta)
    partes = [p.text for p in d.paragraphs]
    for tabla in d.tables:
        for fila in tabla.rows:
            celdas = []
            for c in fila.cells:
                if c.text.strip() and c.text.strip() not in celdas:
                    celdas.append(c.text.strip())
            if celdas:
                partes.append(", ".join(celdas))
    return _limpiar_doc("\n".join(partes))


def leer_texto_plano(ruta):
    datos = open(ruta, "rb").read()
    for cod in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return _limpiar_doc(datos.decode(cod))
        except UnicodeDecodeError:
            continue
    return ""


def leer_pdf(ruta, ocr_pagina=None, max_ocr=40, progreso=None):
    """Texto del PDF. Si una página no tiene texto (escaneada) usa ocr_pagina(imagen BGR)."""
    from pypdf import PdfReader
    lector = PdfReader(ruta)
    if lector.is_encrypted:
        try:
            lector.decrypt("")
        except Exception:
            raise ValueError("El PDF está protegido con contraseña.")
    paginas, usados = [], 0
    total = len(lector.pages)
    pdfium = None
    for i, pag in enumerate(lector.pages):
        if progreso:
            progreso(i + 1, total)
        try:
            t = (pag.extract_text() or "").strip()
        except Exception:
            t = ""
        if len(t) < 15 and ocr_pagina is not None and usados < max_ocr:
            try:
                import pypdfium2 as pdfium_mod
                if pdfium is None:
                    pdfium = pdfium_mod.PdfDocument(ruta)
                img = pdfium[i].render(scale=2.2).to_numpy()
                bgr = cv2.cvtColor(img, cv2.COLOR_RGB2BGR) if img.shape[2] == 3 else cv2.cvtColor(img, cv2.COLOR_RGBA2BGR)
                t = (ocr_pagina(bgr) or "").strip()
                usados += 1
            except Exception as e:
                print(f"OCR de página {i + 1} falló: {e}")
        if t:
            paginas.append(t)
    return _limpiar_doc("\n\n".join(paginas))


def leer_documento(ruta, ocr_pagina=None, progreso=None):
    ext = os.path.splitext(ruta)[1].lower()
    if ext == ".pdf":
        return leer_pdf(ruta, ocr_pagina, progreso=progreso)
    if ext == ".docx":
        return leer_docx(ruta)
    if ext in EXT_TEXTO:
        return leer_texto_plano(ruta)
    raise ValueError("Formato no compatible. Usa PDF, Word (.docx), .txt o imagen.")


def trozos_voz(texto, tam=900):
    """Parte un texto largo por frases para leerlo sin cortes."""
    out, actual = [], ""
    for frase in texto.replace("\n", " \n ").split(". "):
        frase = frase.strip()
        if not frase:
            continue
        if len(actual) + len(frase) > tam and actual:
            out.append(actual)
            actual = ""
        actual += frase + ". "
    if actual.strip():
        out.append(actual.strip())
    return out


# ---------------------------------------------------------------------------
# Recibir archivos por Wi-Fi (el celular abre una página y sube el archivo)
# ---------------------------------------------------------------------------
def ip_local():
    import socket
    try:
        t = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        t.connect(("8.8.8.8", 80))
        ip = t.getsockname()[0]
        t.close()
        return ip
    except OSError:
        return "127.0.0.1"





# ---------------------------------------------------------------------------
# Recibir archivos por Wi-Fi (desde el navegador de un celular u otro computador)
# ---------------------------------------------------------------------------
PAGINA_WIFI = """<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>EduAccesible</title><style>body{font-family:Arial;background:#FAF6EB;color:#2B2650;text-align:center;padding:24px}
button,input{font-size:20px;padding:14px;margin:8px;border-radius:12px;border:2px solid #895DCA}button{background:#895DCA;color:#fff}
#m{font-size:20px;margin-top:18px}</style></head><body><h1>Enviar a EduAccesible</h1>
<p>Código que aparece en la pantalla:</p><input id="c" inputmode="numeric" maxlength="4" size="4"><br>
<input id="f" type="file" accept=".pdf,.docx,.txt,.md,.csv,.png,.jpg,.jpeg,.bmp"><br><button onclick="e()">Enviar</button><div id="m"></div>
<script>document.getElementById('c').value=new URLSearchParams(location.search).get('c')||'';async function e(){const f=document.getElementById('f').files[0],m=document.getElementById('m');
if(!f){m.textContent='Elige un archivo';return}m.textContent='Enviando...';
try{const r=await fetch('/subir',{method:'POST',headers:{'X-Nombre':encodeURIComponent(f.name),'X-Codigo':document.getElementById('c').value},body:f});
m.textContent=r.ok?'Enviado. Ya se está leyendo en EduAccesible.':(r.status==403?'Código incorrecto':'No se pudo enviar')}catch(x){m.textContent='Sin conexión'}}</script></body></html>"""


class ServidorWifi:
    def __init__(self, carpeta):
        self.carpeta = carpeta
        self.codigo = ""
        self.httpd = None
        self.url = ""

    @staticmethod
    def ip_local():
        import socket
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("10.255.255.255", 1))
            return s.getsockname()[0]
        except OSError:
            return "127.0.0.1"
        finally:
            s.close()

    def activo(self):
        return self.httpd is not None

    def iniciar(self, puerto=8765):
        import http.server
        import random
        self.codigo = f"{random.randint(0, 9999):04d}"
        dueno = self

        class H(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                datos = PAGINA_WIFI.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(datos)))
                self.end_headers()
                self.wfile.write(datos)

            def do_POST(self):
                if self.headers.get("X-Codigo", "") != dueno.codigo:
                    self.send_response(403)
                    self.end_headers()
                    return
                n = int(self.headers.get("Content-Length", 0))
                if n <= 0 or n > 60 * 1024 * 1024:
                    self.send_response(413)
                    self.end_headers()
                    return
                nombre = os.path.basename(urllib.parse.unquote(self.headers.get("X-Nombre", "archivo")))
                if not nombre.lower().endswith(EXT_DOC + EXT_IMG):
                    self.send_response(415)
                    self.end_headers()
                    return
                destino = os.path.join(dueno.carpeta, nombre)
                if os.path.exists(destino):
                    b, e = os.path.splitext(nombre)
                    destino = os.path.join(dueno.carpeta, f"{b}_{int(time.time())}{e}")
                with open(destino, "wb") as f:
                    restante = n
                    while restante > 0:
                        bloque = self.rfile.read(min(65536, restante))
                        if not bloque:
                            break
                        f.write(bloque)
                        restante -= len(bloque)
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"ok")

        self.httpd = http.server.ThreadingHTTPServer(("0.0.0.0", puerto), H)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.url = f"http://{self.ip_local()}:{puerto}"
        self.url_qr = f"{self.url}/?c={self.codigo}"

    def detener(self):
        if self.httpd:
            self.httpd.shutdown()
            self.httpd.server_close()
            self.httpd = None



# ---------------------------------------------------------------------------
# Utilidades: color, calidad de foto, cuentas, materiales, consultas en internet
# ---------------------------------------------------------------------------
def color_nombre(bgr):
    """Nombre en español de un color (b, g, r)."""
    px = np.uint8([[[int(bgr[0]), int(bgr[1]), int(bgr[2])]]])
    h, sat, v = (int(x) for x in cv2.cvtColor(px, cv2.COLOR_BGR2HSV)[0][0])
    if v < 50:
        return "negro"
    if sat < 40:
        return "blanco" if v > 200 else ("gris claro" if v > 140 else "gris")
    if h < 8 or h >= 170:
        base = "rosado" if (v > 200 and sat < 150) else "rojo"
    elif h < 22:
        base = "café" if v < 150 else "naranja"
    elif h < 35:
        base = "amarillo"
    elif h < 85:
        base = "verde"
    elif h < 100:
        base = "turquesa"
    elif h < 125:
        base = "celeste" if (sat < 120 and v > 180) else "azul"
    elif h < 150:
        base = "morado"
    else:
        base = "rosado" if (v > 200 and sat < 150) else "fucsia"
    if base not in ("café",):
        if v < 90:
            base += " oscuro"
        elif v > 235 and sat < 110:
            base += " claro"
    return base


def color_del_centro(frame):
    """Color dominante del centro de la imagen (mediana de la zona central)."""
    h, w = frame.shape[:2]
    zona = frame[int(h * .4):int(h * .6), int(w * .4):int(w * .6)]
    mediana = np.median(zona.reshape(-1, 3), axis=0)
    return color_nombre(mediana)


def calidad_imagen(frame):
    """(mensaje, ok): 'muy oscura', 'muy brillante', 'borrosa' o ok."""
    g = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    g = cv2.resize(g, (320, max(1, int(g.shape[0] * 320 / g.shape[1]))), interpolation=cv2.INTER_AREA)
    brillo = float(g.mean())
    nitidez = float(cv2.Laplacian(g, cv2.CV_64F).var())
    if brillo < 45:
        return "Hay muy poca luz. Busca más luz.", False
    if brillo > 225:
        return "Hay demasiado brillo o reflejo. Inclina un poco el papel.", False
    if nitidez < 25:
        return "La imagen está borrosa. Aleja un poco la cámara y mantenla quieta.", False
    return "", True


_OPS_LIBRES = re.compile(r"(\d+(?:[.,]\d+)?)\s*([+×÷*])\s*(\d+(?:[.,]\d+)?)")
_OPS_ESPACIO = re.compile(r"(?<![\w.,])(\d+(?:[.,]\d+)?)\s+([\-−–xX/:])\s+(\d+(?:[.,]\d+)?)(?![\w.,])")
_PALABRA_OP = {"+": "más", "×": "por", "*": "por", "x": "por", "X": "por", "÷": "dividido entre", "/": "dividido entre",
               ":": "dividido entre", "-": "menos", "−": "menos", "–": "menos"}


def _num_hablado(x):
    if abs(x - round(x)) < 1e-9:
        return str(int(round(x)))
    return f"{x:.2f}".rstrip("0").rstrip(".").replace(".", " coma ")


def operaciones_habladas(texto, maximo=5):
    """Detecta cuentas como '3 + 4' o '12 x 3 =' y devuelve cómo se dicen con su resultado."""
    hallazgos = []
    for rx in (_OPS_LIBRES, _OPS_ESPACIO):
        for m in rx.finditer(texto):
            hallazgos.append((m.start(), m.group(1), m.group(2), m.group(3)))
    hallazgos.sort()
    frases = []
    for _, a, op, b in hallazgos[:maximo]:
        x, y = float(a.replace(",", ".")), float(b.replace(",", "."))
        if op in "+":
            r = x + y
        elif op in "×*xX":
            r = x * y
        elif op in "÷/:":
            if y == 0:
                frases.append(f"{_num_hablado(x)} dividido entre cero no se puede hacer.")
                continue
            r = x / y
        else:
            r = x - y
        frases.append(f"{_num_hablado(x)} {_PALABRA_OP[op]} {_num_hablado(y)} es igual a {_num_hablado(r)}.")
    return " ".join(frases)


def nombre_material(modo, texto):
    t = re.sub(r"^(El texto dice|Cifra detectada|Letra)\s*:?\s*", "", texto.strip(), flags=re.I)
    t = re.sub(r'[<>:"/\\|?*\n\r\t]+', " ", t)
    slug = " ".join(t.split()[:6])[:40].strip(" .")
    base = f"{time.strftime('%Y%m%d_%H%M%S')}_{modo}"
    return f"{base}_{slug}.txt" if slug else f"{base}.txt"


def nombre_bonito(archivo):
    """'20261028_132301_texto_Hola mundo.txt' -> '28/10 13:23 · Texto · Hola mundo' (con ★ si es favorito)."""
    fav = archivo.startswith("★")
    a = archivo.lstrip("★_ ")
    m = re.match(r"^(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})\d{2}_([a-z]+)(?:_(.*))?\.txt$", a)
    if not m:
        return ("★ " if fav else "") + a.rsplit(".", 1)[0]
    _, mes, dia, hh, mm, modo, slug = m.groups()
    modo = {"numeros": "Números", "objetos": "Objetos", "figuras": "Figuras", "documento": "Documento"}.get(modo, modo.capitalize())
    return f"{'★ ' if fav else ''}{dia}/{mes} {hh}:{mm} · {modo}" + (f" · {slug}" if slug else "")


def _pedir_json(url, espera=6):
    req = urllib.request.Request(url, headers={"User-Agent": "EduAccesible/7 (apoyo educativo)"})
    with urllib.request.urlopen(req, timeout=espera) as r:
        return json.loads(r.read().decode("utf-8", errors="replace"))


def _limpiar_html(s):
    s = re.sub(r"<[^>]+>", " ", s or "")
    s = html.unescape(s)
    return " ".join(s.split()).strip(" .;:")


def _formas_palabra(p):
    """La palabra y sus posibles formas base (plural -> singular), para encontrarla en el diccionario."""
    p = p.strip().lower()
    formas = [p]
    if p.endswith("ces") and len(p) > 4:
        formas.append(p[:-3] + "z")
    if p.endswith("es") and len(p) > 4:
        formas.append(p[:-2])
    if p.endswith("s") and len(p) > 3:
        formas.append(p[:-1])
    for suf, nuevo in (("ando", "ar"), ("iendo", "er"), ("ado", "ar"), ("ido", "er")):
        if p.endswith(suf) and len(p) > len(suf) + 2:
            formas.append(p[:-len(suf)] + nuevo)
    vistos = []
    for f in formas:
        if f and f not in vistos:
            vistos.append(f)
    return vistos


def _definiciones_wiktionary(forma):
    """[(categoría, [definiciones])] del Wikcionario en español (diccionario colaborativo), o []."""
    try:
        d = _pedir_json("https://es.wiktionary.org/api/rest_v1/page/definition/" + urllib.parse.quote(forma))
    except Exception:
        return []
    salida = []
    for e in (d.get("es") or []):
        defs = [_limpiar_html(x.get("definition", "")) for x in e.get("definitions", [])]
        defs = [x for x in defs if len(x) > 3]
        if defs:
            salida.append((_limpiar_html(e.get("partOfSpeech", "")), defs))
    return salida


def _extracto_wiktionary(forma):
    """Plan B: texto de la página del Wikcionario; toma las líneas numeradas (las definiciones)."""
    try:
        d = _pedir_json("https://es.wiktionary.org/w/api.php?action=query&prop=extracts&explaintext=1&redirects=1"
                        "&format=json&titles=" + urllib.parse.quote(forma))
        paginas = (d.get("query") or {}).get("pages") or {}
        texto = next(iter(paginas.values())).get("extract", "") if paginas else ""
    except Exception:
        return []
    defs = []
    for linea in texto.splitlines():
        m = re.match(r"^\s*\d+\s+(.{8,})$", linea)
        if m:
            defs.append(_limpiar_html(m.group(1)))
    return [("", defs[:3])] if defs else []


def _resumen_wikipedia(forma):
    try:
        d = _pedir_json("https://es.wikipedia.org/api/rest_v1/page/summary/" + urllib.parse.quote(forma.capitalize()))
        ext = (d.get("extract") or "").strip()
        if not ext or d.get("type") == "disambiguation":
            return None
        return " ".join(re.split(r"(?<=[.!?])\s+", ext)[:2])[:420]
    except Exception:
        return None


def buscar_significado(palabra):
    """Significado en español. Prueba el Wikcionario (diccionario), luego su texto de respaldo y por último
    Wikipedia. Devuelve un texto hablable o None. Necesita internet."""
    palabra = re.sub(r"[^\wáéíóúüñÁÉÍÓÚÜÑ-]", "", palabra or "")
    if not palabra:
        return None
    formas = _formas_palabra(palabra)
    for buscador in (_definiciones_wiktionary, _extracto_wiktionary):
        for forma in formas:
            grupos = buscador(forma)
            if grupos:
                partes, n = [], 0
                for cat, defs in grupos:
                    for dfn in defs:
                        n += 1
                        if n > 3:
                            break
                        partes.append(f"{'Como ' + cat.lower() + ': ' if cat and n == 1 else ''}{n}, {dfn[:170]}")
                    if n > 3:
                        break
                return f"{forma}. " + ". ".join(partes) + "."
    for forma in formas:
        r = _resumen_wikipedia(forma)
        if r:
            return f"{forma}. {r}"
    return None


def _trocear(texto, maximo=400):
    frases = re.split(r"(?<=[.!?])\s+|\n+", texto.strip())
    trozos, actual = [], ""
    for f in frases:
        if not f:
            continue
        while len(f) > maximo:
            corte = f.rfind(" ", 0, maximo)
            corte = corte if corte > maximo // 2 else maximo
            trozos.append(f[:corte])
            f = f[corte:].strip()
        if len(actual) + len(f) + 1 > maximo and actual:
            trozos.append(actual)
            actual = f
        else:
            actual = (actual + " " + f).strip()
    if actual:
        trozos.append(actual)
    return trozos


def _traducir_google(texto, de, a):
    d = _pedir_json("https://translate.googleapis.com/translate_a/single?client=gtx&dt=t"
                    f"&sl={de}&tl={a}&q={urllib.parse.quote(texto)}", espera=8)
    return "".join(seg[0] for seg in d[0] if seg and seg[0]).strip()


def _traducir_mymemory(texto, de, a):
    d = _pedir_json(f"https://api.mymemory.translated.net/get?q={urllib.parse.quote(texto)}&langpair={de}|{a}")
    return ((d.get("responseData") or {}).get("translatedText") or "").strip()


def traducir_texto(texto, de="es", a="en"):
    """Traduce por partes. Primero el traductor de Google (sin clave, buena calidad); si no responde, MyMemory.
    Devuelve el texto traducido o None. Necesita internet."""
    salida = []
    for trozo in _trocear(texto)[:8]:
        t = ""
        for motor in (_traducir_google, _traducir_mymemory):
            try:
                t = motor(trozo, de, a)
            except Exception as e:
                print(f"Traducción ({motor.__name__}): {e}")
                t = ""
            if t:
                break
        if not t:
            return None
        salida.append(t)
    return " ".join(salida) or None


# ---------------------------------------------------------------------------
# Dinero colombiano: billetes (número escrito + color) y monedas (círculos + metal + número)
# ---------------------------------------------------------------------------
BILLETES = (2000, 5000, 10000, 20000, 50000, 100000)
MONEDAS = (50, 100, 200, 500, 1000)
_PALABRAS_BILLETE = {"dos mil": 2000, "cinco mil": 5000, "diez mil": 10000, "veinte mil": 20000,
                     "cincuenta mil": 50000, "cien mil": 100000}
# Color principal de cada billete (para confirmar o, si no se lee el número, adivinar con cuidado)
_COLOR_BILLETE = {2000: "azul", 5000: "café", 10000: "rojo", 20000: "naranja", 50000: "morado", 100000: "verde"}
_UNIDADES = {2000: "dos mil", 5000: "cinco mil", 10000: "diez mil", 20000: "veinte mil", 50000: "cincuenta mil",
             100000: "cien mil", 50: "cincuenta", 100: "cien", 200: "doscientos", 500: "quinientos", 1000: "mil"}


def pesos_hablados(n):
    """1500 -> 'mil quinientos pesos' (sirve para totales); si no se sabe decir, el número con puntos."""
    if n in _UNIDADES:
        return f"{_UNIDADES[n]} pesos"
    return f"{n:,}".replace(",", ".") + " pesos"


def _sin_tildes_simple(t):
    return "".join(c for c in unicodedata.normalize("NFD", t) if unicodedata.category(c) != "Mn")


def valores_en_texto(texto, validos):
    """Valores de 'validos' que aparecen como número ('50.000', '50 000', '50000') o en letras ('cincuenta mil')."""
    votos = {}
    t = _sin_tildes_simple(texto).lower()
    # confusiones típicas del OCR: O por 0 pegada a cifras
    for _ in range(4):  # "100.OOO" -> "100.000"
        t = re.sub(r"(?<=[\d.,])o(?=[\do.,\s]|$)", "0", t)
        t = re.sub(r"(?<=[\d.,])o(?=\d)", "0", t)
    for m in re.finditer(r"\d{1,3}(?:[.,\s']\d{3})+|\d{4,7}", t):
        v = int(re.sub(r"\D", "", m.group(0)))
        if v in validos:
            votos[v] = votos.get(v, 0) + 1
    palabras = re.sub(r"[^a-z\s]", " ", t).split()
    for i in range(len(palabras) - 1):
        par = f"{palabras[i]} {palabras[i + 1]}"
        for frase, v in _PALABRAS_BILLETE.items():
            if v in validos and difflib.SequenceMatcher(None, par, frase).ratio() >= 0.86:
                votos[v] = votos.get(v, 0) + 2
    return votos


def color_dominante_billete(frame):
    """Nombre del color que más domina en la imagen (ignora blancos, grises y negros)."""
    h0, w0 = frame.shape[:2]
    pequeno = cv2.resize(frame, (160, max(1, int(160 * h0 / w0))), interpolation=cv2.INTER_AREA)
    hsv = cv2.cvtColor(pequeno, cv2.COLOR_BGR2HSV).reshape(-1, 3)
    bueno = hsv[(hsv[:, 1] > 45) & (hsv[:, 2] > 60)]
    if len(bueno) < 80:
        return ""
    hist = np.bincount(bueno[:, 0].astype(int) // 5, minlength=36)
    pico = int(np.argmax(np.convolve(np.r_[hist[-1:], hist, hist[:1]], [1, 1, 1], "valid")))
    zona = bueno[(bueno[:, 0] // 5 >= pico - 1) & (bueno[:, 0] // 5 <= pico + 1)]
    mediana = np.median(zona, axis=0)
    px = cv2.cvtColor(np.uint8([[mediana]]), cv2.COLOR_HSV2BGR)[0][0]
    return color_nombre(px).replace(" oscuro", "").replace(" claro", "")


def _compatibles(color, valor):
    esp = _COLOR_BILLETE[valor]
    grupos = {"azul": ("azul", "celeste", "turquesa", "gris"), "café": ("café", "naranja", "amarillo", "rojo"),
              "rojo": ("rojo", "fucsia", "rosado", "café"), "naranja": ("naranja", "amarillo", "café"),
              "morado": ("morado", "fucsia", "azul", "rosado"), "verde": ("verde", "turquesa", "amarillo")}
    return color in grupos[esp]


def identificar_billete(texto_ocr, color):
    """(frase, valor_o_None). Combina lo que se leyó (número o letras) con el color del billete."""
    votos = valores_en_texto(texto_ocr, BILLETES)
    if votos:
        valor = max(votos, key=lambda v: (votos[v], v))
        frase = f"Es un billete de {pesos_hablados(valor)}."
        if color and not _compatibles(color, valor):
            frase += (f" Ojo: por el color ({color}) no coincide del todo; verifica con las marcas al tacto "
                      "o toma otra foto más cerca.")
        return frase, valor
    candidatos = [v for v in BILLETES if color and _compatibles(color, v)]
    if len(candidatos) == 1:
        return (f"No alcancé a leer el número. Por el color {color} parece un billete de {pesos_hablados(candidatos[0])}, "
                "pero no estoy seguro. Acércalo para que se vea el número de la esquina, con buena luz."), None
    return ("No pude reconocer el billete. Ponlo plano, con buena luz y acércalo hasta que se vea bien el número "
            "grande de la esquina."), None


def detectar_circulos(frame):
    """Monedas candidatas: lista de (x, y, r) en píxeles de la imagen, sin repetidos."""
    h0, w0 = frame.shape[:2]
    esc = 800.0 / max(w0, h0)
    g = cv2.cvtColor(cv2.resize(frame, None, fx=esc, fy=esc, interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2GRAY)
    g = cv2.medianBlur(g, 5)
    ancho = g.shape[1]
    c = cv2.HoughCircles(g, cv2.HOUGH_GRADIENT, dp=1.2, minDist=ancho * 0.07, param1=110, param2=36,
                         minRadius=int(ancho * 0.03), maxRadius=int(ancho * 0.2))
    if c is None:
        return []
    salida = []
    for x, y, r in sorted(c[0], key=lambda t: -t[2]):
        if all(math.hypot(x - a, y - b) > 0.6 * max(r, s) for a, b, s in salida):
            salida.append((float(x), float(y), float(r)))
    return [(x / esc, y / esc, r / esc) for x, y, r in salida[:12]]


def _tipo_metal(hsv_px):
    """'dorado' o 'plateado' según el color medio de una zona."""
    h, s, v = hsv_px
    return "dorado" if (s > 70 and 8 <= h <= 32) else "plateado"


def clasificar_moneda(frame, x, y, r):
    """(metal_centro, metal_borde) de una moneda: si son distintos es bimetálica."""
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    yy, xx = np.ogrid[:frame.shape[0], :frame.shape[1]]
    d = np.sqrt((xx - x) ** 2 + (yy - y) ** 2)
    centro = hsv[d < r * 0.45]
    borde = hsv[(d > r * 0.78) & (d < r * 0.95)]
    if len(centro) < 20 or len(borde) < 20:
        return None, None
    return _tipo_metal(np.median(centro, axis=0)), _tipo_metal(np.median(borde, axis=0))


def posibles_moneda(centro, borde):
    if centro is None:
        return ()
    if centro == "dorado" and borde == "plateado":
        return (500,)
    if centro == "plateado" and borde == "dorado":
        return (1000,)
    if centro == "dorado":
        return (100,)
    return (50, 200)


def identificar_monedas(frame, leer_numeros=None):
    """Lista de dicts {valor, seguro, opciones} y el texto hablado. leer_numeros(recorte)->texto (opcional)."""
    circulos = detectar_circulos(frame)
    monedas = []
    for x, y, r in circulos:
        c, b = clasificar_moneda(frame, x, y, r)
        opciones = posibles_moneda(c, b)
        if not opciones:
            continue
        leido = 0
        if leer_numeros is not None:
            x0, y0 = int(max(0, x - r)), int(max(0, y - r))
            recorte = frame[y0:int(y + r), x0:int(x + r)]
            if recorte.size:
                try:
                    votos = valores_en_texto(leer_numeros(recorte), MONEDAS)
                    if votos:
                        leido = max(votos, key=lambda v: (votos[v], v))
                except Exception as e:
                    print(f"Número de moneda: {e}")
        monedas.append({"r": r, "opciones": opciones, "leido": leido})
    # Plateadas ambiguas (50 o 200): la más grande de varias es la de 200 (si hay una de cada)
    ambiguas = [m for m in monedas if m["opciones"] == (50, 200) and not m["leido"]]
    if len(ambiguas) >= 2:
        radios = [m["r"] for m in ambiguas]
        if max(radios) / min(radios) > 1.18:
            corte = (max(radios) + min(radios)) / 2
            for m in ambiguas:
                m["opciones"] = (200,) if m["r"] > corte else (50,)
    for m in monedas:
        if m["leido"] and (m["leido"] in m["opciones"] or len(m["opciones"]) > 1 or True):
            m["valor"] = m["leido"]
            m["seguro"] = m["leido"] in m["opciones"]
        elif len(m["opciones"]) == 1:
            m["valor"], m["seguro"] = m["opciones"][0], True
        else:
            m["valor"], m["seguro"] = None, False
    return monedas


def frase_monedas(monedas):
    """(texto hablado, total de las seguras)."""
    if not monedas:
        return "No encontré monedas. Ponlas sobre una superficie lisa y oscura, separadas, con buena luz.", 0
    seguras = [m["valor"] for m in monedas if m["valor"] and m["seguro"]]
    dudosas = [m for m in monedas if not (m["valor"] and m["seguro"])]
    cuenta = {}
    for v in seguras:
        cuenta[v] = cuenta.get(v, 0) + 1
    partes = [f"{n} de {pesos_hablados(v)}" if n > 1 else f"una de {pesos_hablados(v)}"
              for v, n in sorted(cuenta.items(), reverse=True)]
    for m in dudosas:
        ops = " o ".join(str(o) for o in m["opciones"]) if m["opciones"] else "?"
        partes.append(f"una que no estoy seguro si es de {ops} pesos")
    total = sum(seguras)
    n = len(monedas)
    txt = f"Veo {n} moneda{'s' if n != 1 else ''}: " + ", ".join(partes) + "."
    if seguras:
        txt += f" Las seguras suman {pesos_hablados(total)}."
    return txt, total


def _numeros_version(v):
    return tuple(int(x) for x in re.findall(r"\d+", v or ""))


def ultima_version():
    """(etiqueta, dirección del instalador) de la última publicación (Release) en GitHub, o (None, None)."""
    try:
        d = _pedir_json(f"https://api.github.com/repos/{REPO_GITHUB}/releases/latest", espera=8)
        tag = d.get("tag_name") or ""
        for a in d.get("assets", []):
            if str(a.get("name", "")).lower().endswith(".exe"):
                return tag, a.get("browser_download_url")
        return tag or None, None
    except Exception as e:
        print(f"Buscar versión: {e}")
        return None, None


def diagnostico():
    """python app.py --diagnostico : revisa gestos y micrófono y muestra qué falla."""
    print("=" * 60)
    print("DIAGNÓSTICO DE EDUACCESIBLE")
    print("=" * 60)
    print(f"Python {sys.version.split()[0]}  ->  {sys.executable}")
    print(f"OpenCV {cv2.__version__} | numpy {np.__version__}")
    print("\n--- 0. VELOCIDAD DE LA CÁMARA (cuadros por segundo) ---")
    idx0 = leer_config().get("camara", 0)
    if isinstance(idx0, int):
        mejor = None
        for nombre, mjpg, ancho, alto in (("720p  sin MJPG (como antes)", False, 1280, 720), ("720p  MJPG", True, 1280, 720),
                                          ("1080p sin MJPG (como antes)", False, 1920, 1080), ("1080p MJPG", True, 1920, 1080)):
            c = cv2.VideoCapture(idx0, cv2.CAP_DSHOW)
            if not c.isOpened():
                print(f"   no se pudo abrir la cámara {idx0}")
                break
            if mjpg:
                c.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
            c.set(cv2.CAP_PROP_FRAME_WIDTH, ancho)
            c.set(cv2.CAP_PROP_FRAME_HEIGHT, alto)
            for _ in range(5):
                c.read()
            t = time.time()
            n = 0
            while time.time() - t < 2.5:
                if c.read()[0]:
                    n += 1
            fps = n / (time.time() - t)
            real = f"{int(c.get(3))}x{int(c.get(4))}"
            c.release()
            print(f"   {nombre:28s} -> {fps:5.1f} cuadros/s (resolución real {real})")
            if mjpg and (mejor is None or fps >= 24):
                mejor = (nombre, fps)
        print("   La app usa 720p MJPG. Para usar 1080p cambia RES_CAMARA al inicio de app.py si salió ≥ 24 cuadros/s.")
    print("\n--- 1. GESTOS (mediapipe) ---")
    if not Gestos.disponible():
        print("PROBLEMA: mediapipe no se puede usar.")
        print(f"Motivo: {MP_ERROR}")
        print("Prueba:  pip install mediapipe==0.10.14   (dentro del venv)")
    else:
        print("mediapipe: OK")
        cfg = leer_config()
        idx = cfg.get("camara", 0)
        cap = cv2.VideoCapture(idx, cv2.CAP_DSHOW) if isinstance(idx, int) else cv2.VideoCapture(idx)
        if not cap.isOpened():
            print(f"PROBLEMA: no se pudo abrir la cámara {idx}.")
        else:
            g = Gestos()
            g.iniciar()
            print("Se abrirá una ventana. Pon la mano frente a la cámara y haz los gestos (1 a 4 dedos, mano abierta,")
            print("puño, pulgar arriba). Verás puntos verdes sobre tu mano. Pulsa Q para terminar (o espera 25 s).")
            total = con_mano = 0
            vistos = {}
            t_fin = time.time() + 25
            try:
                while time.time() < t_fin:
                    ok, frame = cap.read()
                    if not ok:
                        continue
                    visto = g.leer(frame)
                    total += 1
                    if g.todas:
                        con_mano += 1
                        for puntos, clara in g.todas:  # BGR: verde = mano clara, naranja = dudosa (se ignora)
                            for (px, py) in puntos:
                                cv2.circle(frame, (int(px * frame.shape[1]), int(py * frame.shape[0])), 5,
                                           (0, 255, 0) if clara else (0, 165, 255), -1)
                    if visto:
                        vistos[visto] = vistos.get(visto, 0) + 1
                    texto = visto or (f"sin gesto: {g.nota}" if g.todas and g.nota else
                                      "mano sin gesto de la lista" if g.todas else "NO VEO MANO")
                    cv2.putText(frame, texto, (20, 50), cv2.FONT_HERSHEY_SIMPLEX, 1.4, (0, 0, 255), 3)
                    cv2.imshow("Diagnostico de gestos (Q = salir)", frame)
                    if cv2.waitKey(1) & 0xFF in (ord("q"), ord("Q")):
                        break
            except cv2.error as e:
                print(f"PROBLEMA con la ventana de OpenCV: {e}")
                print("Si dice 'not implemented', tienes opencv headless: pip uninstall opencv-python-headless")
            finally:
                cap.release()
                cv2.destroyAllWindows()
            if total:
                print(f"Cuadros analizados: {total} | con mano detectada: {con_mano} ({100 * con_mano // total} %)")
                print(f"Gestos reconocidos: {vistos or 'ninguno'}")
                if con_mano == 0:
                    print("-> La app NO ve tu mano: más luz, acerca la mano (30-60 cm) y deja la palma hacia la cámara.")
                elif not vistos:
                    print("-> Ve la mano pero no reconoce ningún gesto: dime qué gesto hacías.")

    # ------------------------------------------------------------------ MICRÓFONO
    print("\n--- 2. MICRÓFONO ---")
    if sd is None:
        print("PROBLEMA: falta sounddevice.  pip install sounddevice")
        return
    mic = Microfono()
    print(f"Micrófono por defecto: {mic.nombre_dispositivo()}")
    print("Micrófonos disponibles:")
    for i, nombre in mic.listar_microfonos():
        print(f"   [{i}] {nombre}")
    if vosk is None:
        print("vosk NO está instalado (solo funcionaría con internet).  pip install vosk")
    else:
        mic.preparar(print)
        print(f"Modelo de voz sin internet: {'OK' if mic.modelo is not None else 'NO CARGADO (¿falta descargarlo con internet?)'}")

    input("\nPulsa ENTER y después di claramente: 'capturar' ... ")
    print("Grabando 4 segundos... HABLA AHORA")
    audio = sd.rec(4 * 16000, samplerate=16000, channels=1, dtype="int16", device=mic.dispositivo)
    sd.wait()
    x = audio[:, 0].astype(np.float64)
    rms, pico = float(np.sqrt(np.mean(x ** 2))), int(np.abs(x).max())
    print(f"Nivel de voz: promedio {rms:.0f} | pico {pico}")
    if pico < 4000:
        print("-> Volumen BAJO. La app lo sube sola (hasta x10), pero ayuda subir el volumen del micrófono en Windows")
        print("   (Configuración > Sistema > Sonido > Entrada > tu micrófono > Volumen) o acercarte más.")
    elif pico > 31000:
        print("-> Está SATURADO (demasiado fuerte): baja el volumen del micrófono en Windows.")
    else:
        print("-> El nivel está bien.")
    if mic.modelo is not None:
        crudo = audio.tobytes()
        for nombre, gram in (("solo con las palabras de la app", json.dumps(GRAMATICA, ensure_ascii=False)),
                             ("libre (cualquier palabra)", None)):
            rec = vosk.KaldiRecognizer(mic.modelo, 16000, gram) if gram else vosk.KaldiRecognizer(mic.modelo, 16000)
            rec.AcceptWaveform(crudo)
            texto = json.loads(rec.FinalResult()).get("text", "")
            print(f"Entendió ({nombre}): {texto!r}  -> orden: {interpretar_orden(texto) if texto else None}")
    print("\n--- 3. LA MISMA RUTA QUE USA LA APP (tecla V) ---")
    input("Pulsa ENTER y di 'capturar' (tienes 6 segundos) ... ")
    try:
        oido = []
        texto = mic.escuchar(max_seg=6, al_oir=oido.append)
        print(f"Iba oyendo: {oido}")
        print(f"Resultado final: {texto!r}  -> orden: {interpretar_orden(texto) if texto else None}")
    except Exception:
        import traceback
        print("PROBLEMA: la ruta de la app falla con este error:")
        traceback.print_exc()
    tel = leer_config().get("telefono_audio")
    if tel:
        print(f"\n--- 4. MICRÓFONO DEL TELÉFONO ({tel}) ---")
        try:
            f = FlujoRed(tel)
            datos, _ = f.read(16000)
            x = np.frombuffer(datos, np.int16)
            print(f"Audio recibido del teléfono: {f.tasa} Hz originales, nivel pico {int(np.abs(x).max())}")
            f.close()
        except Exception as e:
            print(f"PROBLEMA con el micrófono del teléfono: {e}")
    print("\nListo. Copia TODO lo que salió en esta ventana y mándamelo.")


if __name__ == "__main__":
    if "--diagnostico" in sys.argv:
        diagnostico()
    else:
        root = tk.Tk()
        app = EduAccesibleApp(root)
        root.mainloop()
