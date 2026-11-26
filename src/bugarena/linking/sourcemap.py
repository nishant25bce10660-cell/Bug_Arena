"""VLQ Source Map parser and site <-> local project finding linker (Section 11)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from bugarena.sandbox.security import SecurityViolationError, validate_safe_path

_B64_CHARS = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"
_B64_MAP = {ch: idx for idx, ch in enumerate(_B64_CHARS)}


def decode_vlq_segment(segment: str) -> list[int]:
    """Decode one Base64 VLQ segment into signed integers."""
    values: list[int] = []
    shift = 0
    result = 0
    for ch in segment:
        digit = _B64_MAP.get(ch)
        if digit is None:
            raise ValueError(f"Invalid VLQ Base64 character: {ch!r}")
        continuation = digit & 32
        result += (digit & 31) << shift
        if continuation:
            shift += 5
        else:
            is_neg = (result & 1) == 1
            val = -(result >> 1) if is_neg else (result >> 1)
            values.append(val)
            result = 0
            shift = 0
    return values


def resolve_source_location(
    source_map: dict[str, Any],
    *,
    gen_line: int,
    gen_col: int = 0,
) -> dict[str, Any] | None:
    """Resolve 1-based generated JS line/col to original source file & 1-based line/col."""
    sources = source_map.get("sources") or []
    mappings = str(source_map.get("mappings") or "")
    if not sources or not mappings or gen_line < 1:
        return None

    source_idx = 0
    orig_line = 0
    orig_col = 0
    best: dict[str, Any] | None = None

    for cur_line_idx, line_str in enumerate(mappings.split(";"), 1):
        gen_col_acc = 0
        for seg in line_str.split(","):
            if not seg:
                continue
            nums = decode_vlq_segment(seg)
            if not nums:
                continue
            gen_col_acc += nums[0]
            if len(nums) >= 4:
                source_idx += nums[1]
                orig_line += nums[2]
                orig_col += nums[3]
                if (
                    cur_line_idx == gen_line
                    and (best is None or gen_col_acc <= gen_col)
                    and 0 <= source_idx < len(sources)
                ):
                        best = {
                            "source": str(sources[source_idx]),
                            "line": orig_line + 1,
                            "col": orig_col,
                        }
        if cur_line_idx == gen_line:
            return best
    return best


def link_site_and_project_findings(
    *,
    site_findings: list[dict[str, Any]],
    project_findings: list[dict[str, Any]],
    source_maps: dict[str, dict[str, Any]],
    project_path: Path | str | None = None,
) -> list[dict[str, Any]]:
    """
    Combine site and project findings, resolving source maps to local project files and
    marking each item linkage_status = 'linked' | 'site_only' | 'project_only'.
    """
    proj_root = Path(project_path).resolve() if project_path else None
    merged: list[dict[str, Any]] = []

    for sf in site_findings:
        item = dict(sf)
        where = dict(item.get("where_found") or {})
        script_url = str(where.get("script_url") or "")
        line_num = where.get("line")
        col_num = int(where.get("col") or 0)
        linked = False

        if script_url and script_url in source_maps and isinstance(line_num, int) and line_num >= 1:
            resolved = resolve_source_location(source_maps[script_url], gen_line=line_num, gen_col=col_num)
            if resolved:
                rel_src = resolved["source"].lstrip("./").lstrip("/")
                if proj_root is None:
                    where["project_file"] = rel_src
                    where["project_line"] = resolved["line"]
                    linked = True
                else:
                    try:
                        candidate = validate_safe_path(proj_root, rel_src)
                        if candidate.is_file():
                            where["project_file"] = candidate.relative_to(proj_root).as_posix()
                            where["project_line"] = resolved["line"]
                            linked = True
                    except (SecurityViolationError, ValueError):
                        linked = False

        item["where_found"] = where
        item["linkage_status"] = "linked" if linked else "site_only"
        merged.append(item)

    for pf in project_findings:
        p_item = dict(pf)
        p_item.setdefault("linkage_status", "project_only")
        merged.append(p_item)

    return merged
