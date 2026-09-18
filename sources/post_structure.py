"""Shared bounded vacancy grammar; authority-specific rich sections stay in adapters."""

import re
from dataclasses import replace

from app.models.candidates import AdvertisementSplitStatus, CandidateValueType
from app.services.post_identity import canonical_post_name
from app.services.post_identity import stable_post_key as _stable_post_key
from sources.extraction import ParsedField, ParsedPost


def _clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


_VACANCY_HEADERS = {
    "post": "post_name",
    "postname": "post_name",
    "nameofpost": "post_name",
    "nameofthepost": "post_name",
    "department": "department",
    "dept": "department",
    "organisation": "organisation",
    "organization": "organisation",
    "unitorganisation": "organisation",
    "unitorganization": "organisation",
    "ur": "vacancies.ur",
    "unreserved": "vacancies.ur",
    "obcmobc": "vacancies.obc_mobc",
    "obc": "vacancies.obc_mobc",
    "sc": "vacancies.sc",
    "stp": "vacancies.st_p",
    "sth": "vacancies.st_h",
    "ews": "vacancies.ews",
    "pwbd": "vacancies.pwbd",
    "pwd": "vacancies.pwbd",
    "women": "vacancies.women",
    "total": "vacancies.total",
    "totalposts": "vacancies.total",
    "noofposts": "vacancies.total",
    "numberofposts": "vacancies.total",
}


def _table_cells(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _header_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.casefold())


def _separator_row(cells: list[str]) -> bool:
    return bool(cells) and all(re.fullmatch(r"[-: ]+", cell) for cell in cells)


def parse_vacancy_table(
    raw_text: str,
) -> tuple[
    tuple[ParsedPost, ...],
    AdvertisementSplitStatus,
    str | None,
    tuple[str, ...],
]:
    """Parse a bounded pipe-delimited vacancy table or retain explicit ambiguity."""
    lines = [line.strip() for line in raw_text.replace("\r\n", "\n").split("\n")]
    candidates: list[tuple[int, list[str], dict[int, str]]] = []
    for index, line in enumerate(lines):
        if "|" not in line:
            continue
        cells = _table_cells(line)
        mapped = {
            cell_index: _VACANCY_HEADERS[key]
            for cell_index, cell in enumerate(cells)
            if (key := _header_key(cell)) in _VACANCY_HEADERS
        }
        if "post_name" in mapped.values() and "vacancies.total" in mapped.values():
            candidates.append((index, cells, mapped))
    if not candidates:
        return (), AdvertisementSplitStatus.LEGACY_UNSPLIT, None, ()
    if len(candidates) != 1:
        note = "Multiple vacancy tables matched; post ownership requires Human Review."
        return (), AdvertisementSplitStatus.AMBIGUOUS, note, (note,)

    header_index, headers, mapped = candidates[0]
    rows: list[list[str]] = []
    for line in lines[header_index + 1 : header_index + 102]:
        if not line:
            if rows:
                break
            continue
        if "|" not in line:
            if rows:
                break
            continue
        cells = _table_cells(line)
        if _separator_row(cells):
            continue
        rows.append(cells)
    if not rows:
        note = "Vacancy table header was found but no deterministic post rows followed."
        return (), AdvertisementSplitStatus.AMBIGUOUS, note, (note,)

    parsed: list[ParsedPost] = []
    seen_keys: set[str] = set()
    errors: list[str] = []
    for row_number, cells in enumerate(rows, start=1):
        if len(cells) != len(headers):
            errors.append(
                f"Vacancy row {row_number} has {len(cells)} cells; expected {len(headers)}"
            )
            continue
        values = {meaning: cells[column] for column, meaning in mapped.items()}
        name = _clean_text(values.get("post_name", ""))
        total_text = values.get("vacancies.total", "")
        if not name or not re.fullmatch(r"\d+", total_text.strip()):
            errors.append(f"Vacancy row {row_number} has an unsupported post name or total")
            continue
        primary_categories = (
            "vacancies.ur",
            "vacancies.obc_mobc",
            "vacancies.sc",
            "vacancies.st_p",
            "vacancies.st_h",
            "vacancies.ews",
        )
        if all(key in values for key in primary_categories) and all(
            re.fullmatch(r"\d+", values[key].strip()) for key in primary_categories
        ):
            category_total = sum(int(values[key]) for key in primary_categories)
            if category_total != int(total_text):
                errors.append(
                    f"Vacancy row {row_number} category total {category_total} "
                    f"does not match stated total {total_text}"
                )
                continue
        organisation = _clean_text(values.get("organisation", ""))
        department = _clean_text(values.get("department", ""))
        post_key = _stable_post_key(name, organisation or department)
        if post_key in seen_keys:
            errors.append(f"Vacancy row {row_number} duplicates stable post key {post_key}")
            continue
        seen_keys.add(post_key)
        row_excerpt = " | ".join(cells)[:8000]
        row_locator = f"pdf:table=vacancies;row={row_number}"
        facts = [
            ParsedField(
                "name",
                CandidateValueType.STRING,
                name,
                values["post_name"],
                f"{row_locator};column=post",
                row_excerpt,
            ),
            ParsedField(
                "vacancies.total",
                CandidateValueType.INTEGER,
                int(total_text),
                total_text,
                f"{row_locator};column=total",
                row_excerpt,
            ),
        ]
        for fact_key, value in sorted(values.items()):
            if fact_key in {"post_name", "vacancies.total"}:
                continue
            if fact_key == "organisation" and value.strip():
                facts.append(
                    ParsedField(
                        "organisation.name",
                        CandidateValueType.STRING,
                        _clean_text(value),
                        value,
                        f"{row_locator};column=organisation",
                        row_excerpt,
                    )
                )
            elif fact_key == "department" and value.strip():
                facts.append(
                    ParsedField(
                        "department.name",
                        CandidateValueType.STRING,
                        _clean_text(value),
                        value,
                        f"{row_locator};column=department",
                        row_excerpt,
                    )
                )
            elif fact_key.startswith("vacancies.") and re.fullmatch(r"\d+", value.strip()):
                facts.append(
                    ParsedField(
                        fact_key,
                        CandidateValueType.INTEGER,
                        int(value),
                        value,
                        f"{row_locator};column={fact_key.removeprefix('vacancies.')}",
                        row_excerpt,
                    )
                )
        parsed.append(
            ParsedPost(
                post_key=post_key,
                ordinal=row_number,
                name=name,
                normalized_name=" ".join(name.casefold().split()),
                source_locator=row_locator,
                facts=tuple(sorted(facts, key=lambda fact: fact.field_path)),
            )
        )
    if errors or len(parsed) != len(rows):
        note = "; ".join(errors)[:4000] or "Vacancy table could not be split safely."
        return (), AdvertisementSplitStatus.AMBIGUOUS, note, tuple(errors or [note])
    return (
        _qualify_duplicate_post_names(tuple(parsed)),
        AdvertisementSplitStatus.EXPLICIT,
        f"Deterministically parsed {len(parsed)} post rows from the vacancy table.",
        (),
    )


_NARRATIVE_MARKER = re.compile(r"\b(?P<total>[0-9][0-9,]*)\s+posts?\s+of\s+", re.I)
_NARRATIVE_ORGANISATION = re.compile(r"^(?P<name>.+?)\s+(?:in|under)\s+(?P<organisation>.+)$", re.I)
_NARRATIVE_SEPARATOR = re.compile(r"(?P<separator>,|&|\band\b)\s*$", re.I)


def parse_narrative_vacancies(
    title: str, raw_text: str
) -> tuple[
    tuple[ParsedPost, ...],
    AdvertisementSplitStatus,
    str | None,
    tuple[str, ...],
]:
    """Split bounded vacancy groups, including a shared trailing organization."""
    candidate = ""
    markers: list[re.Match[str]] = []
    for candidate in (_clean_text(title), _clean_text(raw_text[:8000])):
        candidate_markers = list(_NARRATIVE_MARKER.finditer(candidate))
        if len(candidate_markers) >= 1:
            markers = candidate_markers
            break
    if not markers:
        return (), AdvertisementSplitStatus.LEGACY_UNSPLIT, None, ()

    grouped: list[tuple[re.Match[str], str, str, str, bool]] = []
    pending: list[tuple[re.Match[str], str]] = []
    group_start = markers[0].start()
    for index, marker in enumerate(markers):
        body_end = markers[index + 1].start() if index + 1 < len(markers) else len(candidate)
        body = candidate[marker.end() : body_end].strip()
        if index + 1 < len(markers):
            separator = _NARRATIVE_SEPARATOR.search(body)
            if separator is None:
                return _ambiguous_narrative()
            body = body[: separator.start()].strip()
            if re.search(r"[.;]", body):
                return _ambiguous_narrative()
        else:
            boundary = re.search(r"[.;]", body)
            if boundary is not None:
                body = body[: boundary.start()].strip()
        if not body or re.search(r"[,;]|\band\b", body, re.I):
            return _ambiguous_narrative()

        qualified = _NARRATIVE_ORGANISATION.match(body)
        if qualified is None:
            pending.append((marker, body.strip(" ,-:")))
            continue
        name = _clean_text(qualified.group("name")).strip(" ,-:")
        organisation = _clean_text(qualified.group("organisation")).strip(" ,-:")
        organisation = re.split(
            r"\s+in\s+the\s+Pay\s+Scale\b", organisation, maxsplit=1, flags=re.I
        )[0].strip()
        if not name or not organisation or re.search(r"[,;]", organisation):
            return _ambiguous_narrative()
        pending.append((marker, name))
        group_excerpt = candidate[group_start:body_end].strip(" ,&")[:8000]
        grouped_qualifier = len(pending) > 1
        grouped.extend(
            (
                pending_marker,
                pending_name,
                organisation,
                group_excerpt,
                grouped_qualifier,
            )
            for pending_marker, pending_name in pending
        )
        pending = []
        if index + 1 < len(markers):
            group_start = markers[index + 1].start()
    if pending or len(grouped) != len(markers):
        return _ambiguous_narrative()

    parsed: list[ParsedPost] = []
    seen_keys: set[str] = set()
    name_counts: dict[str, int] = {}
    for _marker, name, _organisation, _excerpt, _grouped_qualifier in grouped:
        normalized = " ".join(name.casefold().split())
        name_counts[normalized] = name_counts.get(normalized, 0) + 1
    for ordinal, (
        marker,
        base_name,
        organisation,
        excerpt,
        grouped_qualifier,
    ) in enumerate(grouped, start=1):
        normalized_name = " ".join(base_name.casefold().split())
        qualified_base_name = " ".join(
            word.capitalize() if word.islower() else word for word in base_name.split()
        )
        name = (
            f"{qualified_base_name} - {organisation}"
            if grouped_qualifier or name_counts[normalized_name] > 1
            else base_name
        )
        total = int(marker.group("total").replace(",", ""))
        post_key = _stable_post_key(base_name, organisation)
        if total < 1 or post_key in seen_keys:
            note = "Narrative vacancy series contains an invalid total or duplicate Post."
            return (), AdvertisementSplitStatus.AMBIGUOUS, note, (note,)
        seen_keys.add(post_key)
        locator = f"pdf:narrative-vacancies;item={ordinal}"
        parsed.append(
            ParsedPost(
                post_key=post_key,
                ordinal=ordinal,
                name=name,
                normalized_name=normalized_name,
                source_locator=locator,
                facts=(
                    ParsedField(
                        "name",
                        CandidateValueType.STRING,
                        name,
                        base_name,
                        f"{locator};field=post",
                        excerpt,
                    ),
                    ParsedField(
                        "organisation.name",
                        CandidateValueType.STRING,
                        organisation,
                        organisation,
                        f"{locator};field=organisation",
                        excerpt,
                    ),
                    ParsedField(
                        "vacancies.total",
                        CandidateValueType.INTEGER,
                        total,
                        marker.group("total"),
                        f"{locator};field=total",
                        excerpt,
                    ),
                ),
            )
        )
    posts = canonicalize_posts(tuple(parsed))
    return (
        posts,
        AdvertisementSplitStatus.EXPLICIT,
        f"Deterministically parsed {len(posts)} Posts from an explicit vacancy series.",
        (),
    )


def _ambiguous_narrative() -> tuple[
    tuple[ParsedPost, ...],
    AdvertisementSplitStatus,
    str,
    tuple[str, ...],
]:
    note = "Narrative vacancy series could not be split completely and safely."
    return (), AdvertisementSplitStatus.AMBIGUOUS, note, (note,)


def canonicalize_posts(posts: tuple[ParsedPost, ...]) -> tuple[ParsedPost, ...]:
    result = []
    for post in posts:
        organisation = next(
            (
                str(fact.value)
                for fact in post.facts
                if fact.field_path
                in {
                    "organisation.name",
                    "organization.name",
                    "organization.unit",
                    "department.name",
                }
            ),
            "",
        )
        name = canonical_post_name(post.name, organisation)
        facts = tuple(
            replace(fact, value=name) if fact.field_path == "name" else fact for fact in post.facts
        )
        result.append(replace(post, name=name, facts=facts))
    return tuple(result)


_qualify_duplicate_post_names = canonicalize_posts


def structure_posts(title: str, text: str):
    posts, status, note, warnings = parse_vacancy_table(text)
    if status == AdvertisementSplitStatus.LEGACY_UNSPLIT:
        posts, status, note, warnings = parse_narrative_vacancies(title, text)
    return canonicalize_posts(posts), status, note, warnings
