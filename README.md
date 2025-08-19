## xml2csv

Convert XML file(s) into CSV by flattening repeating child elements. Designed to match the behavior illustrated by the provided examples, while remaining generally useful for similar hierarchical XML structures.

### Highlights
- Detects the first repeating child group and treats each occurrence as a CSV row unit
- Carries ancestor scalar fields into each row
- Flattens nested structures; expands nested repeating groups into multiple rows
- Stable header union across all rows (and across files when merging)
- Supports converting one or many files, or merging many inputs into a single CSV
 - List predicted columns or select a subset of columns to write

## Installation
The tool is a single Python script and uses only the standard library.

```bash
python3 --version  # Python 3.8+
```

Clone or copy the repo and run the script directly.

## Usage

```bash
# Convert one or more XML files, writing one CSV per input next to each source file
python3 xml2csv.py input1.xml input2.xml

# Choose an output directory for per-file CSVs
python3 xml2csv.py --output-dir /path/to/out input1.xml input2.xml

# Merge rows from multiple XMLs into a single CSV file
python3 xml2csv.py --merge-into /path/to/out/all_rows.csv input1.xml input2.xml input3.xml

# Merge into a directory (creates merged.csv inside)
python3 xml2csv.py --merge-into /path/to/out input1.xml input2.xml

# Control CSV delimiter and I/O encoding
python3 xml2csv.py --delimiter ';' --encoding utf-8 input.xml

# List columns without writing CSVs (per file)
python3 xml2csv.py --list-columns input1.xml input2.xml

# List merged union of columns across inputs
python3 xml2csv.py --merge-into /does/not/matter --list-columns input1.xml input2.xml

# Write only a selected subset of columns (requested order preserved)
python3 xml2csv.py --select-columns fa1,fa2 --select-columns fb1 input1.xml
python3 xml2csv.py --merge-into /path/to/out/all_rows.csv --select-columns fa1,fb1 input1.xml input2.xml
```

### Options
- **positional `inputs`**: One or more `.xml` files
- **`--merge-into PATH`**: Write a single merged CSV for all inputs. If PATH is a directory, `merged.csv` is created inside. When set, `--output-dir` is ignored
- **`--output-dir DIR`**: Directory for per-input CSVs (default: same directory as each XML)
- **`--delimiter`**: CSV delimiter (default: `,`)
- **`--encoding`**: Read/write text encoding (default: `utf-8`)
- **`--list-columns`**: List columns that would be generated and exit. With `--merge-into`, lists merged union; otherwise lists per file
- **`--select-columns`**: Comma-separated column names to include in output. Can be provided multiple times; names must match resolved header names (after disambiguation)

## Behavior model (requirements)
- **Row unit detection**: The script scans in document order to find the first element that has a repeated child tag. Each occurrence of that repeated tag becomes a row. If no repeating group exists, the root yields a single row.
- **Ancestor fields**: Scalar leaf fields from the row element’s ancestor container (excluding repeating groups) are repeated into every row.
- **Row and nested fields**: Scalar leaves under the row element are flattened into columns. Nested single-occurrence elements contribute their leaves as columns. If a nested element is absent for a row, the corresponding cells are blank.
- **Nested repeating groups**: If the row element contains nested repeating groups, the script expands rows across those groups (cartesian expansion). If a nested repeating group is missing, related columns are blank (i.e., the base row is still emitted).
- **Header**: The CSV header is the union of all encountered scalar leaf field names across all rows (and across all inputs when merging), in encounter order: container fields first, then row-level, then deeper nested fields.
- **Column naming**: By default a column is named by its leaf tag. On collision, a dotted path (e.g., `parent.child.leaf`) is used; on further collision, numeric suffixes are appended.
- **Column listing/selection**: You can list the columns that would be generated without writing CSVs. You can also restrict output to a subset of columns; missing columns are ignored with a warning, and the requested order is preserved.

## Examples

### Sample 1
XML:
```xml
<a>
    <fa1>va1</fa1>
    <fa2>va2</fa2>
    <fa3>va3</fa3>
    <b>
        <fb1>vb1</fb1>
        <fb2>vb2</fb2>
        <fb3>vb3</fb3>
    </b>
    <b>
        <fb1>vb11</fb1>
        <fb2>vb21</fb2>
        <fb3>vb31</fb3>
    </b>
</a>
```

CSV:
```csv
fa1,fa2,fa3,fb1,fb2,fb3
va1,va2,va3,vb1,vb2,vb3
va1,va2,va3,vb11,vb21,vb31
```

### Sample 2
XML:
```xml
<a>
    <fa1>va1</fa1>
    <fa2>va2</fa2>
    <fa3>va3</fa3>
    <b>
        <fb1>vb1</fb1>
        <fb2>vb2</fb2>
        <fb3>vb3</fb3>
    </b>
    <b>
        <fb1>vb11</fb1>
        <fb2>vb21</fb2>
        <fb3>vb31</fb3>
        <c>
            <fc1>vc1</fc1>
            <fc2>vc2</fc2>
        </c>
    </b>
</a>
```

CSV:
```csv
fa1,fa2,fa3,fb1,fb2,fb3,fc1,fc2
va1,va2,va3,vb1,vb2,vb3,,
va1,va2,va3,vb11,vb21,vb31,vc1,vc2
```

## Notes and limitations
- The parser uses `xml.etree.ElementTree` and loads each XML file fully into memory. Very large XMLs may require substantial RAM. For extremely large inputs, an `iterparse`-based approach might be preferable (not implemented here).
- The heuristic is designed to match the examples: it uses the first repeating group in document order as the row unit. XMLs with multiple meaningful repeating groups at different levels may need explicit configuration (out of scope for this tool).
- CSV writing uses Python’s `csv.writer` with minimal quoting. Use `--delimiter` and `--encoding` as needed for your environment.

## Troubleshooting
- "Skipping non-existent file": The specified path does not exist; check the filename.
- "Failed to convert …": The XML may be malformed or not readable with the given encoding.
- Merged CSV has more columns than individual files: This is expected when different files contain additional fields; the header is the union.

## Development
Run from the repo root:
```bash
python3 -m pylint xml2csv.py  # if you use pylint
python3 xml2csv.py --help
```

