"""Diccionario de palabras clave con pesos semánticos (motor determinista).

Cada entrada es una frase (una o varias palabras) con:

* ``level``     nivel de urgencia que dispara (``None`` = término indicador: no suma
                urgencia, pero sirve para detectar negaciones, p. ej. "daños" en "sin daños").
* ``category``  familia semántica que usan las reglas de inconsistencia.
* ``weight``    peso en la puntuación de urgencia.

Las frases se escriben en lenguaje natural (con tildes, singular o plural): el
clasificador normaliza el texto igual que estas entradas (minúsculas, sin tildes,
sin plural ni vocal de género), así "heridos", "herida" y "herido" coinciden con
la misma entrada.

Para ajustar el triaje sin tocar código basta con editar estas listas; la suite
`eval/` mide el efecto de cada cambio sobre los casos dorados.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ClaimType(str, Enum):
    AUTO = "AUTO"
    MEDICAL = "MEDICAL"
    HOME = "HOME"


class UrgencyLevel(str, Enum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    LOW = "LOW"

    @property
    def rank(self) -> int:
        return {"CRITICAL": 3, "HIGH": 2, "LOW": 1}[self.value]


# Categorías semánticas
INJURY = "injury"                    # lesiones personales
FATALITY = "fatality"                # fallecimientos
EMERGENCY = "emergency_services"     # ambulancia, bomberos
FIRE = "fire_explosion"
VIOLENT_CRIME = "violent_crime"
PROPERTY_CRIME = "property_crime"
MEDICAL_CARE = "medical_care"        # hospitalización, cirugía
SEVERE_DAMAGE = "severe_damage"      # destrucción total
MINOR_DAMAGE = "minor_damage"        # rayones, espejo roto
GENERIC_DAMAGE = "generic_damage"    # "daño(s)" sin calificar
WATER = "water_damage"


@dataclass(frozen=True)
class LexiconEntry:
    phrase: str
    level: UrgencyLevel | None
    category: str
    weight: float


C, H, L = UrgencyLevel.CRITICAL, UrgencyLevel.HIGH, UrgencyLevel.LOW

LEXICON: tuple[LexiconEntry, ...] = (
    # ------------------------------------------------------------------ CRÍTICO
    # → asignación inmediata de un agente humano (SLA 15 min)
    LexiconEntry("heridos", C, INJURY, 10),
    LexiconEntry("lesionados", C, INJURY, 10),
    LexiconEntry("fallecido", C, FATALITY, 12),
    LexiconEntry("fallecimiento", C, FATALITY, 12),
    LexiconEntry("falleció", C, FATALITY, 12),
    LexiconEntry("fallecer", C, FATALITY, 12),
    LexiconEntry("murió", C, FATALITY, 12),
    LexiconEntry("morir", C, FATALITY, 12),
    LexiconEntry("muerto", C, FATALITY, 12),
    LexiconEntry("ambulancia", C, EMERGENCY, 10),
    LexiconEntry("bomberos", C, EMERGENCY, 8),
    LexiconEntry("fuego", C, FIRE, 10),
    LexiconEntry("en llamas", C, FIRE, 10),
    LexiconEntry("explosión", C, FIRE, 12),
    LexiconEntry("explotó", C, FIRE, 12),
    LexiconEntry("robo con violencia", C, VIOLENT_CRIME, 12),
    LexiconEntry("robo violento", C, VIOLENT_CRIME, 12),
    LexiconEntry("a mano armada", C, VIOLENT_CRIME, 12),
    LexiconEntry("asalto armado", C, VIOLENT_CRIME, 12),
    LexiconEntry("con violencia", C, VIOLENT_CRIME, 12),
    LexiconEntry("armados", C, VIOLENT_CRIME, 10),
    LexiconEntry("inconsciente", C, INJURY, 10),
    LexiconEntry("atrapado", C, INJURY, 10),
    LexiconEntry("hemorragia", C, INJURY, 10),
    LexiconEntry("sangrando", C, INJURY, 10),
    LexiconEntry("atropellado", C, INJURY, 10),
    LexiconEntry("infarto", C, MEDICAL_CARE, 10),
    LexiconEntry("quemaduras", C, INJURY, 10),
    # ------------------------------------------------------------------ ALTO
    # → validación humana en máximo 2 horas
    LexiconEntry("hospitalización", H, MEDICAL_CARE, 5),
    LexiconEntry("hospitalizado", H, MEDICAL_CARE, 5),
    LexiconEntry("cirugía", H, MEDICAL_CARE, 5),
    LexiconEntry("operación quirúrgica", H, MEDICAL_CARE, 5),
    LexiconEntry("urgencias", H, MEDICAL_CARE, 4),
    LexiconEntry("fractura", H, INJURY, 5),
    LexiconEntry("lesiones", H, INJURY, 5),
    LexiconEntry("incendio", H, FIRE, 6),
    LexiconEntry("robo", H, PROPERTY_CRIME, 5),
    LexiconEntry("robar", H, PROPERTY_CRIME, 5),
    LexiconEntry("hurto", H, PROPERTY_CRIME, 5),
    LexiconEntry("inundación", H, WATER, 5),
    LexiconEntry("derrumbe", H, SEVERE_DAMAGE, 6),
    LexiconEntry("colapso", H, SEVERE_DAMAGE, 6),
    LexiconEntry("pérdida total", H, SEVERE_DAMAGE, 6),
    LexiconEntry("completamente destruido", H, SEVERE_DAMAGE, 6),
    LexiconEntry("totalmente destruido", H, SEVERE_DAMAGE, 6),
    LexiconEntry("destruido", H, SEVERE_DAMAGE, 5),
    LexiconEntry("destrozado", H, SEVERE_DAMAGE, 5),
    LexiconEntry("calcinado", H, SEVERE_DAMAGE, 6),
    LexiconEntry("volcamiento", H, SEVERE_DAMAGE, 5),
    LexiconEntry("se volcó", H, SEVERE_DAMAGE, 5),
    # ------------------------------------------------------------------ LEVE
    # → aprobación automática o revisión rápida
    LexiconEntry("rayones", L, MINOR_DAMAGE, 1),
    LexiconEntry("rasguño", L, MINOR_DAMAGE, 1),
    LexiconEntry("espejo roto", L, MINOR_DAMAGE, 1),
    LexiconEntry("retrovisor roto", L, MINOR_DAMAGE, 1),
    LexiconEntry("pintura", L, MINOR_DAMAGE, 1),
    LexiconEntry("pequeños daños", L, MINOR_DAMAGE, 1),
    LexiconEntry("daños menores", L, MINOR_DAMAGE, 1),
    LexiconEntry("daño leve", L, MINOR_DAMAGE, 1),
    LexiconEntry("abolladura", L, MINOR_DAMAGE, 1),
    LexiconEntry("golpe leve", L, MINOR_DAMAGE, 1),
    LexiconEntry("vidrio roto", L, MINOR_DAMAGE, 1),
    LexiconEntry("gotera", L, MINOR_DAMAGE, 1),
    # ------------------------------------------------------------------ formas verbales
    # Sin lematizador (se retiró spaCy, ver classifier.py), un verbo conjugado no coincide
    # con su infinitivo: "robaron" no normaliza a "robo". En vez de adivinar con reglas de
    # sufijos —que generan falsos positivos— se listan las conjugaciones frecuentes en los
    # relatos reales. La suite eval/ mide qué tanto cubre esta lista y expone lo que falta.
    LexiconEntry("robaron", H, PROPERTY_CRIME, 5),
    LexiconEntry("robó", H, PROPERTY_CRIME, 5),
    LexiconEntry("hurtaron", H, PROPERTY_CRIME, 5),
    LexiconEntry("atropellaron", C, INJURY, 10),
    LexiconEntry("atropelló", C, INJURY, 10),
    LexiconEntry("fracturé", H, INJURY, 5),
    LexiconEntry("fracturó", H, INJURY, 5),
    LexiconEntry("fracturaron", H, INJURY, 5),
    LexiconEntry("operaron", H, MEDICAL_CARE, 5),
    LexiconEntry("operar", H, MEDICAL_CARE, 5),
    LexiconEntry("hospitalizaron", H, MEDICAL_CARE, 5),
    LexiconEntry("incendió", H, FIRE, 6),
    LexiconEntry("incendiaron", H, FIRE, 6),
    LexiconEntry("quemó", H, FIRE, 6),
    LexiconEntry("quemaron", H, FIRE, 6),
    LexiconEntry("inundó", H, WATER, 5),
    LexiconEntry("inundaron", H, WATER, 5),
    LexiconEntry("destruyó", H, SEVERE_DAMAGE, 5),
    LexiconEntry("destruyeron", H, SEVERE_DAMAGE, 5),
    LexiconEntry("volcó", H, SEVERE_DAMAGE, 5),
    LexiconEntry("murieron", C, FATALITY, 12),
    LexiconEntry("fallecieron", C, FATALITY, 12),
    LexiconEntry("sangre", C, INJURY, 8),
    LexiconEntry("amarraron", C, VIOLENT_CRIME, 10),
    # ------------------------------------------------------------------ indicadores (peso 0)
    # No cambian la urgencia; permiten detectar negaciones ("sin daños", "nadie herido").
    LexiconEntry("daños", None, GENERIC_DAMAGE, 0),
    LexiconEntry("afectaciones", None, GENERIC_DAMAGE, 0),
)

# Palabras que niegan el término que las sigue dentro de la misma cláusula.
NEGATORS: frozenset[str] = frozenset({
    "no", "sin", "ningun", "ninguna", "ninguno", "ni", "nadie", "nunca", "jamas", "tampoco", "cero",
})

# Palabras que cortan el alcance de una negación ("sin daños, PERO hay heridos").
CLAUSE_BREAKERS: frozenset[str] = frozenset({
    "pero", "aunque", "sino", "y", "e", "mientras", "luego", "despues", "entonces", "embargo", "ademas",
})

# Ventana (en palabras) hacia atrás en la que se busca un negador.
NEGATION_WINDOW = 3

# Vocabulario de dominio para detectar un tipo de siniestro que no corresponde al relato.
DOMAIN_TERMS: dict[ClaimType, frozenset[str]] = {
    ClaimType.AUTO: frozenset({
        "auto", "carro", "vehículo", "coche", "camioneta", "moto", "motocicleta", "choque", "chocó",
        "colisión", "parachoques", "llanta", "conductor", "autopista", "carretera", "semáforo",
        "retrovisor", "capó", "placa", "taxi", "bus", "bómper", "buseta",
    }),
    ClaimType.MEDICAL: frozenset({
        "hospital", "clínica", "médico", "cirugía", "fractura", "dolor", "urgencias", "diagnóstico",
        "hospitalización", "enfermedad", "tratamiento", "paciente", "caída", "infarto", "medicamento",
    }),
    ClaimType.HOME: frozenset({
        "casa", "vivienda", "hogar", "apartamento", "techo", "tubería", "inundación", "cocina",
        "fachada", "pared", "ventana", "puerta", "gotera", "humedad", "baño", "garaje", "edificio",
    }),
}
