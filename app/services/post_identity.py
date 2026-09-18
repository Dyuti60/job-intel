"""One deterministic Post naming and identity contract, independent of templates."""

import hashlib
import re


def canonical_post_name(
    title: str, organisation: str = "", *, previous_organisation: str = ""
) -> str:
    title = " ".join(title.split()).strip(" .,:;")
    organisation = " ".join(organisation.split()).strip(" .,:;")
    for unit in (previous_organisation, organisation):
        for separator in (" - ", " – "):
            suffix = separator + unit
            if unit and title.casefold().endswith(suffix.casefold()):
                title = title[: -len(suffix)].strip()
                break
    return f"{title} – {organisation}" if organisation else title


def stable_post_key(title: str, organisation: str = "") -> str:
    # Keep the existing identity algorithm; display punctuation and row order are irrelevant.
    seed = " ".join(f"{title} {organisation}".split()).casefold()
    slug = re.sub(r"[^a-z0-9]+", "_", seed).strip("_") or "post"
    if len(slug) > 110:
        slug = f"{slug[:97].rstrip('_')}_{hashlib.sha256(seed.encode()).hexdigest()[:12]}"
    return slug
