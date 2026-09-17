"""Utilidades para normalizar y resolver nombres de calles de Rosario contra
el callejero descargado de la API georef (data/rosario_calles.json)."""
import json
import re
import unicodedata
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent / "data"

CATEGORY_PREFIXES = ["AV ", "BV ", "PJE ", "CALLE "]

# prefijos de categoría tal como aparecen escritos en los cuadros horarios
# (con variantes abreviadas/acentuadas) que hay que descartar del token de
# búsqueda antes de matchear contra el callejero, que ya los tiene removidos
TOKEN_PREFIX_PATTERNS = [
    r"^AV\s+", r"^AVDA\s+", r"^BV\s+", r"^BVAR\s+", r"^BLVD\s+",
    r"^PJE\s+", r"^PASAJE\s+", r"^CALLE\s+",
]


def strip_token_prefix(tok_norm: str) -> str:
    for pat in TOKEN_PREFIX_PATTERNS:
        nuevo = re.sub(pat, "", tok_norm)
        if nuevo != tok_norm:
            return nuevo
    return tok_norm

# abreviaturas de palabras comunes en nombres de calle argentinos que no son
# un prefijo literal de la palabra completa (p.ej. "Sta." de "Santa")
WORD_ABBREVIATIONS = {
    "SANTA": "STA",
    "SANTO": "STO",
    "GENERAL": "GRAL",
    "PRESIDENTE": "PDTE",
    "CORONEL": "CNEL",
    "COMANDANTE": "CMTE",
    "DOCTOR": "DR",
    "INGENIERO": "ING",
    "TENIENTE": "TTE",
}


def normalize(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return s.upper().strip()


def strip_category_prefix(name: str) -> str:
    for p in CATEGORY_PREFIXES:
        if name.startswith(p):
            return name[len(p):]
    return name


def strip_variant_suffix(name: str) -> str:
    return re.sub(r"\s+(BIS|[A-Z])$", "", name).strip()


class CalleIndex:
    """Índice de calles de Rosario para resolver abreviaturas por prefijo."""

    def __init__(self, calles_json_path=None):
        path = Path(calles_json_path) if calles_json_path else DATA_DIR / "rosario_calles.json"
        raw = json.loads(path.read_text(encoding="utf-8"))
        # base_norm -> set de nombres originales (con prefijo AV/BV/etc, tal
        # como los devuelve georef) que colapsan a esa misma base
        self.base_to_originals = {}
        for c in raw:
            original = c["nombre"]
            base = strip_variant_suffix(normalize(strip_category_prefix(original)))
            self.base_to_originals.setdefault(base, set()).add(original)
        self.bases = sorted(self.base_to_originals.keys())

    def resolve_token(self, token: str):
        """Devuelve lista de bases candidatas cuyo nombre empieza con el
        token normalizado. Ordena las más cortas primero (mejor match)."""
        tok = normalize(token.replace(".", "").strip())
        tok = strip_token_prefix(tok)
        if not tok:
            return []
        candidates = [b for b in self.bases if b.startswith(tok)]
        candidates.sort(key=len)
        return candidates

    def resolve_token_multiword(self, token: str):
        """Para nombres de dos palabras (ej. 'SAN LORENZO', 'SANTA FE',
        'ENTRE RIOS'), intenta reconstruir la abreviatura como
        prefijo(palabra1) + prefijo(palabra2), p.ej. 'SLORE' = S + LORE."""
        tok = normalize(token.replace(".", "").strip())
        tok = strip_token_prefix(tok)
        if not tok:
            return []
        found = set()
        for b in self.bases:
            if " " not in b:
                continue
            w1, w2 = b.split(" ", 1)
            if " " in w2:
                continue  # solo nombres de exactamente 2 palabras
            w1_forms = {w1[:i] for i in range(1, len(w1) + 1)}
            if w1 in WORD_ABBREVIATIONS:
                w1_forms.add(WORD_ABBREVIATIONS[w1])
            for w1_short in w1_forms:
                if not tok.startswith(w1_short):
                    continue
                j = len(tok) - len(w1_short)
                if 1 <= j <= len(w2) and w2[:j] == tok[len(w1_short):]:
                    found.add(b)
                    break
        return sorted(found, key=len)

    def best_original_name(self, base: str) -> str:
        """Elige un nombre 'representativo' (con prefijo AV/BV si existe)
        entre los originales que colapsan a esa base."""
        originals = self.base_to_originals[base]
        # preferir el que tenga prefijo de avenida/boulevard, si existe
        for o in originals:
            if o.startswith("AV ") or o.startswith("BV "):
                return o
        return sorted(originals, key=len)[0]
