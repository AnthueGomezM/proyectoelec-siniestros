"""Clasificador determinista de urgencia (sin LLM, sin red, sin dependencias).

Es la herramienta `clasificar_urgencia` que llama el agente. Deliberadamente NO usa
el modelo de lenguaje: la clasificación de urgencia es la decisión más sensible del
sistema (de ella depende que una persona con heridos espere 15 minutos o 2 horas) y
debe ser reproducible, auditable y explicable término por término. El LLM orquesta;
esta función decide. Ver docs/decisiones.md § "Frontera IA / código determinista".

Algoritmo (3 pasos):
  1. Normalizar cada palabra: minúsculas → sin tildes → sin plural → sin vocal de
     género. "Heridos" → "herid", "herida" → "herid", "rayones" → "rayon".
  2. Emparejar frases del léxico (gana la coincidencia más larga: "robo con
     violencia" (CRÍTICO) le gana a "robo" (ALTO)).
  3. Marcar términos negados mirando 3 palabras hacia atrás, sin cruzar el final de
     la cláusula ("sin heridos" niega; "no hubo daños, pero hay heridos" no).

Versión anterior del proyecto usaba spaCy para lematizar. Se retiró: añadía ~450 MB
a la imagen y ~3 s al arranque, y las formas verbales que aportaba se cubren
listándolas en el léxico. La suite eval/ respalda esta decisión con números.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Any, Iterable, Sequence

from claims_agent.nlp import lexicon as lx
from claims_agent.nlp.lexicon import ClaimType, LexiconEntry, UrgencyLevel

RULES_VERSION = "reglas-v2"
ENGINE = "lexico-ponderado"

# Acciones recomendadas (coinciden con el CHECK de claim_assessments.recommended_action)
ASSIGN_AGENT_IMMEDIATELY = "ASSIGN_AGENT_IMMEDIATELY"
HUMAN_VALIDATION_2H = "HUMAN_VALIDATION_2H"
AUTO_APPROVE = "AUTO_APPROVE"
FAST_TRACK_REVIEW = "FAST_TRACK_REVIEW"
MANUAL_REVIEW = "MANUAL_REVIEW"

SLA_MINUTES: dict[str, int | None] = {
    ASSIGN_AGENT_IMMEDIATELY: 15,
    HUMAN_VALIDATION_2H: 120,
    FAST_TRACK_REVIEW: 24 * 60,
    MANUAL_REVIEW: 8 * 60,
    AUTO_APPROVE: None,
}

ACTION_ES = {
    ASSIGN_AGENT_IMMEDIATELY: "Asignar agente de inmediato",
    HUMAN_VALIDATION_2H: "Validación humana en máximo 2 horas",
    AUTO_APPROVE: "Aprobación automática",
    FAST_TRACK_REVIEW: "Revisión rápida",
    MANUAL_REVIEW: "Revisión manual",
}

INCONSISTENCY_ES = {
    "DAMAGE_DENIED_BUT_SEVERE": "Niega daños pero describe daños graves",
    "INJURY_DENIED_BUT_EVIDENCE": "Niega lesionados pero hay evidencia de atención médica o emergencias",
    "SEVERITY_CONTRADICTION": "La descripción mezcla daños leves con destrucción grave",
    "CLAIM_TYPE_MISMATCH": "El tipo declarado no corresponde al relato",
}

_TOKEN_RE = re.compile(r"[0-9A-Za-zÁÉÍÓÚÜÑáéíóúüñ]+|[^\sA-Za-z0-9ÁÉÍÓÚÜÑáéíóúüñ]")


# ---------------------------------------------------------------------------- normalización

def strip_accents(text: str) -> str:
    return "".join(ch for ch in unicodedata.normalize("NFD", text) if unicodedata.category(ch) != "Mn")


def normalize(word: str) -> str:
    """Clave de comparación de una palabra (ver docstring del módulo)."""
    w = strip_accents(word.lower().strip())
    if len(w) > 4 and w.endswith("es") and w[-3] in "nrldzsj":
        w = w[:-2]
    elif len(w) > 3 and w.endswith("s"):
        w = w[:-1]
    if len(w) > 4 and w[-1] in "ao":
        w = w[:-1]
    return w


# ---------------------------------------------------------------------------- resultados

@dataclass(frozen=True)
class KeywordMatch:
    term: str                  # entrada del léxico
    matched: str               # texto tal como aparece en el relato
    level: UrgencyLevel | None
    category: str
    weight: float
    negated: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "term": self.term,
            "matched": self.matched,
            "level": self.level.value if self.level else "NONE",
            "category": self.category,
            "weight": self.weight,
            "negated": self.negated,
        }


@dataclass(frozen=True)
class Inconsistency:
    code: str
    description: str
    evidence: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "description": self.description, "evidence": list(self.evidence)}


@dataclass(frozen=True)
class Assessment:
    urgency_level: UrgencyLevel
    urgency_score: float
    keywords: tuple[KeywordMatch, ...]
    inconsistencies: tuple[Inconsistency, ...]
    recommended_action: str
    sla_minutes: int | None
    engine_version: str
    evidence_found: bool

    @property
    def inconsistencies_flag(self) -> bool:
        return bool(self.inconsistencies)

    def to_dict(self) -> dict[str, Any]:
        return {
            "urgencia": self.urgency_level.value,
            "puntuacion": round(self.urgency_score, 2),
            "accion_recomendada": self.recommended_action,
            "accion_es": ACTION_ES[self.recommended_action],
            "sla_minutos": self.sla_minutes,
            "palabras_clave": [k.to_dict() for k in self.keywords],
            "inconsistencias": [i.to_dict() for i in self.inconsistencies],
            "tiene_inconsistencias": self.inconsistencies_flag,
            "evidencia_encontrada": self.evidence_found,
            "motor": self.engine_version,
        }


# ---------------------------------------------------------------------------- clasificador

@dataclass(frozen=True)
class _Compiled:
    entry: LexiconEntry
    keys: tuple[str, ...]


class UrgencyClassifier:
    """Clasifica un relato en CRITICAL / HIGH / LOW y detecta inconsistencias.

    Sin estado tras la construcción: una instancia se reutiliza en todo el proceso.
    """

    def __init__(self, entries: Sequence[LexiconEntry] = lx.LEXICON, auto_approve_low: bool = True) -> None:
        self.auto_approve_low = auto_approve_low
        self.engine_version = f"{ENGINE}/{RULES_VERSION}"
        self._entries = tuple(_Compiled(e, tuple(normalize(w) for w in e.phrase.split())) for e in entries)
        self._by_first: dict[str, list[_Compiled]] = {}
        for compiled in self._entries:
            self._by_first.setdefault(compiled.keys[0], []).append(compiled)
        self._domain = {t: frozenset(normalize(w) for w in words) for t, words in lx.DOMAIN_TERMS.items()}

    # -- API ------------------------------------------------------------------

    def classify(self, description: str, claim_type: ClaimType | str | None = None) -> Assessment:
        if isinstance(claim_type, str):
            try:
                claim_type = ClaimType(claim_type.upper())
            except ValueError:
                claim_type = None

        tokens = self._tokenize(description)
        matches = self._match(tokens)
        active = [m for m in matches if not m.negated and m.level is not None]

        if any(m.level is UrgencyLevel.CRITICAL for m in active):
            urgency = UrgencyLevel.CRITICAL
        elif any(m.level is UrgencyLevel.HIGH for m in active):
            urgency = UrgencyLevel.HIGH
        else:
            urgency = UrgencyLevel.LOW
        score = round(sum(m.weight for m in active), 2)

        inconsistencies = self._inconsistencies(matches, tokens, claim_type)
        evidence = bool(active)
        action = self._recommend(urgency, evidence, bool(inconsistencies))
        return Assessment(
            urgency_level=urgency,
            urgency_score=score,
            keywords=tuple(matches),
            inconsistencies=tuple(inconsistencies),
            recommended_action=action,
            sla_minutes=SLA_MINUTES[action],
            engine_version=self.engine_version,
            evidence_found=evidence,
        )

    # -- tokenización y emparejamiento ----------------------------------------

    @staticmethod
    def _tokenize(text: str) -> list[tuple[str, str, bool]]:
        """(texto original, clave normalizada, es_puntuación)"""
        out: list[tuple[str, str, bool]] = []
        for raw in _TOKEN_RE.findall(text or ""):
            is_punct = not raw[0].isalnum()
            out.append((raw, "" if is_punct else normalize(raw), is_punct))
        return out

    def _match(self, tokens: list[tuple[str, str, bool]]) -> list[KeywordMatch]:
        candidates: list[tuple[int, int, _Compiled]] = []
        for i, (_, key, is_punct) in enumerate(tokens):
            if is_punct:
                continue
            for compiled in self._by_first.get(key, ()):
                n = len(compiled.keys)
                if i + n > len(tokens):
                    continue
                if all(tokens[i + j][1] == compiled.keys[j] for j in range(n)):
                    candidates.append((i, i + n, compiled))

        # Sin solapamiento: primero la frase más larga, luego la de mayor urgencia/peso.
        def priority(c: tuple[int, int, _Compiled]) -> tuple[int, int, int, float]:
            start, end, compiled = c
            level_rank = compiled.entry.level.rank if compiled.entry.level else 0
            return (start, -(end - start), -level_rank, -compiled.entry.weight)

        selected: list[KeywordMatch] = []
        occupied: set[int] = set()
        for start, end, compiled in sorted(set(candidates), key=priority):
            span = set(range(start, end))
            if span & occupied:
                continue
            occupied |= span
            selected.append(KeywordMatch(
                term=compiled.entry.phrase,
                matched=" ".join(tokens[k][0] for k in range(start, end)),
                level=compiled.entry.level,
                category=compiled.entry.category,
                weight=compiled.entry.weight,
                negated=self._is_negated(tokens, start),
            ))
        return selected

    @staticmethod
    def _is_negated(tokens: list[tuple[str, str, bool]], start: int) -> bool:
        """¿Hay un negador en las N palabras previas, dentro de la misma cláusula?"""
        seen = 0
        i = start - 1
        while i >= 0 and seen < lx.NEGATION_WINDOW:
            text, _, is_punct = tokens[i]
            raw = strip_accents(text.lower())
            if is_punct or raw in lx.CLAUSE_BREAKERS:
                return False
            if raw in lx.NEGATORS:
                return True
            seen += 1
            i -= 1
        return False

    # -- inconsistencias -------------------------------------------------------

    def _inconsistencies(self, matches: Sequence[KeywordMatch], tokens: list[tuple[str, str, bool]],
                         claim_type: ClaimType | None) -> list[Inconsistency]:
        found: list[Inconsistency] = []
        negated = [m for m in matches if m.negated]
        affirmed = [m for m in matches if not m.negated]

        def terms(items: Iterable[KeywordMatch]) -> tuple[str, ...]:
            return tuple(dict.fromkeys(m.matched for m in items))

        def add(code: str, evidence: tuple[str, ...]) -> None:
            found.append(Inconsistency(code, INCONSISTENCY_ES[code], evidence))

        # 1) "sin daños" pero describe destrucción o fuego
        damage_denied = [m for m in negated if m.category in (lx.GENERIC_DAMAGE, lx.MINOR_DAMAGE, lx.SEVERE_DAMAGE)]
        severe = [m for m in affirmed if m.category in (lx.SEVERE_DAMAGE, lx.FIRE)]
        if damage_denied and severe:
            add("DAMAGE_DENIED_BUT_SEVERE", terms(damage_denied) + terms(severe))

        # 2) "sin heridos" pero hay ambulancia / hospitalización / fallecidos
        injury_denied = [m for m in negated if m.category == lx.INJURY]
        injury_evidence = [m for m in affirmed
                           if m.category in (lx.INJURY, lx.FATALITY, lx.EMERGENCY, lx.MEDICAL_CARE)]
        if injury_denied and injury_evidence:
            add("INJURY_DENIED_BUT_EVIDENCE", terms(injury_denied) + terms(injury_evidence))

        # 3) daño leve y destrucción total a la vez
        minor = [m for m in affirmed if m.category == lx.MINOR_DAMAGE]
        destroyed = [m for m in affirmed if m.category == lx.SEVERE_DAMAGE]
        if minor and destroyed:
            add("SEVERITY_CONTRADICTION", terms(minor) + terms(destroyed))

        # 4) el tipo declarado no corresponde al relato
        #
        # v1 exigía CERO términos del tipo declarado, y se le escapaba
        # "choque del carro contra un andén saliendo del garaje" declarado como HOGAR:
        # la palabra "garaje" bastaba para considerarlo coherente. v2 compara cuál
        # vocabulario domina, no si el propio está presente. Medido en eval/: la
        # detección de inconsistencias subió de 80 % a 100 % sin falsos positivos nuevos.
        if claim_type is not None:
            keys = {key for _, key, is_punct in tokens if not is_punct}
            own = keys & self._domain[claim_type]
            for other_type, vocabulary in self._domain.items():
                if other_type is claim_type:
                    continue
                hits = keys & vocabulary
                if len(hits) >= 2 and len(hits) > len(own):
                    add("CLAIM_TYPE_MISMATCH", tuple(sorted(hits)))
                    break
        return found

    # -- decisión --------------------------------------------------------------

    def _recommend(self, urgency: UrgencyLevel, evidence: bool, inconsistent: bool) -> str:
        if urgency is UrgencyLevel.CRITICAL:
            return ASSIGN_AGENT_IMMEDIATELY   # la seguridad de las personas primero, siempre
        if inconsistent:
            return MANUAL_REVIEW
        if urgency is UrgencyLevel.HIGH:
            return HUMAN_VALIDATION_2H
        if not evidence:
            return MANUAL_REVIEW              # relato sin términos reconocibles
        return AUTO_APPROVE if self.auto_approve_low else FAST_TRACK_REVIEW


_DEFAULT = UrgencyClassifier()


def classify(description: str, claim_type: ClaimType | str | None = None) -> Assessment:
    """Atajo con la instancia compartida del proceso."""
    return _DEFAULT.classify(description, claim_type)
