#!/usr/bin/env python3
"""
xml2csv: Flatten XML files to CSV based on repeating child elements.

Behavior inferred from provided samples:
- For a given XML document, identify the first parent node in document order that has
  a repeated child tag (e.g., <a> containing multiple <b>). That repeated child
  tag defines the base row unit.
- For each occurrence of that repeated child, output one or more CSV rows where:
  - Scalar leaf fields from the row element's ancestors at and above the row parent
    (excluding any repeating groups) are repeated into every row (e.g., fa1..fa3).
  - Scalar leaf fields under the row element are flattened into columns (e.g., fb1..fb3).
  - If there are nested repeating groups under the row element, expand rows for each
    occurrence (cartesian expansion across nested repeaters). If a nested group is
    absent for some rows, leave those columns blank.
- The CSV header is the union of all encountered scalar leaf field names in encounter
  order: first ancestor/context fields, then row-level fields and deeper nested fields.
- Column names default to the leaf tag name; if a collision occurs, a dotted path is
  used to disambiguate (e.g., parent.child.leaf).
- Accept one or more XML files as positional arguments and write corresponding CSV
  files with the same base name and a .csv extension in the same directory.

Note: This is a general-purpose heuristic to match the examples provided. XMLs with
multiple different repeating groups at the same level or ambiguous structures may
require explicit configuration which is out of scope here.
"""

from __future__ import annotations

import argparse
import csv
from collections import Counter, OrderedDict
from pathlib import Path
from typing import Dict, Iterable, Iterator, List, Optional, Sequence, Tuple
import xml.etree.ElementTree as ET


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Convert XML file(s) to CSV by flattening repeating child elements",
    )
    parser.add_argument(
        "inputs",
        nargs="+",
        help="One or more XML files to convert",
    )
    parser.add_argument(
        "--merge-into",
        dest="merge_into",
        default=None,
        help=(
            "Optional path to a single merged CSV file. If provided, rows from all input XMLs "
            "are combined and written to this single CSV."
        ),
    )
    parser.add_argument(
        "--output-dir",
        dest="output_dir",
        default=None,
        help="Optional output directory for CSV files. Defaults to the same directory as the input file.",
    )
    parser.add_argument(
        "--encoding",
        dest="encoding",
        default="utf-8",
        help="Text encoding for reading XML and writing CSV (default: utf-8)",
    )
    parser.add_argument(
        "--delimiter",
        dest="delimiter",
        default=",",
        help="CSV delimiter (default: ,)",
    )
    return parser.parse_args()


def get_children_by_tag(parent: ET.Element) -> Dict[str, List[ET.Element]]:
    children_by_tag: Dict[str, List[ET.Element]] = {}
    for child in list(parent):
        children_by_tag.setdefault(child.tag, []).append(child)
    return children_by_tag


def first_repeating_child_tag(parent: ET.Element) -> Optional[str]:
    by_tag = get_children_by_tag(parent)
    for tag, nodes in by_tag.items():
        if len(nodes) > 1:
            return tag
    return None


def find_row_parent_and_tag(root: ET.Element) -> Tuple[Optional[ET.Element], str, List[ET.Element]]:
    """
    Find the first element in document order that has a repeating child tag.
    Returns (row_parent, row_tag, row_elements).

    If none found, treat the root as a single-row element.
    """
    # BFS through the tree until we find a parent with a repeating child
    queue: List[ET.Element] = [root]
    while queue:
        parent = queue.pop(0)
        tag = first_repeating_child_tag(parent)
        if tag is not None:
            row_elements = get_children_by_tag(parent)[tag]
            return parent, tag, row_elements
        queue.extend(list(parent))

    # No repeating children anywhere: single row is the root
    return None, root.tag, [root]


PathKey = Tuple[str, ...]


def compute_repeating_group_keys(parent: ET.Element, parent_path: PathKey) -> List[Tuple[PathKey, str, List[ET.Element]]]:
    """
    For a given parent node, return a list of repeating groups under this parent.
    Each entry is (group_key, child_tag, children).
    group_key identifies the group by (path_to_parent + child_tag).
    """
    children_by_tag = get_children_by_tag(parent)
    groups: List[Tuple[PathKey, str, List[ET.Element]]] = []
    for tag, children in children_by_tag.items():
        if len(children) > 1:
            group_key: PathKey = parent_path + (tag,)
            groups.append((group_key, tag, children))
    return groups


def find_next_unselected_repeating_group(
    root: ET.Element,
    selection: Dict[PathKey, int],
    path_prefix: Optional[PathKey] = None,
) -> Optional[Tuple[PathKey, List[ET.Element]]]:
    """
    Depth-first search for the next repeating group under root not covered by selection.
    Returns (group_key, children) or None if all are selected.
    """
    if path_prefix is None:
        path_prefix = (root.tag,)

    groups_here = compute_repeating_group_keys(root, path_prefix)
    for group_key, _tag, children in groups_here:
        if group_key not in selection:
            return group_key, children

    # Recurse into non-repeating children only (repeating groups handled above)
    for child in list(root):
        siblings = get_children_by_tag(root).get(child.tag, [])
        if len(siblings) == 1:
            found = find_next_unselected_repeating_group(child, selection, path_prefix + (child.tag,))
            if found is not None:
                return found
    return None


def iter_scalar_leaves(
    node: ET.Element,
    selection: Dict[PathKey, int],
    path: Optional[PathKey] = None,
) -> Iterator[Tuple[PathKey, str]]:
    """
    Yield (path, text) for scalar leaf nodes reachable from node while respecting selection
    for repeating groups. Unselected repeating groups are skipped entirely.
    """
    if path is None:
        path = (node.tag,)

    children = list(node)
    if not children:
        text = (node.text or "").strip()
        yield path, text
        return

    by_tag = get_children_by_tag(node)
    for tag, siblings in by_tag.items():
        next_path = path + (tag,)
        if len(siblings) > 1:
            group_key = next_path
            if group_key in selection:
                idx = selection[group_key]
                if 0 <= idx < len(siblings):
                    yield from iter_scalar_leaves(siblings[idx], selection, next_path)
            # If not selected, skip this repeating group entirely
            continue
        else:
            yield from iter_scalar_leaves(siblings[0], selection, next_path)


def build_container_values(row_parent: Optional[ET.Element], row_tag: str) -> OrderedDict:
    """
    Collect scalar leaves from the row_parent while excluding the repeating child group (row_tag).
    If row_parent is None (root is the row), return empty container values.
    """
    values: OrderedDict[str, str] = OrderedDict()
    if row_parent is None:
        return values

    selection: Dict[PathKey, int] = {}
    # Exclude the repeating group under row_parent by marking it as unselected (skip in traversal)
    # We accomplish this by not adding it to selection so iter_scalar_leaves will skip it.
    # Traverse children except the repeated row_tag group.
    for path, text in iter_scalar_leaves(row_parent, selection):
        # Skip any paths that include the repeating row_tag directly under the parent
        if len(path) >= 2 and path[0] == row_parent.tag and path[1] == row_tag:
            continue
        if text == "":
            continue
        col = path[-1]
        values[col] = text
    return values


def disambiguate_column_name(
    candidate: str,
    full_path: PathKey,
    existing: Dict[str, PathKey],
) -> str:
    """
    Ensure column names are unique. Prefer leaf tag name; on collision use dotted path.
    If dotted path also collides, append a numeric suffix.
    """
    if candidate not in existing:
        return candidate

    dotted = ".".join(full_path)
    if dotted not in existing:
        return dotted

    # Append numeric suffix until unique
    i = 2
    while True:
        alt = f"{dotted}_{i}"
        if alt not in existing:
            return alt
        i += 1


def extract_rows_for_element(
    row_elem: ET.Element,
    row_parent: Optional[ET.Element],
    row_tag: str,
    header_order: List[str],
    header_paths: Dict[str, PathKey],
) -> List[OrderedDict]:
    """
    Expand nested repeating groups under row_elem into multiple contexts and
    extract a list of row dictionaries for CSV writing.
    """
    container_values = build_container_values(row_parent, row_tag)

    # Expand contexts across nested repeating groups under row_elem
    pending: List[Dict[PathKey, int]] = [{}]
    finalized: List[Dict[PathKey, int]] = []

    while pending:
        sel = pending.pop()
        found = find_next_unselected_repeating_group(row_elem, sel)
        if found is None:
            finalized.append(sel)
            continue
        group_key, children = found
        for idx in range(len(children)):
            new_sel = dict(sel)
            new_sel[group_key] = idx
            pending.append(new_sel)

    rows: List[OrderedDict] = []
    for sel in finalized:
        row_map: OrderedDict[str, str] = OrderedDict()

        # Seed with container values first (and register header order/paths)
        for candidate_name, value in container_values.items():
            if candidate_name in header_paths and header_paths[candidate_name] != (row_parent.tag, candidate_name) if row_parent is not None else False:
                # Disambiguate against an existing different path
                full_path = (row_parent.tag, candidate_name) if row_parent is not None else (candidate_name,)
                col = disambiguate_column_name(candidate_name, full_path, header_paths)
            else:
                col = candidate_name

            if col not in header_paths:
                full_path = (row_parent.tag, candidate_name) if row_parent is not None else (candidate_name,)
                header_paths[col] = full_path
                header_order.append(col)

            if col not in row_map:
                row_map[col] = value

        # Now add values from row element subtree respecting selection
        for path, text in iter_scalar_leaves(row_elem, sel):
            # Skip the top-level tag of row's parent in the path if present.
            if len(path) >= 2 and row_parent is not None and path[0] == row_parent.tag and path[1] == row_tag:
                effective_path = path[1:]  # start from row_tag
            else:
                effective_path = path

            if text == "":
                continue
            candidate_name = effective_path[-1]
            if candidate_name in header_paths and header_paths[candidate_name] != effective_path:
                col = disambiguate_column_name(candidate_name, effective_path, header_paths)
            else:
                col = candidate_name

            # Update header tracking
            if col not in header_paths:
                header_paths[col] = effective_path
                header_order.append(col)

            row_map[col] = text

        rows.append(row_map)

    return rows


def convert_xml_to_csv(input_path: Path, output_dir: Optional[Path], encoding: str, delimiter: str) -> Path:
    tree = ET.parse(str(input_path))
    root = tree.getroot()

    row_parent, row_tag, row_elements = find_row_parent_and_tag(root)

    header_order: List[str] = []
    header_paths: Dict[str, PathKey] = {}
    table_rows: List[OrderedDict[str, str]] = []

    for row_elem in row_elements:
        extracted = extract_rows_for_element(row_elem, row_parent, row_tag, header_order, header_paths)
        table_rows.extend(extracted)

    # Ensure all container columns appear first in header order by scanning first row's container again
    # (header already constructed during extraction, which seeded container columns first per row.)

    # Compute output path
    out_dir = output_dir if output_dir is not None else input_path.parent
    out_path = out_dir / (input_path.stem + ".csv")

    # Write CSV
    with out_path.open("w", encoding=encoding, newline="") as f:
        writer = csv.writer(f, delimiter=delimiter)
        writer.writerow(header_order)
        for row in table_rows:
            writer.writerow([row.get(col, "") for col in header_order])

    return out_path


def extract_table_from_file(
    input_path: Path,
    header_order: List[str],
    header_paths: Dict[str, PathKey],
) -> List[OrderedDict[str, str]]:
    """
    Parse a single XML file and extract rows, updating the provided header_order and header_paths
    so that column naming is consistent across multiple files when merging.
    """
    tree = ET.parse(str(input_path))
    root = tree.getroot()
    row_parent, row_tag, row_elements = find_row_parent_and_tag(root)

    rows: List[OrderedDict[str, str]] = []
    for row_elem in row_elements:
        extracted = extract_rows_for_element(row_elem, row_parent, row_tag, header_order, header_paths)
        rows.extend(extracted)
    return rows


def main() -> None:
    args = parse_args()
    inputs: List[Path] = [Path(p).expanduser().resolve() for p in args.inputs]
    output_dir: Optional[Path] = None
    if args.output_dir is not None:
        output_dir = Path(args.output_dir).expanduser().resolve()
        output_dir.mkdir(parents=True, exist_ok=True)

    if args.merge_into is not None:
        # Merge all inputs into a single CSV
        merged_header_order: List[str] = []
        merged_header_paths: Dict[str, PathKey] = {}
        merged_rows: List[OrderedDict[str, str]] = []

        for inp in inputs:
            if not inp.exists():
                print(f"Skipping non-existent file: {inp}")
                continue
            try:
                merged_rows.extend(extract_table_from_file(inp, merged_header_order, merged_header_paths))
            except Exception as exc:
                print(f"Failed to parse {inp}: {exc}")

        # Determine output path for merged file
        merge_path = Path(args.merge_into).expanduser().resolve()
        if merge_path.is_dir():
            # If a directory is provided, use a default filename inside it
            merge_path = merge_path / "merged.csv"
        merge_path.parent.mkdir(parents=True, exist_ok=True)

        with merge_path.open("w", encoding=args.encoding, newline="") as f:
            writer = csv.writer(f, delimiter=args.delimiter)
            writer.writerow(merged_header_order)
            for row in merged_rows:
                writer.writerow([row.get(col, "") for col in merged_header_order])
        print(f"Wrote merged CSV: {merge_path}")
    else:
        # One CSV per input
        for inp in inputs:
            if not inp.exists():
                print(f"Skipping non-existent file: {inp}")
                continue
            try:
                out_path = convert_xml_to_csv(inp, output_dir, args.encoding, args.delimiter)
                print(f"Wrote: {out_path}")
            except Exception as exc:
                print(f"Failed to convert {inp}: {exc}")


if __name__ == "__main__":
    main()

