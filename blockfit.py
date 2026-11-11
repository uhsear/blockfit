#!/usr/bin/env python
"""Refuse a block-to-district assignment that does not reconcile, or that sits on the wrong vintage.

The usual way to give each Census block a district is to take the block's centroid and ask which
district holds it. A block whose centroid falls on water, or just outside the district tiling, is
then in no district. The district tables still print. They add up to a little less than the county,
and nothing says so. The same job can also read the 2020 blocks to place 2010 people. Census redraws
the blocks every decade, so the two files share many GEOIDs and disagree about the rest.

blockfit takes a block extract (one row per block, a GEOID column and count columns, such as the
CSV that pl94 writes) and an assignment of those blocks to districts. It prints the district
table, and it refuses unless every block is in exactly one district, the extract and the
assignment name the same blocks, and the district sums equal the extract. It never reads a
shapefile and never imports arcpy.

--parts takes the pieces of an overlay of blocks on districts instead (geoid, district, area),
and gives each block to the district that holds the largest part of it. That is a pure function
of the table, so the tie rule and the split blocks are reported rather than hidden.

    python blockfit.py --self-test
    python blockfit.py --blocks blocks.csv --assignment assign.csv --year 2020 --county 99001
    python blockfit.py --blocks blocks.csv --parts pieces.csv --year 2020 --county 99001
    python blockfit.py --blocks blocks.csv --assignment assign.csv --year 2020 --county 99001 \\
        --control-total 1234 --out districts.csv --apply

Nothing is written unless --apply is given. Exit codes: 0 reconciled, 1 refused (the data
disagree), 2 a file could not be read or written, 64 usage error.
"""

from __future__ import print_function

import argparse
import csv
import io
import math
import os
import sys

# =============================================================================
# CONFIGURATION
# =============================================================================
YEARS = ("2010", "2020")
GEOID_COLUMNS = ("geoid", "geoid10", "geoid20")
DEFAULT_MEASURE = "total"
SAMPLE = 5            # example GEOIDs shown per reason; the counts are always exact
DIGITS = "0123456789"
RESERVED_COLUMNS = ("district", "blocks")   # the summary CSV names its own
# A spreadsheet runs a cell that starts with one of these as a formula (OWASP, CSV Injection).
NULL_LABELS = ("-1", "null", "none", "nan", "n/a", "unassigned", "unknown")   # "no district"
FORMULA_LEADS = ("=", "+", "-", "@", "\t", "\r", "\n")

EXIT_OK = 0
EXIT_REFUSED = 1
EXIT_IO = 2
EXIT_USAGE = 64
EXIT_UNVERIFIED = 3


class InputError(Exception):
    """A file that cannot be read or is malformed. The caller exits 2."""


# ------------------------------------------------------------------- pure core

def is_digits(text):
    """True for a non-empty string of ASCII digits. str.isdigit also accepts other scripts."""
    return text != "" and all(ch in DIGITS for ch in text)


def is_printable_ascii(text):
    return all(" " <= ch <= "~" for ch in text)


def normalise_geoid(text):
    """Return the 15 digit block GEOID in text, or raise ValueError saying why not.

    A block GEOID is state (2) + county (3) + tract (6) + block (4) digits. A 14 digit
    value is the one a spreadsheet or an integer column produces for a state whose FIPS
    code starts with 0, so the message says so.
    """
    geoid = text.strip()
    if not is_digits(geoid):
        raise ValueError("%s is not a string of ASCII digits" % ascii(text))
    if len(geoid) == 14:
        raise ValueError("%s has 14 digits; a leading zero was probably lost" % ascii(text))
    if len(geoid) != 15:
        raise ValueError("%s has %d digits; a block GEOID has 15" % (ascii(text), len(geoid)))
    return geoid


def district_key(district):
    """Sort whole numbers as numbers, then everything else as text."""
    if is_digits(district):
        # Compare digit strings by length, then text: the order int() gives, with no 4300 digit cap.
        digits = district.lstrip("0")
        return (0, len(digits), digits, district)
    return (1, 0, "", district)


def collect_assignment(rows):
    """rows: (geoid, district) pairs. -> (assign, repeated, conflicting).

    The first district seen for a block is kept. A block named twice with the same district
    is repeated; with two districts it is conflicting. Either way the caller refuses.
    """
    assign = {}
    repeated = set()
    conflicting = set()
    for geoid, district in rows:
        if geoid not in assign:
            assign[geoid] = district
        elif assign[geoid] == district:
            repeated.add(geoid)
        else:
            conflicting.add(geoid)
    return assign, sorted(repeated), sorted(conflicting)


def max_overlap(pieces):
    """pieces: (geoid, district, area) triples. -> (assign, info).

    Each block goes to the district holding the largest summed area of it. A tie goes to the
    lowest district by district_key, and the block is listed in info["ties"]. A piece with
    area 0 is counted in info["empty"] and ignored. A block with no positive piece is left
    out of assign, so the reconcile reports it as unassigned. info["split"] maps each block
    that touches more than one district to how many.

    math.fsum returns the correctly rounded sum of the exact inputs on every Python. The
    built-in sum is only compensated from 3.12, so on 3.9 to 3.11 it could break a tie by
    rounding, and the two hosts would disagree.
    """
    parts = {}
    empty = 0
    for geoid, district, area in pieces:
        if area <= 0:
            empty += 1
            continue
        parts.setdefault(geoid, {}).setdefault(district, []).append(area)
    assign = {}
    split = {}
    ties = []
    for geoid, per_district in parts.items():
        ranked = sorted((-math.fsum(areas), district_key(district), district)
                        for district, areas in per_district.items())
        assign[geoid] = ranked[0][2]
        if len(ranked) > 1:
            split[geoid] = len(ranked)
            if ranked[1][0] == ranked[0][0]:
                ties.append(geoid)
    return assign, {"split": split, "ties": sorted(ties), "empty": empty}


def cell(value):
    """A CSV text cell that a spreadsheet will not run as a formula. Numbers pass unchanged.

    A text starting with a character in FORMULA_LEADS gets one apostrophe in front. So does a
    text that starts with apostrophes and then such a character, so that uncell(cell(x)) == x
    for every text x: without it "=x" and "'=x" would both read back as "=x".
    """
    if not isinstance(value, str):
        return value
    if value[:1] in FORMULA_LEADS or (value[:1] == "'" and value.lstrip("'")[:1] in FORMULA_LEADS):
        return "'" + value
    return value


def uncell(value):
    """The inverse of cell: drop the one apostrophe that cell added, and nothing else."""
    if value[:1] == "'" and value.lstrip("'")[:1] in FORMULA_LEADS:
        return value[1:]
    return value


def is_null_label(label):
    """True for a label GIS tools use for "no district": all zeros, -1, null, none and so on."""
    text = label.strip().lower()
    return text in NULL_LABELS or (is_digits(text) and not text.strip("0"))


def safe(text):
    """text with every non-ASCII character escaped, so a strict stdout cannot fail on a path."""
    return text.encode("ascii", "backslashreplace").decode("ascii")


def sample(items):
    """Up to SAMPLE items, with the true count when there are more."""
    shown = ", ".join(items[:SAMPLE])
    if len(items) > SAMPLE:
        shown += " (first %d of %d)" % (SAMPLE, len(items))
    return shown


def reconcile(blocks, columns, measure, assign, year, county, tags,
              repeated=(), conflicting=(), control=None, require_tag=False):
    """Decide whether the assignment reconciles to the extract. Pure: no I/O.

    blocks  geoid -> {column: int}, one entry per extract row
    assign  geoid -> district
    tags    (extract_tag, assignment_tag): 10, 20 or None, read from a GEOID10 or GEOID20 header
    control optional population the extract itself must equal
    require_tag  refuse when neither header carries a GEOID10 or GEOID20 tag, because then
                 nothing in the files says which vintage they are

    Returns a dict. report["ok"] is True only when report["reasons"] is empty.
    """
    reasons = []
    wanted = int(year) % 100
    for label, tag in zip(("block extract", "assignment"), tags):
        if tag is not None and tag != wanted:
            reasons.append("VINTAGE: the %s header says GEOID%d but --year is %s" %
                           (label, tag, year))

    foreign_blocks = sorted(g for g in blocks if not g.startswith(county))
    foreign_assign = sorted(g for g in assign if not g.startswith(county))
    if foreign_blocks:
        reasons.append("COUNTY: %d extract block(s) are outside county %s: %s" %
                       (len(foreign_blocks), county, sample(foreign_blocks)))
    if foreign_assign:
        reasons.append("COUNTY: %d assignment block(s) are outside county %s: %s" %
                       (len(foreign_assign), county, sample(foreign_assign)))

    in_extract = set(g for g in blocks if g.startswith(county))
    in_assign = set(g for g in assign if g.startswith(county))
    matched = sorted(in_extract & in_assign)
    unassigned = sorted(in_extract - in_assign)
    orphans = sorted(in_assign - in_extract)

    if not blocks:
        reasons.append("EMPTY: the block extract has no rows, so there is nothing to reconcile")

    lost = dict((col, sum(blocks[g][col] for g in unassigned)) for col in columns)
    if unassigned and orphans:
        reasons.append(
            "VINTAGE: %d extract block(s) (%d %s) are in no district and %d assignment block(s) "
            "are not in the extract; %d of %d assignment blocks match. Census redraws blocks "
            "every decade, so these files describe different block sets. Both files must use "
            "the %s blocks, and blockfit cannot tell which one does not. Extract only: %s. "
            "Assignment only: %s" %
            (len(unassigned), lost[measure], measure, len(orphans), len(matched),
             len(in_assign), year, sample(unassigned), sample(orphans)))
    elif unassigned:
        reasons.append("UNASSIGNED: %d extract block(s) are in no district, holding %d %s: %s" %
                       (len(unassigned), lost[measure], measure, sample(unassigned)))
    elif orphans:
        reasons.append("ORPHAN: the assignment names %d block(s) the extract does not have: %s" %
                       (len(orphans), sample(orphans)))
    if repeated:
        reasons.append("REPEATED: %d block(s) appear more than once in the assignment: %s" %
                       (len(repeated), sample(list(repeated))))
    if conflicting:
        reasons.append("CONFLICT: %d block(s) are given two districts: %s" %
                       (len(conflicting), sample(list(conflicting))))

    extract_totals = dict((col, sum(blocks[g][col] for g in in_extract)) for col in columns)
    if control is not None and extract_totals[measure] != control:
        reasons.append("CONTROL: the extract holds %d %s but the control total is %d" %
                       (extract_totals[measure], measure, control))

    districts = {}
    for geoid in matched:
        row = districts.setdefault(assign[geoid],
                                   dict([("blocks", 0)] + [(col, 0) for col in columns]))
        row["blocks"] += 1
        for col in columns:
            row[col] += blocks[geoid][col]
    nulls = sorted((d for d in districts if is_null_label(d)), key=district_key)
    if nulls:
        reasons.append(
            "NULL-DISTRICT: %d block(s) hold the district label(s) %s, holding %d %s. GIS tools "
            "write these labels for a block with no district, so they may be unassigned blocks "
            "and not a district. If a label is a real district, rename it in the input file" %
            (sum(districts[d]["blocks"] for d in nulls), sample(nulls),
             sum(districts[d][measure] for d in nulls), measure))
    verified = any(tag is not None for tag in tags)
    if require_tag and not verified:
        reasons.append(
            "UNVERIFIED-VINTAGE: neither header carries a GEOID10 or GEOID20 tag, so nothing in "
            "the files says they are %s blocks. --year %s is your claim, and blockfit cannot "
            "check it. Rename a geoid header to geoid%d if it is true, or pass --trust-year to "
            "accept the claim" % (year, year, wanted))
    assigned_totals = dict((col, sum(row[col] for row in districts.values())) for col in columns)
    return {
        "ok": not reasons,
        "vintage_verified": verified,
        "reasons": reasons,
        "districts": sorted(districts.items(), key=lambda kv: district_key(kv[0])),
        "columns": list(columns),
        "measure": measure,
        "extract_blocks": len(blocks),
        "assign_blocks": len(assign),
        "matched": len(matched),
        "extract_totals": extract_totals,
        "assigned_totals": assigned_totals,
        "control": control,
        "unassigned": unassigned,
        "orphans": orphans,
        "lost": lost,
    }


def render(report, names, year, county, parts_info=None):
    """The text report. names is (extract label, assignment label, 'assignment' or 'parts')."""
    lines = ["blockfit: %s with %s %s" % (safe(names[0]), names[2], safe(names[1])),
             "  county %s, %s blocks, count column '%s'" % (county, year, report["measure"])]
    if not report["vintage_verified"]:
        lines.append("  vintage: not verified. Neither header carries a GEOID10 or GEOID20 tag, "
                     "so %s is your claim, not a finding." % year)
    lines += ["",
              "  blocks in the extract       : %d" % report["extract_blocks"],
              "  blocks in the assignment    : %d" % report["assign_blocks"],
              "  blocks in both              : %d" % report["matched"],
              ""]
    columns = report["columns"]
    lines.append("  %-10s %7s %s" % ("DISTRICT", "BLOCKS", " ".join("%12s" % c for c in columns)))
    for district, row in report["districts"]:
        lines.append("  %-10s %7d %s" % (district, row["blocks"],
                                         " ".join("%12d" % row[c] for c in columns)))
    lines.append("")
    for col in columns:
        lines.append("  %-14s districts %d / extract %d" %
                     (col, report["assigned_totals"][col], report["extract_totals"][col]))
    if report["control"] is not None:
        lines.append("  %-14s extract %d / control %d" %
                     (report["measure"], report["extract_totals"][report["measure"]],
                      report["control"]))
    if parts_info is not None:
        split = parts_info["split"]
        lines.append("")
        lines.append("  blocks split across districts: %d, holding %d %s (whole blocks, so this "
                     "bounds the people the largest-overlap rule can misplace)" %
                     (len(split), parts_info["people"], report["measure"]))
        lines.append("  ties on area broken by the lowest district: %d" % len(parts_info["ties"]))
        lines.append("  pieces with zero area ignored: %d" % parts_info["empty"])
    lines.append("")
    if report["ok"]:
        lines.append("RECONCILED%s: every block is in exactly one district and the district "
                     "sums equal the extract." %
                     ("" if report["vintage_verified"] else " (vintage not verified)"))
    else:
        lines.append("REFUSED: %d reason(s)" % len(report["reasons"]))
        for number, reason in enumerate(report["reasons"], 1):
            lines.append("  %d. %s" % (number, reason))
    return "\n".join(lines) + "\n"


# -------------------------------------------------------------------------- I/O

def parse_table(data, label):
    """bytes -> (header, body). header: lowercase names. body: (line number, cells) pairs."""
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise InputError("%s is not UTF-8 text" % label)
    if "\x00" in text:
        raise InputError("%s contains a NUL byte" % label)
    reader = csv.reader(io.StringIO(text, newline=""))
    rows = []
    try:
        for cells in reader:
            if cells:
                rows.append((reader.line_num, cells))
    except csv.Error as exc:
        raise InputError("%s is not readable CSV: %s" % (label, exc))
    if not rows:
        raise InputError("%s has no header row" % label)
    header = [cell.strip().lower() for cell in rows[0][1]]
    if not all(is_printable_ascii(name) and name for name in header):
        raise InputError("%s has an empty or non-ASCII column name" % label)
    if len(set(header)) != len(header):
        raise InputError("%s repeats a column name" % label)
    body = rows[1:]
    for line, cells in body:
        if len(cells) != len(header):
            raise InputError("%s line %d has %d field(s), the header has %d" %
                             (label, line, len(cells), len(header)))
    return header, body


def read_table(path):
    try:
        with open(path, "rb") as fh:
            data = fh.read()
    except OSError as exc:
        raise InputError("cannot read %s: %s" % (path, exc.strerror or exc))
    return parse_table(data, path)


def geoid_column(header, label):
    """-> (index, tag). tag is 10 or 20 for a GEOID10 or GEOID20 header, else None."""
    found = [name for name in header if name in GEOID_COLUMNS]
    if len(found) != 1:
        raise InputError("%s needs exactly one of the columns %s, found %d" %
                         (label, "/".join(GEOID_COLUMNS), len(found)))
    name = found[0]
    return header.index(name), (int(name[5:]) if name != "geoid" else None)


def column(header, name, label):
    if name not in header:
        raise InputError("%s has no '%s' column" % (label, name))
    return header.index(name)


def cell_geoid(cells, index, label, line):
    try:
        return normalise_geoid(cells[index])
    except ValueError as exc:
        raise InputError("%s line %d: %s" % (label, line, exc))


def cell_district(cells, index, label, line):
    """The district label in a cell. A leading apostrophe that write_csv added is removed."""
    district = cells[index].strip()
    if district == "" or not is_printable_ascii(district):
        raise InputError("%s line %d: the district is empty or not printable ASCII" %
                         (label, line))
    return uncell(district)


def load_blocks(header, body, measure, label):
    """-> (blocks, columns, tag). blocks maps geoid -> {column: int}."""
    gi, tag = geoid_column(header, label)
    columns = [name for i, name in enumerate(header) if i != gi]
    for name in columns:
        if name in RESERVED_COLUMNS:
            raise InputError("%s has a column called '%s', which the district table uses" %
                             (label, name))
    if measure not in columns:
        raise InputError("%s has no '%s' column to count" % (label, measure))
    blocks = {}
    for line, cells in body:
        geoid = cell_geoid(cells, gi, label, line)
        if geoid in blocks:
            raise InputError("%s line %d: block %s appears twice" % (label, line, geoid))
        values = {}
        for i, name in enumerate(header):
            if i != gi:
                if not is_digits(cells[i].strip()):
                    raise InputError("%s line %d: column '%s' is not a whole number" %
                                     (label, line, name))
                values[name] = int(cells[i].strip())
        blocks[geoid] = values
    return blocks, columns, tag


def load_assignment(header, body, label):
    """-> (assign, repeated, conflicting, tag)."""
    gi, tag = geoid_column(header, label)
    di = column(header, "district", label)
    rows = [(cell_geoid(cells, gi, label, line), cell_district(cells, di, label, line))
            for line, cells in body]
    assign, repeated, conflicting = collect_assignment(rows)
    return assign, repeated, conflicting, tag


def load_parts(header, body, label):
    """-> (assign, info, tag)."""
    gi, tag = geoid_column(header, label)
    di = column(header, "district", label)
    ai = column(header, "area", label)
    pieces = []
    for line, cells in body:
        try:
            area = float(cells[ai])
        except ValueError:
            raise InputError("%s line %d: area %s is not a number" %
                             (label, line, ascii(cells[ai])))
        if not math.isfinite(area) or area < 0:
            raise InputError("%s line %d: area must be a finite number, 0 or more" %
                             (label, line))
        pieces.append((cell_geoid(cells, gi, label, line),
                       cell_district(cells, di, label, line), area))
    assign, info = max_overlap(pieces)
    return assign, info, tag


def write_csv(path, header, rows):
    """Write the CSV. Every text cell goes through cell(), so no cell is a formula."""
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh, lineterminator="\n")
        writer.writerow([cell(name) for name in header])
        for row in rows:
            writer.writerow([cell(value) for value in row])


def same_file(left, right):
    return os.path.normcase(os.path.realpath(left)) == os.path.normcase(os.path.realpath(right))


# ------------------------------------------------------------------------- cli

def _parse(argv):
    parser = argparse.ArgumentParser(
        prog="blockfit", allow_abbrev=False,
        description="Refuse a block-to-district assignment that does not reconcile, "
                    "or that sits on the wrong block vintage.")
    parser.add_argument("--blocks", help="Block extract CSV: a GEOID column and whole-number "
                        "count columns. Required.")
    parser.add_argument("--assignment", help="CSV of geoid,district. Use this or --parts.")
    parser.add_argument("--parts", help="CSV of geoid,district,area: the pieces of an overlay of "
                        "blocks on districts. Each block goes to its largest piece.")
    parser.add_argument("--year", help="Block vintage of --blocks: 2010 or 2020. Required.")
    parser.add_argument("--county", help="Five digit state plus county FIPS. Required.")
    parser.add_argument("--measure", default=DEFAULT_MEASURE,
                        help="Count column that means people (default: %(default)s).")
    parser.add_argument("--control-total", help="The extract's --measure must equal this number.")
    parser.add_argument("--trust-year", action="store_true",
                        help="Accept --year when neither file has a GEOID10 or GEOID20 header. "
                        "Without it such a run is refused, because blockfit cannot check the year.")
    parser.add_argument("--out", help="Path for the district summary CSV. Needs --apply.")
    parser.add_argument("--assign-out", help="Path for the block-to-district CSV that --parts "
                        "produced. Needs --apply.")
    parser.add_argument("--apply", action="store_true",
                        help="Write --out and --assign-out. Without it nothing is written.")
    parser.add_argument("--allow-unreconciled", action="store_true",
                        help="Write the outputs even when the check refused. Still exits 1.")
    parser.add_argument("--self-test", action="store_true",
                        help="Run the offline assertions and exit.")
    return parser.parse_args(argv)


def usage_problem(args):
    """The first usage error in args, or None."""
    for flag in ("blocks", "year", "county"):
        if getattr(args, flag) is None:
            return "--%s is required" % flag
    if (args.assignment is None) == (args.parts is None):
        return "give exactly one of --assignment and --parts"
    if args.year not in YEARS:
        return "--year must be one of %s" % ", ".join(YEARS)
    if not (is_digits(args.county) and len(args.county) == 5):
        return "--county must be five ASCII digits: state FIPS then county FIPS"
    if args.control_total is not None and not is_digits(args.control_total):
        return "--control-total must be a whole number"
    if args.assign_out is not None and args.parts is None:
        return "--assign-out only makes sense with --parts"
    outputs = [p for p in (args.out, args.assign_out) if p is not None]
    if outputs and not args.apply:
        return "--out and --assign-out write files, so they need --apply"
    if args.apply and not outputs:
        return "--apply needs --out or --assign-out"
    inputs = [p for p in (args.blocks, args.assignment, args.parts) if p is not None]
    for path in outputs:
        if any(same_file(path, other) for other in inputs):
            return "%s is also an input; blockfit will not overwrite its input" % path
    if len(outputs) == 2 and same_file(outputs[0], outputs[1]):
        return "--out and --assign-out are the same file"
    return None


def write_failed(err, what, exc, out, real_stdout):
    """Say that a write failed and return EXIT_IO.

    After a failed flush Python keeps the unwritten report in the stdout buffer and flushes it
    again at shutdown. On a closed pipe that second flush fails, and the interpreter replaces
    our exit code with 120. Pointing the descriptor at os.devnull lets that flush succeed.
    This is the recipe in the Python documentation for BrokenPipeError.
    """
    err.write("blockfit: cannot write%s: %s\n" % (" " + what if what else "", exc))
    if real_stdout:
        try:
            os.dup2(os.open(os.devnull, os.O_WRONLY), out.fileno())
        except (OSError, ValueError):   # no usable descriptor, so there is nothing to redirect
            pass
    return EXIT_IO


def main(argv=None, out=None, err=None):
    args = _parse(argv)
    real_stdout = out is None
    out = sys.stdout if out is None else out
    err = sys.stderr if err is None else err
    if args.self_test:
        return self_test()
    problem = usage_problem(args)
    if problem is not None:
        err.write("blockfit: usage: %s\n" % problem)
        return EXIT_USAGE
    measure = args.measure.strip().lower()
    control = None if args.control_total is None else int(args.control_total)
    try:
        header, body = read_table(args.blocks)
        blocks, columns, block_tag = load_blocks(header, body, measure, args.blocks)
        if args.assignment is not None:
            other = args.assignment
            header, body = read_table(other)
            assign, repeated, conflicting, tag = load_assignment(header, body, other)
            parts_info = None
        else:
            other = args.parts
            header, body = read_table(other)
            assign, parts_info, tag = load_parts(header, body, other)
            repeated = conflicting = ()
    except InputError as exc:
        err.write("blockfit: %s\n" % exc)
        return EXIT_IO

    report = reconcile(blocks, columns, measure, assign, args.year, args.county,
                       (block_tag, tag), repeated, conflicting, control,
                       require_tag=not args.trust_year)
    if parts_info is not None:
        parts_info["people"] = sum(blocks[g][measure] for g in parts_info["split"] if g in blocks)
    text = render(report, (args.blocks, other, "assignment" if parts_info is None else "parts"),
                  args.year, args.county, parts_info)
    # The report is flushed before any file is written, so a closed pipe cannot leave a
    # half-trusted CSV behind a report nobody saw.
    try:
        out.write(text)
        out.flush()
    except (OSError, ValueError) as exc:
        return write_failed(err, "the report", exc, out, real_stdout)
    if not report["ok"]:
        code = EXIT_REFUSED
    elif report["vintage_verified"]:
        code = EXIT_OK
    else:
        code = EXIT_UNVERIFIED   # reconciled, but --year is a claim the files cannot back
    if not args.apply:
        return code
    if not report["ok"] and not args.allow_unreconciled:
        err.write("blockfit: nothing written, because the check refused. "
                  "--allow-unreconciled writes anyway and still exits 1.\n")
        return code
    try:
        if args.out is not None:
            write_csv(args.out, ["district", "blocks"] + columns,
                      [[d, row["blocks"]] + [row[c] for c in columns]
                       for d, row in report["districts"]])
            out.write("wrote %s (%d row(s))\n" % (safe(args.out), len(report["districts"])))
        if args.assign_out is not None:
            write_csv(args.assign_out, ["geoid", "district"], sorted(assign.items()))
            out.write("wrote %s (%d row(s))\n" % (safe(args.assign_out), len(assign)))
        out.flush()
    except (OSError, ValueError) as exc:
        return write_failed(err, "", exc, out, real_stdout)
    return code


# ------------------------------------------------------------------- self-test

def self_test():
    """Offline assertions over synthetic blocks. Returns the exit code.

    No network, no census download, no arcpy. Every file the command line half reads is
    written here, in a temporary directory, and the real command line is run against it.
    """
    import contextlib
    import shutil
    import socket
    import subprocess
    import tempfile

    passed = [0]
    failed = []

    def check(cond, label):
        if cond:
            passed[0] += 1
            print("PASS  %s" % label)
        else:
            failed.append(label)
            print("FAIL  %s" % label)

    def raises(fn, label, exc_type=ValueError):
        try:
            fn()
        except exc_type:
            check(True, label)
        except Exception as exc:
            check(False, "%s (wrong exception %r)" % (label, exc))
        else:
            check(False, "%s (no error raised)" % label)

    print("blockfit self-test: no network, no census download, no arcpy")
    print("-" * 68)

    # ---- fixtures. County 99001 is not a real county. Every number is made up.
    def g(tract, block):
        return "99001" + tract + block

    G1, G2, G3 = g("000100", "1000"), g("000100", "1001"), g("000100", "1002")
    G4, G5, G6 = g("000100", "1003"), g("000100", "1004"), g("000200", "2000")
    BLOCKS = [(G1, 100, 1000), (G2, 200, 2000), (G3, 50, 3000),
              (G4, 350, 4000), (G5, 0, 500), (G6, 30, 600)]
    GOOD = [(G1, "1"), (G2, "1"), (G3, "2"), (G4, "2"), (G5, "2"), (G6, "2")]
    PIECES = [(G1, "1", 1000), (G2, "1", 600), (G2, "2", 400), (G3, "2", 300),
              (G4, "2", 800), (G5, "2", 500), (G5, "1", 0), (G6, "2", 100), (G6, "1", 100)]
    blocks = dict((geoid, {"total": t, "arealand": a}) for geoid, t, a in BLOCKS)
    cols = ["total", "arealand"]

    def rec(assign_rows, **kw):
        assign, repeated, conflicting = collect_assignment(assign_rows)
        kw.setdefault("tags", (None, None))
        return reconcile(blocks, cols, "total", assign, "2020", "99001",
                         repeated=repeated, conflicting=conflicting, **kw)

    def text_of(report):
        return " | ".join(report["reasons"])

    # ---- geoid
    check(normalise_geoid(G1) == G1, "a 15 digit block GEOID is accepted unchanged")
    check(normalise_geoid("  " + G1 + "\n") == G1, "and surrounding whitespace is stripped")
    raises(lambda: normalise_geoid(""), "an empty GEOID is refused")
    raises(lambda: normalise_geoid(G1[:-1] + "A"), "a GEOID with a letter is refused")
    raises(lambda: normalise_geoid(G1[:-1] + "\u0663"),
           "a GEOID with an Arabic-Indic digit is refused, because str.isdigit would pass it  "
           "<-- pinned defect")
    raises(lambda: normalise_geoid(G1 + "0"), "a 16 digit GEOID is refused")
    try:
        normalise_geoid(G1[1:])
    except ValueError as exc:
        check("leading zero" in str(exc),
              "a 14 digit GEOID is refused and the message names the lost leading zero  "
              "<-- pinned defect")
    check(is_digits("007") and not is_digits("") and not is_digits("1 "),
          "is_digits is ASCII only and refuses the empty string")
    check(is_printable_ascii("District 1") and not is_printable_ascii("caf\u00e9")
          and not is_printable_ascii("a\tb"), "printable ASCII excludes tabs and accents")
    check(sorted(["10", "2", "B", "1", "A"], key=district_key) == ["1", "2", "10", "A", "B"],
          "districts sort 1, 2, 10 then text, not 1, 10, 2")
    check(sorted(["9" * 5000, "2" * 5000, "007", "7", "A"], key=district_key)
          == ["007", "7", "2" * 5000, "9" * 5000, "A"],
          "a district label of more than 4300 digits sorts without a traceback  "
          "<-- pinned defect")
    check(sample(["a", "b"]) == "a, b" and "first 5 of 7" in sample(list("abcdefg")),
          "sample shows five and says how many there are")

    # ---- collect_assignment
    a, rep, con = collect_assignment([(G1, "1"), (G1, "1"), (G2, "1"), (G2, "2"), (G3, "2")])
    check(a == {G1: "1", G2: "1", G3: "2"}, "the first district seen for a block is kept")
    check(rep == [G1] and con == [G2], "a repeat and a conflict are told apart")

    # ---- max_overlap
    got, info = max_overlap(PIECES)
    check(got == {G1: "1", G2: "1", G3: "2", G4: "2", G5: "2", G6: "1"},
          "the largest piece decides: G2 is 600 against 400 and goes to district 1")
    check(sorted(info["split"]) == sorted([G2, G6]) and info["split"][G2] == 2,
          "the blocks that touch two districts are listed with how many")
    check(info["ties"] == [G6], "an exact tie is listed, never silent")
    check(got[G6] == "1", "and a tie goes to the lowest district")
    check(info["empty"] == 1, "a zero-area piece is counted and ignored")
    check(G5 in got and got[G5] == "2",
          "a block whose only positive piece is district 2 is not dragged to district 1 by "
          "its zero-area piece  <-- pinned defect")
    got2, _ = max_overlap([(G1, "2", 1.0), (G1, "1", 0.6), (G1, "1", 0.6)])
    check(got2[G1] == "1", "pieces of one district add up: 0.6 + 0.6 beats 1.0")
    fine = [(G1, "1", 1e16), (G1, "1", 1.0), (G1, "1", 1.0), (G1, "2", 1e16 + 2.0)]
    check(max_overlap(fine)[1]["ties"] == [G1] and
          max_overlap(list(reversed(fine)))[1]["ties"] == [G1],
          "pieces summing to the same exact area tie in either order, because the sum is "
          "exact and a running float sum would not be  <-- pinned defect")
    got3, info3 = max_overlap([(G1, "1", 0), (G1, "2", 0)])
    check(got3 == {} and info3["empty"] == 2,
          "a block with only zero-area pieces is left out, so the reconcile reports it")
    check(max_overlap([(G1, "2", 5.0), (G1, "10", 5.0)])[0][G1] == "2",
          "a tie between 2 and 10 goes to 2, the lower number, not the lower text")

    # ---- reconcile
    ok = rec(GOOD)
    check(ok["ok"] and ok["reasons"] == [], "a complete assignment reconciles")
    check(ok["assigned_totals"] == ok["extract_totals"] == {"total": 730, "arealand": 11100},
          "and the district sums equal the extract on both columns")
    check([d for d, _ in ok["districts"]] == ["1", "2"] and ok["districts"][1][1]["blocks"] == 4,
          "the district table has the right block counts")

    centroid = rec([r for r in GOOD if r[0] != G4])
    check(not centroid["ok"] and centroid["lost"]["total"] == 350,
          "an assignment missing the block whose centroid fell on water is refused and "
          "reports the 350 people it lost  <-- pinned defect")
    check("UNASSIGNED" in text_of(centroid) and "350 total" in text_of(centroid),
          "and the reason says so in words")
    check(centroid["assigned_totals"]["total"] == 380,
          "the district sums add to 380, not the extract's 730, with no error from the "
          "arithmetic  <-- pinned defect")
    empty_block = rec([r for r in GOOD if r[0] != G5])
    check(not empty_block["ok"] and empty_block["lost"]["total"] == 0,
          "a block with no people missing from the assignment is refused although the "
          "people still add up  <-- pinned defect")
    check(empty_block["assigned_totals"]["total"] == empty_block["extract_totals"]["total"],
          "the population totals agree in that case, so only the block count catches it")
    check(empty_block["lost"]["arealand"] == 500,
          "and the lost land area shows what went")

    foreign = [(g("000100", "9" + str(i) + "00"), "1") for i in range(1, 3)]
    vint = rec([r for r in GOOD if r[0] not in (G4, G5)] + foreign)
    check(not vint["ok"] and "VINTAGE" in text_of(vint) and "UNASSIGNED" not in text_of(vint),
          "blocks missing on one side and extra on the other are called a vintage mismatch  "
          "<-- pinned defect")
    check("4 of 6 assignment blocks match" in text_of(vint),
          "and the reason says how many blocks do match")
    check(vint["unassigned"] == [G4, G5] and vint["orphans"] == sorted(r[0] for r in foreign),
          "both sides' blocks are listed")
    orphan = rec(GOOD + [(g("000300", "3000"), "1")])
    check(not orphan["ok"] and "ORPHAN" in text_of(orphan),
          "an assignment block that the extract lacks is refused as an orphan")
    rep = rec(GOOD + [(G1, "1")])
    check(not rep["ok"] and "REPEATED" in text_of(rep),
          "a block listed twice with the same district is refused, not double counted  "
          "<-- pinned defect")
    con = rec(GOOD + [(G1, "2")])
    check(not con["ok"] and "CONFLICT" in text_of(con),
          "a block given two districts is refused")
    check(con["assigned_totals"]["total"] == 730,
          "and the first district is kept so the sums are not double counted")

    tag = rec(GOOD, tags=(10, None))
    check(not tag["ok"] and "extract header says GEOID10" in text_of(tag),
          "a GEOID10 extract against --year 2020 is refused  <-- pinned defect")
    tag2 = rec(GOOD, tags=(None, 10))
    check(not tag2["ok"] and "assignment header says GEOID10" in text_of(tag2),
          "and so is a GEOID10 assignment")
    check(rec(GOOD, tags=(20, 20))["ok"], "a GEOID20 header on both sides passes for 2020")

    strict = rec(GOOD, require_tag=True)
    check(not strict["ok"] and "UNVERIFIED-VINTAGE" in text_of(strict)
          and not strict["vintage_verified"],
          "with require_tag, two plain headers are refused because the vintage cannot be checked  "
          "<-- pinned defect")
    check(rec(GOOD, tags=(None, 20), require_tag=True)["ok"] and rec(GOOD)["ok"],
          "one tag is enough for require_tag, and the pure default does not require one")

    check(rec(GOOD, control=730)["ok"], "an extract equal to the control total passes")
    ctrl = rec(GOOD, control=731)
    check(not ctrl["ok"] and "CONTROL" in text_of(ctrl),
          "an extract one person off the control total is refused")
    ctrl_low = rec(GOOD, control=729)
    check(not ctrl_low["ok"] and "the extract holds 730 total but the control total is 729"
          in text_of(ctrl_low),
          "an extract one person ABOVE the control total is refused too, not only one below  "
          "<-- pinned defect")

    mixed = dict(blocks)
    mixed["98002000100" + "1000"] = {"total": 9, "arealand": 9}
    foreign_extract = reconcile(mixed, cols, "total", dict(GOOD), "2020", "99001", (None, None))
    check(not foreign_extract["ok"] and "extract block(s) are outside county 99001" in
          text_of(foreign_extract) and "UNASSIGNED" not in text_of(foreign_extract),
          "an extract block outside the county is refused as a county error, not as a lost "
          "block")
    foreign_assign = rec(GOOD + [("98002000100" + "1000", "1")])
    check(not foreign_assign["ok"] and "assignment block(s) are outside" in
          text_of(foreign_assign) and "ORPHAN" not in text_of(foreign_assign),
          "an assignment block outside the county is a county error, not a vintage one")
    nothing = reconcile({}, cols, "total", {}, "2020", "99001", (None, None))
    check(not nothing["ok"] and "EMPTY" in text_of(nothing),
          "an empty extract is refused, not reconciled as 0 equals 0  <-- pinned defect")

    check([is_null_label(x) for x in
           ("0", "000", "-1", " NULL ", "None", "NaN", "n/a", "Unassigned", "unknown")] == [True] * 9 and
          not any(is_null_label(x) for x in ("1", "10", "A", "01", "-2", "")),
          "the labels GIS tools write for no district are recognised, and real districts are not")
    null_report = rec([(G1, "1"), (G2, "1"), (G3, "2"), (G4, "2"), (G5, "2"), (G6, "0")])
    check(not null_report["ok"] and "NULL-DISTRICT: 1 block(s) hold the district label(s) 0, "
          "holding 30 total" in text_of(null_report),
          "a district 0 that holds blocks is refused, with its block and people counts  "
          "<-- pinned defect")
    check(rec(GOOD)["ok"] and "NULL-DISTRICT" not in text_of(rec(GOOD)),
          "and an assignment with no such label is not")

    # ---- a path with an accent must not crash a strict ASCII stdout
    check(safe("caf\u00e9.csv") == "caf\\xe9.csv" and safe("plain.csv") == "plain.csv",
          "a path with an accented letter is printed escaped, so an ASCII pipe cannot raise  "
          "<-- pinned defect")
    # ---- reading tables
    BOM = b"\xef\xbb\xbf"
    parse = parse_table
    h, body = parse(BOM + b"GeoID , Total\r\n" + G1.encode() + b",5\r\n\r\n", "t")
    check(h == ["geoid", "total"] and len(body) == 1,
          "a BOM, CRLF line ends, padded and capitalised names, and a blank line are all read")
    raises(lambda: parse(b"\xff\xfe", "t"), "a file that is not UTF-8 is refused", InputError)
    raises(lambda: parse(b"a,b\n1,\x002\n", "t"), "a NUL byte is refused", InputError)
    raises(lambda: parse(b"", "t"), "an empty file is refused", InputError)
    raises(lambda: parse(b"\n\n", "t"), "a file of blank lines is refused", InputError)
    raises(lambda: parse(b"a,a\n1,2\n", "t"), "a repeated column name is refused", InputError)
    raises(lambda: parse(b"a,\n1,2\n", "t"), "an empty column name is refused", InputError)
    raises(lambda: parse("a,caf\u00e9\n1,2\n".encode("utf-8"), "t"),
           "a non-ASCII column name is refused", InputError)
    raises(lambda: parse(b"a,b\n1\n", "t"), "a short row is refused, not padded", InputError)
    raises(lambda: parse(b"a,b\n1,2,3\n", "t"), "a long row is refused", InputError)
    raises(lambda: parse(b"a\n" + b"x" * 200000 + b"\n", "t"),
           "a field past the csv module's limit is refused with one line", InputError)

    def blocks_of(text):
        head, rows = parse(text.encode("utf-8"), "b")
        return load_blocks(head, rows, "total", "b")

    got_b, got_cols, got_tag = blocks_of("GEOID20,total,arealand\n%s,5,7\n" % G1)
    check(got_b == {G1: {"total": 5, "arealand": 7}} and got_cols == ["total", "arealand"]
          and got_tag == 20, "a GEOID20 extract loads and reports its vintage tag")
    check(blocks_of("geoid,total\n%s,5\n" % G1)[2] is None, "a plain geoid header has no tag")
    raises(lambda: blocks_of("name,total\nx,5\n"), "an extract without a geoid column is refused",
           InputError)
    raises(lambda: blocks_of("geoid,geoid20,total\n%s,%s,5\n" % (G1, G1)),
           "an extract with two geoid columns is refused", InputError)
    raises(lambda: blocks_of("geoid,pop\n%s,5\n" % G1),
           "an extract without the count column is refused", InputError)
    raises(lambda: blocks_of("geoid,total,district\n%s,5,1\n" % G1),
           "an extract with a column called district is refused, because the summary uses it",
           InputError)
    raises(lambda: blocks_of("geoid,total\n%s,5.0\n" % G1),
           "a count of 5.0 is refused, not truncated", InputError)
    raises(lambda: blocks_of("geoid,total\n%s,1,000\n" % G1), "a count with a comma is refused",
           InputError)
    raises(lambda: blocks_of("geoid,total\n%s,-1\n" % G1), "a negative count is refused",
           InputError)
    raises(lambda: blocks_of("geoid,total\n%s,5\n%s,6\n" % (G1, G1)),
           "a block twice in the extract is refused, not overwritten  <-- pinned defect",
           InputError)
    raises(lambda: blocks_of("geoid,total\n%s,5\n" % G1[1:]),
           "a 14 digit GEOID in the extract is refused with its line number", InputError)

    def assignment_of(text):
        head, rows = parse(text.encode("utf-8"), "a")
        return load_assignment(head, rows, "a")

    a_assign, a_rep, a_con, a_tag = assignment_of("geoid10,district\n%s, 3 \n" % G1)
    check(a_assign == {G1: "3"} and a_tag == 10, "an assignment loads and strips the district")
    raises(lambda: assignment_of("geoid\n%s\n" % G1), "an assignment without district is refused",
           InputError)
    raises(lambda: assignment_of("geoid,district\n%s,\n" % G1),
           "a blank district is refused, not read as district ''", InputError)
    raises(lambda: assignment_of("geoid,district\n%s,D\u00e9\n" % G1),
           "a non-ASCII district is refused", InputError)
    raises(lambda: assignment_of("geoid,district\n%s,\uff1dA\n" % G1),
           "a full-width equals sign in a district is refused as non-ASCII, so OWASP's full-width "
           "formula characters cannot reach the output", InputError)
    raises(lambda: assignment_of("geoid,district\n%s,A\tB\n" % G1),
           "a tab inside a district is refused as not printable", InputError)
    raises(lambda: parse(("geoid,\uff1dtotal\n%s,1\n" % G1).encode("utf-8"), "t"),
           "and so is a full-width formula character in a column name", InputError)
    check(assignment_of("geoid,district\n%s,nan\n%s,01\n%s,1\n" % (G1, G2, G3))[0] ==
          {G1: "nan", G2: "01", G3: "1"},
          "documented limit: nan is a district of its own, and 01 and 1 are two districts")

    def parts_of(text):
        head, rows = parse(text.encode("utf-8"), "p")
        return load_parts(head, rows, "p")

    p_assign, p_info, p_tag = parts_of("geoid,district,area\n%s,1,2.5\n%s,2,4\n" % (G1, G1))
    check(p_assign == {G1: "2"} and p_tag is None and p_info["split"] == {G1: 2},
          "parts load and the larger piece wins")
    raises(lambda: parts_of("geoid,district\n%s,1\n" % G1), "parts without area are refused",
           InputError)
    raises(lambda: parts_of("geoid,district,area\n%s,1,wide\n" % G1),
           "a text area is refused", InputError)
    raises(lambda: parts_of("geoid,district,area\n%s,1,nan\n" % G1),
           "an area of nan is refused, because it compares false to everything  "
           "<-- pinned defect", InputError)
    raises(lambda: parts_of("geoid,district,area\n%s,1,inf\n" % G1),
           "an infinite area is refused", InputError)
    raises(lambda: parts_of("geoid,district,area\n%s,1,-3\n" % G1),
           "a negative area is refused", InputError)
    check(parts_of("geoid,district,area\n%s,1,1_0\n" % G1)[0] == {G1: "1"},
          "documented limit: float() reads 1_0 as an area, unlike the strict GEOID and count rules")

    # ---- the CSV that pl94 writes is the input, and a leading zero must survive
    PL94_HEAD = ("geoid,arealand,areawatr,total,white,black,aian,asian,nhpi,other,"
                 "two_or_more,hispanic_any_race,housing_units,occupied,vacant")
    z1, z2 = "09999" + "000100" + "1000", "09999" + "000100" + "1001"
    zhead, zbody = parse(
        (PL94_HEAD + "\n%s,10,0,7,3,2,0,1,0,0,1,2,4,3,1\n%s,5,5,0,0,0,0,0,0,0,0,0,0,0,0\n"
         % (z1, z2)).encode("utf-8"), "pl94.csv")
    zblocks, zcols, ztag = load_blocks(zhead, zbody, "total", "pl94.csv")
    check(len(zcols) == 14 and zblocks[z1]["housing_units"] == 4 and ztag is None,
          "the 15 column CSV that pl94 writes loads, with its 14 count columns")
    zrep = reconcile(zblocks, zcols, "total", {z1: "1", z2: "1"}, "2020", "09999", (None, None))
    check(zrep["ok"] and zrep["districts"][0][1]["total"] == 7 and z1.startswith("09"),
          "a state FIPS that starts with 0 survives as text and the extract reconciles")

    # ---- the formula guard: a text cell that starts with =, +, -, @, tab, CR or LF
    for lead, name in (("=", "an equals sign"), ("+", "a plus sign"), ("-", "a minus sign"),
                       ("@", "an at sign"), ("\t", "a tab"), ("\r", "a carriage return"),
                       ("\n", "a line feed")):
        check(cell(lead + "x") == "'" + lead + "x",
              "a text cell that starts with %s gets one apostrophe in front  <-- pinned defect"
              % name)
        check(uncell(cell(lead + "x")) == lead + "x",
              "and reading it back removes exactly that apostrophe, for %s" % name)
    check(cell("plain") == "plain" and cell("") == "" and cell("a=b") == "a=b"
          and cell("a-1") == "a-1" and cell("1-2") == "1-2",
          "a text that does not start with a formula character is left alone, whatever it holds")
    check(cell(7) == 7 and type(cell(7)) is int and cell(0) == 0 and cell(-5) == -5
          and type(cell(-5)) is int,
          "a number is not a text cell and stays a number, so a count column stays numeric")
    check(cell("'abc") == "'abc" and cell("'") == "'" and cell("''") == "''",
          "an apostrophe that is not followed by a formula character is a plain label")
    check(cell("'=x") == "''=x" and cell("''-x") == "'''-x",
          "a label that is itself an apostrophe and a formula character gets a second "
          "apostrophe, so it is not mistaken for an escaped one  <-- pinned defect")
    check(uncell("'abc") == "'abc" and uncell("'") == "'" and uncell("=x") == "=x"
          and uncell("''=x") == "'=x" and uncell("'=x") == "=x",
          "uncell removes one apostrophe only when a formula character follows the apostrophes")
    labels = ["=A", "+1", "-1", "@x", "\tt", "\rr", "\nn", "'=C", "''=C", "'", "''", "'a", "a'",
              "'+", "'-1", "a=b", "", "=", "-", "''@", "'\t"]
    check(all(uncell(cell(text)) == text for text in labels),
          "uncell(cell(x)) gives x back for 21 awkward labels, apostrophes included  "
          "<-- pinned defect")
    check(len(set(cell(text) for text in labels)) == len(labels),
          "and no two of those labels are written as the same text")
    check(cell_district(["'=A"], 0, "t", 1) == "=A" and cell_district([" '-1 "], 0, "t", 1) == "-1"
          and cell_district(["''=A"], 0, "t", 1) == "'=A" and cell_district(["'a"], 0, "t", 1) == "'a",
          "a district cell is stripped of its whitespace and of the one apostrophe write_csv adds")
    check(cell_district(["\t=A"], 0, "t", 1) == "=A" and cell_district(["\r@A"], 0, "t", 1) == "@A",
          "a leading tab or carriage return is stripped on read, so the formula character it hid "
          "is then guarded on write")

    # ---- the files for the command line half
    tmp = tempfile.mkdtemp(prefix="blockfit-")

    def put(name, text):
        path = os.path.join(tmp, name)
        with open(path, "wb") as fh:
            fh.write(text.encode("utf-8"))
        return path

    def listing():
        return sorted(os.listdir(tmp))

    def slurp(path):
        """The bytes of path, or b'' when it is missing, so a broken tool fails a check."""
        try:
            with open(path, "rb") as fh:
                return fh.read()
        except OSError:
            return b""

    check(slurp(os.path.join(tmp, "nothing-here")) == b"",
          "the harness reads a missing file as empty, so a broken tool fails a check and does "
          "not crash the run")

    block_text = "geoid,total,arealand\n" + "".join("%s,%d,%d\n" % row for row in BLOCKS)
    assign_text = "geoid,district\n" + "".join("%s,%s\n" % row for row in GOOD)
    parts_text = "geoid,district,area\n" + "".join("%s,%s,%s\n" % row for row in PIECES)
    f_blocks = put("blocks.csv", block_text)
    f_assign = put("assign.csv", assign_text)
    f_parts = put("parts.csv", parts_text)
    f_lost = put("lost.csv", assign_text.replace("%s,2\n" % G4, ""))
    f_old = put("old.csv", "".join(
        l if G4 not in l and G5 not in l else l.replace(G4[-4:], "9100").replace(G5[-4:], "9200")
        for l in assign_text.splitlines(True)))
    f_dup = put("dup.csv", assign_text + "%s,1\n%s,1\n" % (G1, G3))
    f_tag10 = put("tag10.csv", assign_text.replace("geoid", "geoid10", 1))
    f_bigdist = put("bigdist.csv", assign_text.replace(",1\n", ",%s\n" % ("7" * 5000)))
    f_tag20 = put("tag20.csv", assign_text.replace("geoid", "geoid20", 1))
    f_null = put("null-district.csv", assign_text.replace("%s,2\n" % G4, "%s,0\n" % G4))
    before = listing()

    def run(argv, out=None):
        """-> (exit code, stdout text, stderr text). argparse writes to sys.stderr itself."""
        out = io.StringIO() if out is None else out
        err = io.StringIO()
        try:
            with contextlib.redirect_stderr(err):
                code = main(argv, out, err)
        except SystemExit as exc:
            code = exc.code
        text = out.getvalue() if isinstance(out, io.StringIO) and not out.closed else ""
        return code, text, err.getvalue()

    base = ["--blocks", f_blocks, "--year", "2020", "--county", "99001", "--trust-year"]

    # ---- the whole command line must make no network call
    net_calls = []

    def no_net(*args, **kwargs):
        net_calls.append(args)
        raise OSError("blockfit self-test: the network is off")

    saved = (socket.socket, socket.getaddrinfo, socket.create_connection)
    socket.socket = no_net
    socket.getaddrinfo = no_net
    socket.create_connection = no_net
    try:
        raises(lambda: socket.create_connection(("blockfit.invalid", 80)),
               "the network trap itself fires when something dials out", OSError)
        check(len(net_calls) == 1, "and it recorded the attempt")
        del net_calls[:]
        code, out, err = run(base + ["--assignment", f_assign])
        check(code == EXIT_UNVERIFIED and "RECONCILED" in out and err == "",
              "a complete assignment exits 0 and prints RECONCILED")
        rows = [line.split() for line in out.splitlines()]
        check(["DISTRICT", "BLOCKS", "total", "arealand"] in rows and
              ["1", "2", "300", "3000"] in rows and ["2", "4", "430", "8100"] in rows,
              "the district table is printed")
        check("districts 730 / extract 730" in out and "districts 11100 / extract 11100" in out,
              "and the district sum is printed beside the extract sum for every column")
        check("blocks in the extract       : 6" in out and "blocks in the assignment    : 6" in out
              and "blocks in both              : 6" in out,
              "and the three block counts are printed")
        check(listing() == before, "a run without --apply writes nothing at all  <-- pinned defect")

        code, out, err = run(base + ["--assignment", f_lost])
        check(code == 1 and "REFUSED: 1 reason(s)" in out and "350 total" in out,
              "an assignment that loses the water block exits 1 and names the 350 people")
        check("districts 380 / extract 730" in out,
              "and prints the short district sum against the extract")

        code, out, err = run(base + ["--assignment", f_old])
        check(code == 1 and "VINTAGE" in out and "Both files must use the 2020 blocks" in out,
              "an assignment on the wrong block set exits 1 and names the vintage")
        check("blocks in the assignment    : 6" in out and "blocks in both              : 4" in out,
              "and the blocks in both files are counted as 4, not as every assignment block  "
              "<-- pinned defect")

        code, out, err = run(base + ["--assignment", f_dup])
        check(code == 1 and "REPEATED" in out, "a repeated block exits 1")

        code, out, err = run(["--blocks", f_blocks, "--year", "2010", "--county", "99001",
                              "--trust-year", "--assignment", f_tag10])
        check(code == 0, "a GEOID10 assignment against --year 2010 reconciles")
        code, out, err = run(base + ["--assignment", f_tag10])
        check(code == 1 and "VINTAGE: the assignment header says GEOID10 but --year is 2020" in out,
              "and against --year 2020 it is refused  <-- pinned defect")
        code, out, err = run(["--blocks", f_blocks, "--year", "2010", "--county", "99001",
                              "--trust-year", "--assignment", f_assign])
        check(code == 3 and EXIT_UNVERIFIED == 3 and "2010 blocks" in out,
              "plain geoid headers carry no vintage, so --year 2010 reconciles but exits 3, not 0, "
              "because the tool could not tell  <-- pinned defect")
        check("vintage: not verified" in out and "2010 is your claim, not a finding" in out,
              "and the report says the vintage was not verified  <-- pinned defect")
        check("RECONCILED (vintage not verified): every block" in out,
              "and the verdict line carries the same words, so a log that keeps only the verdict "
              "keeps the caveat  <-- pinned defect")
        wrong = ["--blocks", f_blocks, "--year", "2010", "--county", "99001"]
        code, out, err = run(wrong + ["--assignment", f_assign])
        check(code == 1 and "UNVERIFIED-VINTAGE" in out and "RECONCILED" not in out,
              "plain geoid headers and no --trust-year exit 1, so a wrong --year cannot exit 0  "
              "<-- pinned defect")
        unv = os.path.join(tmp, "unverified.csv")
        code, out, err = run(wrong + ["--assignment", f_assign, "--out", unv, "--apply"])
        check(code == 1 and not os.path.exists(unv) and "nothing written" in err,
              "and --apply writes nothing for it  <-- pinned defect")
        code, out, err = run(["--blocks", f_blocks, "--year", "2020", "--county", "99001",
                              "--assignment", f_tag20])
        check(code == 0 and "vintage: not verified" not in out and "RECONCILED: every block" in out,
              "one header tag is enough to call the vintage checked, and the verdict says plain "
              "RECONCILED")
        code, out, err = run(base + ["--assignment", f_null])
        check(code == 1 and "NULL-DISTRICT: 1 block(s)" in out and "RECONCILED" not in out,
              "a block given district 0 is refused on the command line, not reconciled with a "
              "phantom district  <-- pinned defect")
        code, out, err = run(base + ["--assignment", f_bigdist])
        check(code == EXIT_UNVERIFIED and "RECONCILED" in out,
              "a district label of 5000 digits reconciles and does not end in a traceback  "
              "<-- pinned defect")

        code, out, err = run(base + ["--assignment", f_assign, "--control-total", "730"])
        check(code == EXIT_UNVERIFIED and "extract 730 / control 730" in out, "a matching control total passes")
        code, out, err = run(base + ["--assignment", f_assign, "--control-total", "7300"])
        check(code == 1 and "CONTROL" in out, "a wrong control total exits 1")

        code, out, err = run(base + ["--parts", f_parts])
        check(code == EXIT_UNVERIFIED and "RECONCILED" in out,
              "pieces that cover every block reconcile, including the water block the "
              "centroid rule lost")
        check("blocks split across districts: 2, holding 230 total" in out and
              "ties on area broken by the lowest district: 1" in out and
              "pieces with zero area ignored: 1" in out,
              "and the split blocks, the tie and the ignored piece are reported")
        check(listing() == before, "a --parts run without --apply writes nothing")
        code, out, err = run(base + ["--parts", put("p2.csv", parts_text.replace(
            "%s,2,800\n" % G4, ""))])
        check(code == 1 and "350 total" in out,
              "pieces with no part for the water block are refused like a lost block")

        # --- writing
        o1 = os.path.join(tmp, "districts.csv")
        o2 = os.path.join(tmp, "assigned.csv")
        before2 = listing()
        code, out, err = run(base + ["--assignment", f_assign, "--out", o1])
        check(code == 64 and "need --apply" in err and listing() == before2,
              "--out without --apply is a usage error and writes nothing")
        code, out, err = run(base + ["--assignment", f_assign, "--out", o1, "--apply"])
        written = slurp(o1)
        check(code == EXIT_UNVERIFIED and written == (b"district,blocks,total,arealand\n"
                                        b"1,2,300,3000\n2,4,430,8100\n"),
              "--apply writes the district table, with LF line ends on every host")
        check("wrote " in out and o1 in out, "and says what it wrote")
        code, out, err = run(base + ["--assignment", f_lost, "--out", o1, "--apply"])
        kept = slurp(o1)
        check(code == 1 and kept == written and "nothing written" in err,
              "--apply does NOT overwrite the table when the check refused  "
              "<-- pinned defect")
        check("--allow-unreconciled" in err, "and the message names the flag that would override it")
        code, out, err = run(base + ["--assignment", f_lost, "--out", o1, "--apply",
                                     "--allow-unreconciled"])
        forced = slurp(o1)
        check(code == 1 and forced != written and b"1,2,300,3000\n2,3,80,4100\n" in forced,
              "--allow-unreconciled writes the short table anyway")
        check(code == 1, "and still exits 1, because the extract is still wrong  "
              "<-- pinned defect")
        code, out, err = run(base + ["--parts", f_parts, "--out", o1, "--assign-out", o2,
                                     "--apply"])
        assigned = slurp(o2)
        check(code == EXIT_UNVERIFIED and assigned == (
            ("geoid,district\n" + "".join("%s,%s\n" % (k, v) for k, v in sorted(
                [(G1, "1"), (G2, "1"), (G3, "2"), (G4, "2"), (G5, "2"), (G6, "1")]))).encode()),
            "--assign-out writes the largest-overlap assignment, sorted by GEOID")
        code, out, err = run(base + ["--parts", f_parts, "--assign-out", o2])
        check(code == 64, "--assign-out also needs --apply")
        o5 = os.path.join(tmp, "only-assigned.csv")
        code, out, err = run(base + ["--parts", f_parts, "--assign-out", o5, "--apply"])
        check(code == EXIT_UNVERIFIED and os.path.exists(o5) and not os.path.exists(o1.replace(
            "districts", "never-made")) and "districts.csv" not in out,
              "--assign-out alone writes the assignment and no district table")
        f_sblocks = put("sort-blocks.csv", "geoid,total\n%s,4\n%s,3\n%s,2\n%s,1\n" %
                        (G4, G3, G2, G1))
        f_sparts = put("sort-parts.csv",
                       "geoid,district,area\n%s,A,1\n%s,10,1\n%s,2,1\n%s,1,1\n" % (G4, G3, G2, G1))
        o6 = os.path.join(tmp, "sorted-districts.csv")
        o7 = os.path.join(tmp, "sorted-assigned.csv")
        code, out, err = run(["--blocks", f_sblocks, "--year", "2020", "--county", "99001", "--trust-year",
                              "--parts", f_sparts, "--out", o6, "--assign-out", o7, "--apply"])
        check(code == EXIT_UNVERIFIED and slurp(o6) == b"district,blocks,total\n1,1,1\n2,1,2\n10,1,3\nA,1,4\n",
              "--out sorts whole numbers as numbers, then text: 1, 2, 10, A, from rows given "
              "as A, 10, 2, 1  <-- pinned defect")
        check(slurp(o7) == ("geoid,district\n%s,1\n%s,2\n%s,10\n%s,A\n" %
                            (G1, G2, G3, G4)).encode(),
              "--assign-out sorts by GEOID however the pieces were ordered  <-- pinned defect")
        # the assignment that --assign-out wrote goes back through the check
        code, out, err = run(base + ["--assignment", o2])
        check(code == EXIT_UNVERIFIED, "and the file it wrote reconciles when read back as an assignment")

        # --- formula guard on the written files
        def formulas(path):
            """Every text cell in the CSV at path that a spreadsheet would run as a formula."""
            reader = csv.reader(io.StringIO(slurp(path).decode("utf-8"), newline=""))
            return [c for row in reader for c in row if c[:1] in FORMULA_LEADS]

        f_fblocks = put("formula-blocks.csv", block_text.replace("arealand", "=sum"))
        f_fparts = put("formula-parts.csv", "geoid,district,area\n" + "".join(
            "%s,%s,1\n" % pair for pair in (
                (G1, "=A"), (G2, "-B"), (G3, "''=C"), (G4, "+D"), (G5, '"\r@E"'),
                (G6, "\t=F"))))
        o10 = os.path.join(tmp, "formula-districts.csv")
        o11 = os.path.join(tmp, "formula-assigned.csv")
        fbase = ["--blocks", f_fblocks, "--year", "2020", "--county", "99001", "--trust-year"]
        code, out, err = run(fbase + ["--parts", f_fparts, "--out", o10, "--assign-out", o11,
                                      "--apply"])
        check(code == EXIT_UNVERIFIED and "RECONCILED" in out and err == "",
              "an overlay whose district labels start with =, +, -, @, a tab, a carriage return "
              "and an apostrophe reconciles and writes both files")
        check(slurp(o10) == (b"district,blocks,total,'=sum\n''=C,1,50,3000\n'+D,1,350,4000\n"
                             b"'-B,1,200,2000\n'=A,1,100,1000\n'=F,1,30,600\n'@E,1,0,500\n"),
              "--out puts one apostrophe before each district label that starts with a formula "
              "character, and before a count column named =sum  <-- pinned defect")
        check(slurp(o11) == (("geoid,district\n%s,'=A\n%s,'-B\n%s,''=C\n%s,'+D\n%s,'@E\n%s,'=F\n"
                              % (G1, G2, G3, G4, G5, G6)).encode()),
              "--assign-out guards the district column too, and leaves the geoid column and the "
              "header alone  <-- pinned defect")
        check(formulas(o10) == [] and formulas(o11) == [],
              "no cell in either file starts with a formula character")
        check(all(is_digits(c) for row in list(csv.reader(io.StringIO(
            slurp(o10).decode("utf-8"), newline="")))[1:] for c in row[1:]),
              "and the block and count columns are bare numbers with no apostrophe")
        o12 = os.path.join(tmp, "formula-districts-2.csv")
        code, out, err = run(fbase + ["--assignment", o11, "--out", o12, "--apply"])
        check(code == EXIT_UNVERIFIED and "RECONCILED" in out and slurp(o12) == slurp(o10),
              "the guarded --assign-out reads back as --assignment, gives the same district "
              "table byte for byte, and no label collapses into another  <-- pinned defect")
        check("  =A  " in out and "  '=C " in out and "'=A" not in out and "''=C" not in out,
              "and the report shows the real labels, =A and '=C, not the escaped ones")
        check(formulas(o12) == [], "and the second table is guarded as well")

        # The README's formula example: the same bytes, so the quoted files are a real run.
        g0, g1, g2 = "990010001001000", "990010001001001", "990010001001002"
        f_rb = put("readme-b.csv", "geoid,total\n%s,100\n%s,20\n%s,3\n" % (g0, g1, g2))
        f_rp = put("readme-p.csv", "geoid,district,area\n%s,=SUM(A1),1\n%s,-2,1\n%s,Ward 3,1\n"
                   % (g0, g1, g2))
        o13 = os.path.join(tmp, "readme-o.csv")
        o14 = os.path.join(tmp, "readme-a.csv")
        code, out, err = run(["--blocks", f_rb, "--parts", f_rp, "--year", "2020", "--county",
                              "99001", "--trust-year", "--out", o13, "--assign-out", o14,
                              "--apply"])
        check(code == EXIT_UNVERIFIED and slurp(o13) == (b"district,blocks,total\n'-2,1,20\n'=SUM(A1),1,100\n"
                                           b"Ward 3,1,3\n") and
              slurp(o14) == ("geoid,district\n%s,'=SUM(A1)\n%s,'-2\n%s,Ward 3\n"
                             % (g0, g1, g2)).encode(),
              "the README's formula example writes exactly the two files the README shows")

        # --- usage errors
        def usage(argv, label):
            code, out, err = run(argv)
            check(code == 64 and err.startswith("blockfit: usage:") and out == "", label)

        usage(["--year", "2020", "--county", "99001", "--assignment", f_assign],
              "a missing --blocks is a usage error")
        usage(["--blocks", f_blocks, "--county", "99001", "--assignment", f_assign],
              "a missing --year is a usage error")
        usage(["--blocks", f_blocks, "--year", "2020", "--assignment", f_assign],
              "a missing --county is a usage error, with no default county  <-- pinned defect")
        usage(base, "neither --assignment nor --parts is a usage error")
        usage(base + ["--assignment", f_assign, "--parts", f_parts],
              "both --assignment and --parts is a usage error")
        usage(["--blocks", f_blocks, "--year", "2000", "--county", "99001",
               "--assignment", f_assign], "--year 2000 is a usage error")
        usage(["--blocks", f_blocks, "--year", "2020", "--county", "9900",
               "--assignment", f_assign], "a four digit county is a usage error")
        usage(["--blocks", f_blocks, "--year", "2020", "--county", "9900\u0661",
               "--assignment", f_assign], "an Arabic-Indic digit in --county is a usage error")
        usage(base + ["--assignment", f_assign, "--control-total", "7.5"],
              "a fractional --control-total is a usage error")
        usage(base + ["--assignment", f_assign, "--apply"],
              "--apply with no output path is a usage error")
        usage(base + ["--assignment", f_assign, "--assign-out", o2, "--apply"],
              "--assign-out with --assignment is a usage error")
        usage(["--blocks", f_blocks, "--year", "2020", "--county", "990010",
               "--assignment", f_assign], "a six digit county is a usage error, not a sub-area "
              "filter  <-- pinned defect")
        # These probes run on disposable copies, so a broken guard cannot damage a fixture the
        # later steps need. It turns the probes red instead of crashing the run.
        c_blocks = put("victim-blocks.csv", block_text)
        c_assign = put("victim-assign.csv", assign_text)
        c_parts = put("victim-parts.csv", parts_text)
        cbase = ["--blocks", c_blocks, "--year", "2020", "--county", "99001", "--trust-year"]
        usage(cbase + ["--assignment", c_assign, "--out", c_blocks, "--apply"],
              "--out equal to --blocks is a usage error, not an overwrite  <-- pinned defect")
        usage(cbase + ["--assignment", c_assign, "--out", c_assign, "--apply"],
              "--out equal to --assignment is a usage error")
        usage(cbase + ["--parts", c_parts, "--assign-out", c_parts, "--apply"],
              "--assign-out equal to --parts is a usage error")
        usage(cbase + ["--parts", c_parts, "--out", o1, "--assign-out", o1, "--apply"],
              "--out and --assign-out equal is a usage error")
        usage(cbase + ["--assignment", c_assign, "--out",
                       os.path.join(tmp, ".", "victim-assign.csv"), "--apply"],
              "an output that reaches an input through ./ is caught too")
        check(slurp(c_blocks) == block_text.encode() and slurp(c_assign) == assign_text.encode()
              and slurp(c_parts) == parts_text.encode(),
              "and none of those probes touched its input")

        # --- flags must be spelled out
        for flag in ("--ap", "--app", "--appl", "--allow", "--allow-unrec", "--assign"):
            before3 = listing()
            code, out, err = run(base + ["--assignment", f_assign, "--out", o1, flag])
            check(code == 2 and listing() == before3 and "unrecognized" in err,
                  "%s is refused by the parser with exit 2 and writes nothing  "
                  "<-- pinned defect" % flag)
        check(_parse(["--apply"]).apply is True and _parse([]).apply is False,
              "--apply is off by default and on when spelled out")
        check(_parse([]).allow_unreconciled is False and _parse([]).county is None
              and _parse([]).measure == "total", "no other flag has a surprising default")

        # --- unreadable inputs and unwritable outputs
        code, out, err = run(base + ["--assignment", os.path.join(tmp, "missing.csv")])
        check(code == 2 and "cannot read" in err and out == "",
              "a missing assignment exits 2 with one line")
        code, out, err = run(base + ["--assignment", tmp])
        check(code == 2 and "cannot read" in err, "a directory in place of a file exits 2")
        code, out, err = run(["--blocks", f_assign, "--year", "2020", "--county", "99001",
                              "--assignment", f_assign])
        check(code == 2 and "district table uses" in err,
              "an assignment file given as the extract exits 2 with the reason")
        code, out, err = run(base + ["--assignment", f_assign, "--measure", "pop"])
        check(code == 2 and "no 'pop' column" in err, "a --measure the extract lacks exits 2")
        code, out, err = run(base + ["--assignment", f_assign, "--measure", "arealand",
                                     "--control-total", "11100"])
        check(code == EXIT_UNVERIFIED and "arealand       extract 11100 / control 11100" in out,
              "a --measure naming another count column reconciles and checks the control on it")
        code, out, err = run(base[:1] + [put("w.csv", "geoid,total\n%s,x\n" % G1)] + base[2:] +
                             ["--assignment", f_assign])
        check(code == 2 and "not a whole number" in err, "a malformed count exits 2")
        code, out, err = run(base + ["--parts", put("bad.csv", "geoid,district,area\n")])
        check(code == 1 and "ORPHAN" not in out and "UNASSIGNED" in out,
              "a parts file with a header and no rows is a refusal, not a crash")

        badpath = os.path.join(tmp, "nodir", "x.csv")
        code, out, err = run(base + ["--assignment", f_assign, "--out", badpath, "--apply"])
        check(code == 2 and "cannot write" in err and "RECONCILED" in out,
              "an unwritable --out exits 2, after the report was printed")
        code, out, err = run(base + ["--parts", f_parts, "--out", o1,
                                     "--assign-out", badpath, "--apply"])
        check(code == 2, "an unwritable --assign-out exits 2")

        class Pipe(object):
            def __init__(self, fail_write):
                self.fail_write = fail_write

            def write(self, text):
                if self.fail_write:
                    raise BrokenPipeError(32, "Broken pipe")

            def flush(self):
                raise OSError(5, "flush failed")

        before4 = listing()
        o3 = os.path.join(tmp, "never.csv")
        code, out, err = run(base + ["--assignment", f_assign, "--out", o3, "--apply"],
                             out=Pipe(True))
        check(code == 2 and "cannot write the report" in err and listing() == before4,
              "a closed pipe exits 2 and the CSV is not written  <-- pinned defect")
        code, out, err = run(base + ["--assignment", f_assign, "--out", o3, "--apply"],
                             out=Pipe(False))
        check(code == 2 and listing() == before4, "a report that cannot be flushed exits 2 too")
        dead = io.StringIO()
        dead.close()
        code, out, err = run(base + ["--assignment", f_lost], out=dead)
        check(code == 2, "a closed stdout object exits 2, not 1, even on a refused run")
    finally:
        socket.socket, socket.getaddrinfo, socket.create_connection = saved
    check(net_calls == [], "the whole command line half made no network call")

    # ---- the real command line, as a separate process
    secret = "blockfit-canary-7f3a9"
    env = dict(os.environ)
    env["BLOCKFIT_TOKEN"] = secret
    env["PYTHONIOENCODING"] = "ascii"
    script = os.path.abspath(__file__)
    o4 = os.path.join(tmp, "proc.csv")

    def proc(argv):
        done = subprocess.run([sys.executable, script] + argv, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, env=env, cwd=tmp)
        return done.returncode, done.stdout.decode("ascii"), done.stderr.decode("ascii")

    pcode, pout, perr = proc(base + ["--assignment", f_assign, "--out", o4, "--apply"])
    pwrote = slurp(o4)
    check(pcode == EXIT_UNVERIFIED and "RECONCILED" in pout and pwrote == written,
          "the real command line reconciles and writes the same bytes as the in-process run")
    pcode, pout, perr = proc(base + ["--assignment", f_lost, "--out", o4, "--apply"])
    check(pcode == 1 and "REFUSED" in pout, "the real command line exits 1 on a refusal")
    check(slurp(o4) == pwrote, "and leaves the earlier file alone")
    before5 = listing()
    pcode, pout, perr = proc(base + ["--assignment", f_assign, "--out", os.path.join(
        tmp, "pre.csv"), "--ap"])
    check(pcode == 2 and listing() == before5 and "unrecognized" in perr,
          "the real command line refuses --ap with exit 2 and writes nothing  <-- pinned defect")
    f_accent = put("caf\u00e9.csv", assign_text)
    pcode, pout, perr = proc(base + ["--assignment", f_accent])
    check(pcode == EXIT_UNVERIFIED and "caf\\xe9.csv" in pout,
          "a file with an accent in its name reconciles through a strict ASCII stdout  "
          "<-- pinned defect")
    pcode, pout, perr = proc(["--blocks", f_blocks])
    check(pcode == 64, "the real command line exits 64 on a usage error")
    check(secret not in pout + perr and secret.encode() not in pwrote + slurp(o4),
          "an environment variable named TOKEN is not echoed to stdout, stderr or a file")

    # ---- a closed pipe, for real. Python flushes stdout again at shutdown and fails a second
    # time, and then the interpreter exits 120. The fake Pipe above cannot show that.
    rd, wr = os.pipe()
    os.close(rd)
    o8 = os.path.join(tmp, "pipe-never.csv")
    before6 = listing()
    done = subprocess.run([sys.executable, script] + base + ["--assignment", f_assign, "--out", o8,
                                                              "--apply"],
                          stdout=wr, stderr=subprocess.PIPE, env=env, cwd=tmp)
    os.close(wr)
    check(done.returncode == 2 and b"cannot write the report" in done.stderr
          and listing() == before6,
          "a real closed pipe exits 2, not the interpreter's 120, and writes no file  "
          "<-- pinned defect")

    class Gone(object):
        """A stdout whose pipe is closed. fd is the descriptor it reports, or None for none."""

        def __init__(self, fd):
            self.fd = fd

        def write(self, text):
            raise BrokenPipeError(32, "Broken pipe")

        def fileno(self):
            if self.fd is None:
                raise OSError(9, "no descriptor")
            return self.fd

    o9 = os.path.join(tmp, "fd.bin")
    fd = os.open(o9, os.O_WRONLY | os.O_CREAT | getattr(os, "O_BINARY", 0))
    sink = io.StringIO()
    with contextlib.redirect_stdout(Gone(fd)):
        gone_code = main(base + ["--assignment", f_assign], None, sink)
    os.write(fd, b"leak")
    os.close(fd)
    check(gone_code == 2 and slurp(o9) == b"" and "cannot write the report" in sink.getvalue(),
          "after a failed report write the stdout descriptor points at the null device, so the "
          "flush at shutdown cannot fail  <-- pinned defect")
    with contextlib.redirect_stdout(Gone(None)):
        gone_code = main(base + ["--assignment", f_assign], None, sink)
    check(gone_code == 2, "a stdout with no descriptor still exits 2")

    # ---- the standard library only
    import ast
    with open(script, "rb") as fh:
        tree = ast.parse(fh.read())
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module.split(".")[0])
    check(imported == set(["__future__", "argparse", "ast", "contextlib", "csv", "io", "math",
                           "os", "runpy", "shutil", "socket", "subprocess", "sys", "tempfile"]),
          "the file imports only the standard library: no arcpy, no third party package")

    # ---- importing the file must not run it
    import runpy
    quiet = io.StringIO()
    with contextlib.redirect_stdout(quiet):
        namespace = runpy.run_path(script, run_name="blockfit_import")
    check(quiet.getvalue() == "" and callable(namespace["main"]),
          "loading the file as a module prints nothing and does not call main")

    # ---- the harness itself, which has to be able to report red
    def probe():
        check(False, "a false check must be recorded as a failure")
        raises(lambda: None, "a function that raises nothing must fail")
        raises(lambda: 1 / 0, "a function that raises the wrong thing must fail")

    def summary():
        print("-" * 68)
        total = passed[0] + len(failed)
        if failed:
            print("%d assertions, %d failed" % (total, len(failed)))
            for label in failed:
                print("  FAILED: %s" % label)
            return 1
        print("%d assertions, 0 failed" % total)
        return 0

    kept_passed, kept_failed = passed[0], list(failed)
    noise = io.StringIO()
    with contextlib.redirect_stdout(noise):
        probe()
        probe_code = summary()
    probe_failed = len(failed) - len(kept_failed)
    passed[0], failed[:] = kept_passed, kept_failed
    check(probe_failed == 3 and probe_code == 1,
          "the harness records a false check, a missing exception and a wrong exception as "
          "three failures, so a broken tool turns this self-test red  <-- pinned defect")

    shutil.rmtree(tmp, ignore_errors=True)
    return summary()


if __name__ == "__main__":
    sys.exit(main())
