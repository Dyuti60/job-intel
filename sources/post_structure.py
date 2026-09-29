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


_WHITESPACE_VACANCY_HEADER = re.compile(
    r"\bname\s+of\s+(?:the\s+)?posts?\b.*?\b(?:minimum\s+)?educational\s+qualification\b"
    r".*?\bscale\s+of\s+pay\b.*?\btotal\s+(?:no[.,]?\s+of\s+)?vacant\s+"
    r"(?:posts?|dost|oost)\b",
    re.I,
)
_QUALIFICATION_START = re.compile(
    r"^(?:b\.?\s*sc\.?|m\.?\s*sc\.?|hsslc|hslc|mbbs|bachelor|master|graduate|"
    r"post[- ]?graduate|diploma|certificate|iti\b|degree\b|class\s+[ivx]+\b|passed\b)",
    re.I,
)
_QUALIFICATION_INLINE = re.compile(_QUALIFICATION_START.pattern.removeprefix("^"), re.I)
_PAY_RANGE = re.compile(r"\b\d{1,2}[,.]?\d{3}\s*[-–]\s*\d{1,2}[,.]?\d{3}\b")
_VACANCY_COUNT_LINE = re.compile(r"^\s*(\d{1,5})(?:\s+(?:nos?\.?|[A-Za-z]))", re.I)
_SERIAL_ROW = re.compile(r"^\s*(?P<serial>[0-9Il]{1,3})[.)]?\s+(?P<title>\S.+?)\s*$")


def parse_whitespace_vacancy_table(
    raw_text: str, title: str = "",
) -> tuple[
    tuple[ParsedPost, ...],
    AdvertisementSplitStatus,
    str | None,
    tuple[str, ...],
]:
    """Parse bounded pypdf rows whose columns survived but pipe separators did not."""
    lines = [_clean_text(line) for line in raw_text.replace("\r\n", "\n").split("\n")]
    header_index = next(
        (
            index
            for index in range(len(lines))
            if _WHITESPACE_VACANCY_HEADER.search(" ".join(lines[index : index + 8]))
        ),
        None,
    )
    if header_index is None:
        return (), AdvertisementSplitStatus.LEGACY_UNSPLIT, None, ()

    parsed: list[ParsedPost] = []
    seen_keys: set[str] = set()
    expected_serial = 1
    errors: list[str] = []
    scan_end = min(len(lines), header_index + 402)
    index = header_index + 1
    while index < scan_end:
        match = _SERIAL_ROW.match(lines[index])
        if match is None:
            index += 1
            continue
        serial_text = match.group("serial").translate(str.maketrans({"I": "1", "l": "1"}))
        serial = int(serial_text)
        if serial < expected_serial:
            index += 1
            continue
        if serial > expected_serial:
            errors.append(f"Vacancy table skipped serial {expected_serial}")
            break

        initial_title = match.group("title")
        inline_qualification = _QUALIFICATION_INLINE.search(initial_title)
        title_lines = [
            initial_title[: inline_qualification.start()]
            if inline_qualification is not None
            else initial_title
        ]
        qualification_index = index if inline_qualification is not None else None
        for offset in range(1, 8):
            if qualification_index is not None:
                break
            candidate_index = index + offset
            if candidate_index >= scan_end:
                break
            candidate = lines[candidate_index]
            if _QUALIFICATION_START.match(candidate):
                qualification_index = candidate_index
                break
            if not candidate or _SERIAL_ROW.match(candidate):
                break
            title_lines.append(candidate)
        if qualification_index is None:
            index += 1
            continue

        name = _clean_post_title(" ".join(title_lines)).strip(" ,-:")
        if not name or len(name) > 180 or re.search(r"[.;]", name):
            errors.append(f"Vacancy row {serial} has an unsupported Post title")
            break
        row_end = min(scan_end, qualification_index + 25)
        for candidate_index in range(qualification_index + 1, row_end):
            next_row = _SERIAL_ROW.match(lines[candidate_index])
            if next_row is None:
                continue
            next_serial = int(
                next_row.group("serial").translate(str.maketrans({"I": "1", "l": "1"}))
            )
            if next_serial == serial + 1:
                row_end = candidate_index
                break
        pay_index = next(
            (
                candidate_index
                for candidate_index in range(qualification_index, row_end)
                if _PAY_RANGE.search(lines[candidate_index])
            ),
            None,
        )
        if pay_index is None:
            errors.append(f"Vacancy row {serial} has no deterministic pay/total boundary")
            break
        count_match = next(
            (
                (candidate_index, count)
                for candidate_index in range(pay_index + 1, min(scan_end, pay_index + 6))
                if (count := _VACANCY_COUNT_LINE.match(lines[candidate_index]))
            ),
            None,
        )
        if count_match is None:
            errors.append(f"Vacancy row {serial} has no deterministic total")
            break
        count_index, count = count_match
        total = int(count.group(1))
        post_key = _stable_post_key(name, "")
        if total < 1 or post_key in seen_keys:
            errors.append(f"Vacancy row {serial} has an invalid total or duplicate Post")
            break
        seen_keys.add(post_key)
        excerpt = "\n".join(lines[index : count_index + 1])[:8000]
        locator = f"pdf:whitespace-vacancies;row={serial}"
        parsed.append(
            ParsedPost(
                post_key=post_key,
                ordinal=len(parsed) + 1,
                name=name,
                normalized_name=" ".join(name.casefold().split()),
                source_locator=locator,
                facts=(
                    ParsedField(
                        "name",
                        CandidateValueType.STRING,
                        name,
                        name,
                        f"{locator};column=post",
                        excerpt,
                    ),
                    ParsedField(
                        "vacancies.total",
                        CandidateValueType.INTEGER,
                        total,
                        count.group(1),
                        f"{locator};column=total",
                        excerpt,
                    ),
                ),
            )
        )
        expected_serial += 1
        index = count_index + 1

    if errors or not parsed:
        note = "; ".join(errors)[:4000] or (
            "Whitespace vacancy table was found but no deterministic Post rows followed."
        )
        return (), AdvertisementSplitStatus.AMBIGUOUS, note, tuple(errors or [note])
    return (
        canonicalize_posts(_prefer_listing_post_names(title, tuple(parsed))),
        AdvertisementSplitStatus.EXPLICIT,
        f"Deterministically parsed {len(parsed)} Posts from a whitespace vacancy table.",
        (),
    )


def _clean_post_title(value: str) -> str:
    return _clean_text(re.sub(r"(?<=[a-z])(?=[A-Z])", " ", value))


def _prefer_listing_post_names(
    title: str, posts: tuple[ParsedPost, ...]
) -> tuple[ParsedPost, ...]:
    listing = re.sub(
        r"^\s*(?:advertisement|advt\.?|recruitment\s+notice)\s*[-:]?\s*",
        "",
        _clean_text(title),
        flags=re.I,
    )
    names = [_clean_post_title(value).strip(" ,-:") for value in re.split(r"\s+&\s+", listing)]
    if len(names) != len(posts) or len(names) < 2:
        return posts
    listing_token_sets = [set(re.findall(r"[a-z0-9]+", name.casefold())) for name in names]
    parsed_token_sets = [
        set(re.findall(r"[a-z0-9]+", post.name.casefold())) for post in posts
    ]
    for index, (listing_tokens, parsed_tokens) in enumerate(
        zip(listing_token_sets, parsed_token_sets, strict=True)
    ):
        overlap = len(listing_tokens & parsed_tokens)
        competing = max(
            (
                len(other_listing & parsed_tokens)
                for other_index, other_listing in enumerate(listing_token_sets)
                if other_index != index
            ),
            default=0,
        )
        if not listing_tokens or not parsed_tokens or overlap == 0 or overlap <= competing:
            return posts
    result: list[ParsedPost] = []
    for name, post in zip(names, posts, strict=True):
        facts = tuple(
            replace(
                fact,
                value=name,
                raw_value=name,
                source_locator=f"listing:title;post={post.ordinal}",
                excerpt=_clean_text(title)[:8000],
            )
            if fact.field_path == "name"
            else fact
            for fact in post.facts
        )
        result.append(
            replace(
                post,
                post_key=_stable_post_key(name, ""),
                name=name,
                normalized_name=" ".join(name.casefold().split()),
                facts=facts,
            )
        )
    if len({post.post_key for post in result}) != len(result):
        return posts
    return tuple(result)


_POSITION_TABLE_HEADER = re.compile(r"\bposition\s+essential\s+qualification\b", re.I)
_POSITION_COUNT = re.compile(
    r"^\(?\s*(?P<total>\d{1,5})\s*(?:nos?\.?|posts?)\s*\)?$", re.I
)


def parse_numbered_position_table(
    raw_text: str,
) -> tuple[
    tuple[ParsedPost, ...],
    AdvertisementSplitStatus,
    str | None,
    tuple[str, ...],
]:
    """Parse bounded numbered position headings with an explicit parenthetical count."""
    lines = [_clean_text(line) for line in raw_text.replace("\r\n", "\n").split("\n")]
    header_index = next(
        (
            index
            for index in range(len(lines))
            if _POSITION_TABLE_HEADER.search(" ".join(lines[index : index + 4]))
        ),
        None,
    )
    if header_index is None:
        return (), AdvertisementSplitStatus.LEGACY_UNSPLIT, None, ()

    parsed: list[ParsedPost] = []
    seen_keys: set[str] = set()
    for index in range(header_index + 1, min(len(lines), header_index + 252)):
        row = _SERIAL_ROW.match(lines[index])
        if row is None:
            continue
        title_lines = [row.group("title")]
        count_match = None
        count_index = None
        for candidate_index in range(index + 1, min(len(lines), index + 8)):
            candidate = lines[candidate_index]
            if count := _POSITION_COUNT.fullmatch(candidate):
                count_match = count
                count_index = candidate_index
                break
            if not candidate or _SERIAL_ROW.match(candidate) or re.search(r"[.;:]$", candidate):
                break
            title_lines.append(candidate)
        if count_match is None or count_index is None:
            continue
        name = _clean_text(" ".join(title_lines)).strip(" ,-:")
        if not name or len(name) > 160 or re.search(r"[.;:]", name):
            continue
        post_key = _stable_post_key(name, "")
        if post_key in seen_keys:
            note = "Numbered position table contains a duplicate Post identity."
            return (), AdvertisementSplitStatus.AMBIGUOUS, note, (note,)
        seen_keys.add(post_key)
        total = int(count_match.group("total"))
        if total < 1:
            continue
        locator = f"pdf:numbered-positions;row={len(parsed) + 1}"
        excerpt = "\n".join(lines[index : count_index + 1])[:8000]
        parsed.append(
            ParsedPost(
                post_key=post_key,
                ordinal=len(parsed) + 1,
                name=name,
                normalized_name=" ".join(name.casefold().split()),
                source_locator=locator,
                facts=(
                    ParsedField(
                        "name",
                        CandidateValueType.STRING,
                        name,
                        name,
                        f"{locator};field=post",
                        excerpt,
                    ),
                    ParsedField(
                        "vacancies.total",
                        CandidateValueType.INTEGER,
                        total,
                        count_match.group("total"),
                        f"{locator};field=total",
                        excerpt,
                    ),
                ),
            )
        )
    if not parsed:
        note = "Numbered position table was found but no explicit Post/count rows followed."
        return (), AdvertisementSplitStatus.AMBIGUOUS, note, (note,)
    return (
        canonicalize_posts(tuple(parsed)),
        AdvertisementSplitStatus.EXPLICIT,
        f"Deterministically parsed {len(parsed)} Posts from numbered position rows.",
        (),
    )


_SINGLE_POST_TITLE = re.compile(
    r"^\s*(?:advertisement|advt\.?)\s+for\s+the\s+post\s+of\s+(?P<name>.+?)\s*$",
    re.I,
)


def parse_explicit_single_post(
    title: str, raw_text: str
) -> tuple[
    tuple[ParsedPost, ...],
    AdvertisementSplitStatus,
    str | None,
    tuple[str, ...],
]:
    """Create one Post only for an official title that explicitly says 'the post of'."""
    match = _SINGLE_POST_TITLE.match(_clean_text(title))
    if match is None:
        return (), AdvertisementSplitStatus.LEGACY_UNSPLIT, None, ()
    if re.search(r"\bfollowing\b.{0,80}\bposts?\b", _clean_text(raw_text[:8000]), re.I):
        note = "Single-Post title conflicts with a multi-Post advertisement body."
        return (), AdvertisementSplitStatus.AMBIGUOUS, note, (note,)
    name = _clean_text(match.group("name")).strip(" ,-:")
    if not name or len(name) > 240 or re.search(r"[.;:]", name):
        return (), AdvertisementSplitStatus.LEGACY_UNSPLIT, None, ()
    locator = "listing:title=explicit-single-post"
    post = ParsedPost(
        post_key=_stable_post_key(name, ""),
        ordinal=1,
        name=name,
        normalized_name=" ".join(name.casefold().split()),
        source_locator=locator,
        facts=(
            ParsedField(
                "name",
                CandidateValueType.STRING,
                name,
                match.group("name"),
                locator,
                _clean_text(title)[:8000],
            ),
        ),
    )
    return (
        canonicalize_posts((post,)),
        AdvertisementSplitStatus.EXPLICIT,
        "Deterministically parsed one Post from an explicit single-Post title.",
        (),
    )


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
    if status == AdvertisementSplitStatus.LEGACY_UNSPLIT:
        posts, status, note, warnings = parse_whitespace_vacancy_table(text, title)
    if status == AdvertisementSplitStatus.LEGACY_UNSPLIT:
        posts, status, note, warnings = parse_numbered_position_table(text)
    if status == AdvertisementSplitStatus.LEGACY_UNSPLIT:
        posts, status, note, warnings = parse_explicit_single_post(title, text)
    return canonicalize_posts(posts), status, note, warnings
