from __future__ import annotations

import re
from typing import Any

LANGUAGE_NAMES = {"en": "English", "fa": "Farsi", "es": "Spanish", "ar": "Arabic"}
LANGUAGE_ALIASES = {
    "en": "en", "english": "en", "fa": "fa", "farsi": "fa", "persian": "fa",
    "es": "es", "spanish": "es", "español": "es", "espanol": "es",
    "ar": "ar", "arabic": "ar", "العربية": "ar", "فارسی": "fa", "پارسی": "fa",
}
WORK_ARRANGEMENTS = {"remote", "hybrid", "in_person", "other"}
MOBILITY_SUPPORT = {"relocation", "visa_sponsorship"}


def normalize_language(value: str, *, allow_job: bool = False) -> str:
    normalized = str(value or "").strip().lower().replace(" ", "_")
    if allow_job and normalized in {"job", "job_language", "posting_language"}:
        return "job"
    code = LANGUAGE_ALIASES.get(normalized)
    if not code:
        choices = ", ".join(LANGUAGE_NAMES)
        raise ValueError(f"Language must be one of: {choices}" + (", or job" if allow_job else ""))
    return code


def normalize_work_arrangements(values: list[str] | None) -> list[str]:
    aliases = {
        "remote": "remote", "fully remote": "remote", "remoto": "remote", "remota": "remote", "trabajo remoto": "remote", "hybrid": "hybrid", "híbrido": "hybrid", "hibrido": "hybrid",
        "in_person": "in_person", "in-person": "in_person", "in person": "in_person", "on site": "in_person",
        "onsite": "in_person", "on-site": "in_person", "office": "in_person", "presencial": "in_person",
        "حضوري": "in_person", "حضوری": "in_person", "دورکاری": "remote", "از راه دور": "remote", "عن بعد": "remote",
        "هجين": "hybrid", "هیبرید": "hybrid", "ترکیبی": "hybrid", "híbrido": "hybrid", "hibrido": "hybrid",
        "other": "other", "flexible": "other", "field": "other", "any": "", "no preference": "",
    }
    out = []
    for value in values or []:
        key = str(value).strip().lower().replace(chr(0x200c), "")
        if key not in aliases:
            raise ValueError("work_arrangements items must be remote, hybrid, in_person, or other")
        canonical = aliases[key]
        if canonical and canonical not in out:
            out.append(canonical)
    return out


def normalize_mobility_support(values: list[str] | None) -> list[str]:
    aliases = {
        "relocation": "relocation", "relocation available": "relocation", "reubicación": "relocation", "reubicacion": "relocation",
        "دعم الانتقال": "relocation", "حمایت جابهجایی": "relocation", "جابجایی": "relocation",
        "visa": "visa_sponsorship", "sponsorship": "visa_sponsorship",
        "visa sponsorship": "visa_sponsorship", "visa_sponsorship": "visa_sponsorship",
        "patrocinio de visa": "visa_sponsorship", "رعاية التأشيرة": "visa_sponsorship", "حمایت ویزا": "visa_sponsorship",
        "work visa": "visa_sponsorship",
    }
    out = []
    for value in values or []:
        key = str(value).strip().lower().replace(chr(0x200c), "")
        if key not in aliases:
            raise ValueError("mobility_support items must be relocation or visa_sponsorship")
        canonical = aliases[key]
        if canonical not in out:
            out.append(canonical)
    return out


def effective_preferences(profile: dict[str, Any]) -> tuple[list[str], list[str]]:
    arrangements = normalize_work_arrangements(profile.get("work_arrangements", []))
    mobility = normalize_mobility_support(profile.get("mobility_support", []))
    # Keep old profiles working while moving new profiles to clearer fields.
    legacy_modes, legacy_mobility = [], []
    for value in profile.get("remote_preferences", []):
        key = str(value).strip().lower().replace(chr(0x200c), "")
        if key in {"relocation", "relocation available", "visa", "sponsorship", "visa sponsorship"}:
            legacy_mobility.append(value)
        else:
            legacy_modes.append(value)
    arrangements = list(dict.fromkeys([*arrangements, *normalize_work_arrangements(legacy_modes)]))
    mobility = list(dict.fromkeys([*mobility, *normalize_mobility_support(legacy_mobility)]))
    return arrangements, mobility


def infer_work_arrangement(job: dict[str, Any]) -> str:
    explicit = str(job.get("remote", "unknown") or "unknown").strip().lower()
    explicit_aliases = {
        "remote": "remote", "fully remote": "remote", "true": "remote",
        "hybrid": "hybrid", "in_person": "in_person", "in-person": "in_person",
        "in person": "in_person", "onsite": "in_person", "on-site": "in_person",
        "on site": "in_person", "office": "in_person", "office-based": "in_person",
        "other": "other", "flexible": "other", "field-based": "other",
    }
    if explicit in explicit_aliases:
        return explicit_aliases[explicit]
    text = " ".join(str(job.get(k, "")) for k in ("title", "location", "description")).lower().replace(chr(0x200c), "")
    if re.search(r"\bhybrid\b|híbrido|hibrido|نظام هجين|هجين|ترکیبی", text):
        return "hybrid"
    if re.search(r"\b(on.site|onsite|in.person|office.based|presencial)\b|حضوري|في الموقع|حضوری", text):
        return "in_person"
    if re.search(r"\b(remote|fully remote|work from anywhere|telework|teletrabajo|remoto|remota)\b|عن بعد|عن بُعد|دورکاری|از راه دور", text):
        return "remote"
    if re.search(r"\b(field.based|field work|flexible location|work from office or home)\b|مرن الموقع|موقع مرن|محل کار منعطف", text):
        return "other"
    return "unknown"


def infer_mobility_support(job: dict[str, Any]) -> list[str]:
    text = " ".join(str(job.get(k, "")) for k in ("title", "description")).lower().replace(chr(0x200c), "")
    result = []
    if re.search(r"\b(relocation (?:assistance|support|package|provided|available|offered)|relocation offered)\b|ayuda de reubicación|apoyo para reubicación|دعم الانتقال|مساعدة في الانتقال|حمایت جابه?جایی|کمک هزینه جابه?جایی", text):
        result.append("relocation")
    if re.search(r"\b(visa sponsorship|sponsor(?:ship)? (?:a )?work visa|work visa sponsorship)\b|patrocinio de (?:visa|visado)|patrocinio de visa|رعاية التأشيرة|كفالة تأشيرة|حمایت ویزا|اسپانسر ویزا", text):
        result.append("visa_sponsorship")
    return result


def detect_language(text: str) -> str:
    sample = str(text or "")[:12000]
    if re.search(r"[پچژگک‌ی]", sample):
        return "fa"
    if re.search(r"[؀-ۿ]", sample):
        return "ar"
    spanish_markers = r"\b(el|la|los|las|para|con|experiencia|trabajo|empresa|datos|producto|responsabilidades)\b|[áéíóúñ¿¡]"
    if re.search(spanish_markers, sample, re.I):
        return "es"
    return "en"
