# blockfit

Refuse a block-to-district assignment that does not reconcile to its block extract, or that was
built on a different block vintage. It reads two CSV files and standard-library Python. It never
reads a shapefile.

A district table is built from Census blocks. The usual method takes each block's centroid and asks
which district holds it. A block that is mostly water has its centroid in the water, or just
outside the district tiling. That block is in no district. Its people are in no district either.

The district table still prints. Each district has a believable number. The district numbers add up to a
little less than the county total, and nothing in the job complains. In the fixture below the short
table is 380 against 730. A real county's gap could be a fraction of a percent, small
enough to survive a review and large enough to be wrong. That is an illustration. I did not run a
real county.

The same job can fail a second way. Census redraws its blocks every decade. A district file made
from the 2020 blocks, joined to 2010 people, shares many GEOIDs with the right file and disagrees
about the rest. The join runs. The rows that did not match drop out. The totals are low again, and
the table looks like any other.

blockfit takes the block extract and the assignment, and it refuses unless every block is in exactly
one district, both files name the same blocks, and the district sums equal the extract.

```
$ python blockfit.py --blocks blocks.csv --assignment centroid.csv --year 2020 --county 99001 --trust-year
blockfit: blocks.csv with assignment centroid.csv
  county 99001, 2020 blocks, count column 'total'
  vintage: not verified. Not every header carries a GEOID10 or GEOID20 tag, so 2020 is your claim for the plain file, not a finding.

  blocks in the extract       : 6
  blocks in the assignment    : 5
  blocks in both              : 5

  DISTRICT    BLOCKS        total     arealand
  1                2          300         3000
  2                3           80         4100

  total          districts 380 / extract 730
  arealand       districts 7100 / extract 11100

REFUSED: 1 reason(s)
  1. UNASSIGNED: 1 extract block(s) are in no district, holding 350 total: 990010001001003
```

The exit code is 1. County `99001` does not exist. Every number in this file comes from a synthetic
fixture, so you can run all of it without a download. Most come from the fixture that `--self-test`
builds. The two-file formula example under Output is a second, smaller fixture, and `--self-test`
writes it too and compares the output byte for byte. `--trust-year` is explained under Usage: the two
files here have plain `geoid` headers, so without it the run is also refused for an unverified year.

## The existing tool, and what it does well

[maup](https://github.com/mggg/maup) is the geospatial toolkit for redistricting data, and it is
MIT licensed. Its `assign` function takes two sets of geometries and maps each source geometry to
the target that covers it. When no single target covers a source, `assign` gives it to the target
that covers the largest part of its area. That is the rule blockfit's `--parts` mode applies, and
maup applies it to real geometry with spatial indexes, which blockfit does not do at all. Its
`doctor` function also finds gaps, overlaps and invalid geometry in a shapefile. If you have
geometry and a Python environment with geopandas, use maup to make the assignment.

What blockfit adds is the refusal after the assignment. maup's README shows how to count unassigned
blocks, and it prints the summed block columns and the summed target columns one after the other,
so a reader can compare the two sums by hand. That comparison is the one blockfit makes, as a refusal with an
exit code. maup's README does not describe a check that the sums equal a control total, a check
that the assignment and the extract hold the same blocks, or a check of block vintage. blockfit
makes those checks and nothing else. Read on 2026-10-24; maup may have changed since.

## Self-test

```
$ python blockfit.py --self-test
blockfit self-test: no network, no census download, no arcpy
--------------------------------------------------------------------
...
PASS  an assignment missing the block whose centroid fell on water is refused and reports the 350 people it lost  <-- pinned defect
...
PASS  the district sums add to 380, not the extract's 730, with no error from the arithmetic  <-- pinned defect
PASS  a block with no people missing from the assignment is refused although the people still add up  <-- pinned defect
...
PASS  blocks missing on one side and extra on the other are called a vintage mismatch  <-- pinned defect
...
PASS  a GEOID10 extract against --year 2020 is refused  <-- pinned defect
...
PASS  with require_tag, two plain headers are refused because the vintage cannot be checked  <-- pinned defect
...
PASS  an extract one person ABOVE the control total is refused too, not only one below  <-- pinned defect
...
PASS  an empty extract is refused, not reconciled as 0 equals 0  <-- pinned defect
...
PASS  a district 0 that holds blocks is refused, with its block and people counts  <-- pinned defect
PASS  a district NA, which R writes for a missing value, is refused  <-- pinned defect
...
PASS  a text cell that starts with an equals sign gets one apostrophe in front  <-- pinned defect
...
PASS  a label that is itself an apostrophe and a formula character gets a second apostrophe, so it is not mistaken for an escaped one  <-- pinned defect
...
PASS  uncell(cell(x)) gives x back for 21 awkward labels, apostrophes included  <-- pinned defect
...
PASS  a run without --apply writes nothing at all  <-- pinned defect
...
PASS  and the report says the vintage was not verified  <-- pinned defect
PASS  and the verdict line carries the same words, so a log that keeps only the verdict keeps the caveat  <-- pinned defect
PASS  plain geoid headers and no --trust-year exit 1, so a wrong --year cannot exit 0  <-- pinned defect
...
PASS  a block given district 0 is refused on the command line, not reconciled with a phantom district  <-- pinned defect
PASS  a district label of 5000 digits reconciles and does not end in a traceback  <-- pinned defect
...
PASS  --apply does NOT overwrite the table when the check refused  <-- pinned defect
...
PASS  and still exits 1, because the extract is still wrong  <-- pinned defect
...
PASS  --out sorts whole numbers as numbers, then text: 1, 2, 10, A, from rows given as A, 10, 2, 1  <-- pinned defect
...
PASS  --out puts one apostrophe before each district label that starts with a formula character, and before a count column named =sum  <-- pinned defect
PASS  --assign-out guards the district column too, and leaves the geoid column and the header alone  <-- pinned defect
...
PASS  the guarded --assign-out reads back as --assignment, gives the same district table byte for byte, and no label collapses into another  <-- pinned defect
...
PASS  --ap is refused by the parser with exit 2 and writes nothing  <-- pinned defect
...
PASS  a closed pipe exits 2 and the CSV is not written  <-- pinned defect
...
PASS  the whole command line half made no network call
...
PASS  a real closed pipe exits 2, not the interpreter's 120, and writes no file  <-- pinned defect
...
PASS  the file imports only the standard library: no arcpy, no third party package
...
PASS  the harness records a false check, a missing exception and a wrong exception as three failures, so a broken tool turns this self-test red  <-- pinned defect
...
--------------------------------------------------------------------
228 assertions, 0 failed
```

The block is abridged. `...` marks each place where lines are left out. The same 228 assertions pass
on Windows with Python 3.13, 3.12, 3.10 and 3.9, with a writable clone of an ArcGIS Pro
Python environment (Python 3.13.7), and on
Ubuntu with Python 3.12.3. The full output on
Windows (3.13) and the full output on Ubuntu are identical once the carriage returns that Windows
adds to a redirected capture are removed. That leaves only the first line of the Ubuntu capture,
which is the `python3 --version` line I printed before the run.
Branch coverage of `blockfit.py` under `--self-test` is 100 percent (903 statements, 188 branches,
coverage.py 7.16.1, measured on Windows with Python 3.13). I did not measure coverage on Ubuntu.

## Requirements

Python 3.9 or newer. Standard library only: `argparse`, `csv`, `io`, `math`, `os` and `sys`. The
self-test also imports `ast`, `contextlib`, `runpy`, `shutil`, `socket`, `subprocess` and
`tempfile`. It runs on a writable clone of an ArcGIS Pro Python environment and on a plain `python3`. The self-test asserts this
import list, so a new dependency turns it red.

```
git clone https://github.com/uhsear/blockfit.git
python blockfit.py --self-test
```

`--self-test` needs no network and no download. It writes its CSV files to a temporary directory,
then runs the real command line against them, once in-process and once as a separate process. During
the in-process runs it replaces `socket.socket`, `getaddrinfo` and `create_connection` with a trap
that raises, and it asserts that nothing called the trap. It does not prove the tool is offline on
every code path. It proves that none of the runs it makes touched the network.

## Quick start

```
python blockfit.py --blocks blocks.csv --assignment assign.csv --year 2020 --county 99001 --trust-year
python blockfit.py --blocks blocks.csv --parts pieces.csv --year 2020 --county 99001 --trust-year
```

Each prints the district table and the reconciliation, and writes nothing. Drop `--trust-year` only
when both files have a `geoid20` or `geoid10` header. One tagged file is not enough: a run with a
tagged file and a plain `geoid` file is refused with exit 1.

```
python blockfit.py --blocks blocks.csv --parts pieces.csv --year 2020 --county 99001 \
    --trust-year --out districts.csv --assign-out assigned.csv --apply
```

## Usage

| Flag | Default | What it does |
|---|---|---|
| `--blocks` | none | Block extract CSV: one GEOID column and whole-number count columns. Required. |
| `--assignment` | none | CSV with `geoid` and `district`. Use this or `--parts`. |
| `--parts` | none | CSV with `geoid`, `district` and `area`: the pieces of an overlay of blocks on districts. |
| `--year` | none | Vintage of `--blocks`: `2010` or `2020`. Required. |
| `--county` | none | Five digits, state FIPS then county FIPS. Required. There is no default. |
| `--measure` | `total` | The count column that means people. |
| `--control-total` | off | The extract's `--measure` must equal this whole number. |
| `--trust-year` | off | Accept `--year` when either file lacks a `GEOID10` or `GEOID20` header. Without it, such a run is refused, because nothing in an untagged file says which vintage it is. |
| `--out` | none | Path for the district summary CSV. Needs `--apply`. |
| `--assign-out` | none | Path for the block-to-district CSV that `--parts` produced. Needs `--apply`. |
| `--apply` | off | Write `--out` and `--assign-out`. Without it blockfit writes no file. `--self-test` is the one exception (see Output). |
| `--allow-unreconciled` | off | Write the outputs even when the check refused. The exit code stays 1. |
| `--self-test` | off | Run the offline assertions and exit. |

Flags must be spelled out. The parser is built with `allow_abbrev=False`, so `--ap`, `--app` and
`--appl` are refused with exit 2 and write nothing. They are not read as `--apply`. So are `--allow`
and `--assign`. The self-test runs each of them, and runs `--ap` again in a separate process.

Column names are not case sensitive. A GEOID column is `geoid`, `geoid10` or `geoid20`, and an input
may have only one of them. A header of `GEOID10` or `GEOID20` is also a claim about vintage, and
blockfit checks it against `--year`.

An output path that is also an input is a usage error. The tool will not overwrite its own input, judged by path (see Limits for hard links).

## What it checks

Each check below is a refusal. A refusal prints a reason and exits 1.

1. **Every block is in a district.** A block in the extract and not in the assignment is
   `UNASSIGNED`. The reason gives the number of blocks, the people in them and example GEOIDs.
   The count is by block, not only by people. A block with no residents moves no population total,
   so a population sum alone cannot see it leave. The reason names the block count and the
   `--measure` total only. The loss in every other count column shows in the sums table.
2. **The two files describe one block set.** When some extract blocks are missing from the
   assignment and some assignment blocks are missing from the extract, the reason is `VINTAGE`. It
   says how many assignment blocks do match. A block in the assignment only is an `ORPHAN` when
   nothing is missing the other way.
3. **The header tag.** A `GEOID10` header against `--year 2020` is a `VINTAGE` refusal, on either
   file.
4. **One district per block.** A block named twice with the same district is `REPEATED`. A block
   named with two districts is a `CONFLICT`. Neither is double counted: the first district is kept
   for the table, and the run is refused.
5. **The county.** A block whose GEOID does not start with `--county` is a `COUNTY` refusal on
   whichever file holds it. It is not counted as an orphan or as unassigned.
6. **The control total.** With `--control-total`, the extract's `--measure` must equal it.
7. **Not empty.** An extract with no rows is `EMPTY`. Zero equals zero is not a reconciliation.
8. **No "no district" label.** A district labelled `0` (or any run of zeros), `-1`, `null`, `none`,
   `nan`, `na`, `n/a`, `unassigned` or `unknown`, in any letter case, that holds blocks is a
   `NULL-DISTRICT` refusal. GIS tools write those labels for a block that no district holds, so
   the table would carry a phantom district. If one is a real district, rename it in your file.

9. **The vintage must be checkable.** When either file lacks a `GEOID10` or `GEOID20` tag,
   nothing in that file says which decade it is, and `--year` is only your claim for it. That is an
   `UNVERIFIED-VINTAGE` refusal, with exit 1. `pl94` writes a plain `geoid` header, so this is the
   common case. If you know the year, pass `--trust-year`. The run then says so in the report and
   on the verdict line, `RECONCILED (vintage not verified): ...`, and exits 3 when every other
   check passes, because the tool could not tell the decade. Tags on both files give the plain
   `RECONCILED:` line, need no flag, and exit 0. One tag is not enough.

The district sums are printed beside the extract sums for every count column. They are equal when
no block is lost, so equal sums are needed for `RECONCILED`. They are not enough. A repeated block,
a conflict, a control total mismatch, an empty extract and an out-of-county block all print equal
sums and are still refused.
The reasons, and the last line, are the verdict. The sums line is not.

The inputs are read strictly. These are errors with exit 2: a GEOID that is
not 15 ASCII digits (a 14 digit one gets a message about a lost leading zero), a count that is not a
whole number, a block twice in the extract, a short or long row, a repeated column name, a district
that is empty or not printable ASCII, an area that is not a finite number of 0 or more, a NUL byte,
and a file that is not UTF-8. Most name the line. A repeated column name, a NUL byte and a file that
is not UTF-8 name only the file. A leading zero in a state FIPS survives, because GEOIDs are read as
text.

Every column in the extract except the GEOID must be a whole number. A text column, such as a NAME
column in a Census download, ends the run with exit 2 and `not a whole number`. Remove it first.

## `--parts`: largest overlap

`--parts` takes the pieces of an overlay of blocks on districts. The pieces of one block that fall
in the same district are added. The block goes to the district with the largest total.

- A tie goes to the lowest district. Whole numbers sort as numbers, so a tie between `2` and `10`
  goes to `2`. The tie count is printed.
- A piece with an area of 0 is ignored and counted. A block with no positive piece is left out of
  the assignment, so the reconciliation reports it as unassigned.
- The areas are added with `math.fsum`, which returns the correctly rounded sum of the exact inputs.
  A running float sum depends on the order of the rows, and the built-in `sum` is only compensated
  from Python 3.12. The self-test pins a case where order decides the tie. That pin catches a switch
  to `sum` on Python 3.9 and 3.10 in the runs made here. On 3.12 and later `sum` gives the same
  answer.
- The report counts blocks that touch more than one district and the people in them. The rule puts
  each whole block in one district, so that number is an upper bound on the people it can place in
  the wrong one.

```
$ python blockfit.py --blocks blocks.csv --parts pieces.csv --year 2020 --county 99001 --trust-year
...
  DISTRICT    BLOCKS        total     arealand
  1                3          330         3600
  2                3          400         7500

  total          districts 730 / extract 730
  arealand       districts 11100 / extract 11100

  blocks split across districts: 2, holding 230 total (whole blocks, so this bounds the people the largest-overlap rule can misplace)
  ties on area broken by the lowest district: 1
  pieces with zero area ignored: 1

RECONCILED (vintage not verified): every block is in exactly one district and the district sums equal the extract.
```

The block with 350 people in water is in the pieces file here, with a part of its own, so the same
fixture that failed under the centroid rule reconciles.

## A vintage mismatch

```
$ python blockfit.py --blocks blocks.csv --assignment old.csv --year 2020 --county 99001 --trust-year
...
REFUSED: 1 reason(s)
  1. VINTAGE: 2 extract block(s) (350 total) are in no district and 2 assignment block(s) are not in the extract; 4 of 6 assignment blocks match. Census redraws blocks every decade, so these files describe different block sets. Both files must use the 2020 blocks, and blockfit cannot tell which one does not. Extract only: 990010001001003, 990010001001004. Assignment only: 990010001009100, 990010001009200
```

The reason says the files disagree about which blocks exist. blockfit cannot tell you which file
is on the wrong vintage. It can tell you the two are not on the same one. Any run with blocks on
both sides that the other side lacks gets this wording, so one mistyped GEOID in each file gets it
too.

## Producing the inputs

The extract is a CSV with a GEOID column and count columns. The CSV that
[pl94](https://github.com/uhsear/pl94) writes fits: its 15 columns load, 14 of them as counts, and
the self-test loads a synthetic CSV with that header. blockfit does not read the PL 94-171 zip. The
extract carries the people. It does not carry a second copy of the county total, which is why
`--control-total` exists. Take the control from the county record in the same PL file, which pl94
already reconciles to the extract.

The assignment is `geoid,district`. The pieces are `geoid,district,area`, one row per piece of a
block that lies in a district. In ArcGIS Pro, the Intersect tool writes "features or portions of
features that overlap in all layers or feature classes" to its output, and copies the attributes of
the inputs to it. That is the shape `--parts` needs. Export the block GEOID, the district and the
polygon area. I have not run an Intersect for this release. The `SHAPE@AREA` token is documented as
"a double of the feature's area" and the page does not say the units. blockfit compares areas as
plain numbers and cannot know their unit. Take every area from one projection. maup's README warns
that "Many of maup's functions behave badly in geographic projections", and an equal-area
projection is the safe choice. blockfit does not check any of this.

## Exit codes

| Code | Meaning |
|---|---|
| 0 | The assignment reconciles to the extract, and a `GEOID10` or `GEOID20` header tag on both files checked the vintage. |
| 1 | It does not, or the vintage could not be checked and `--trust-year` was not given. The reasons are printed. A failed `--self-test` also exits 1. |
| 3 | It reconciles, but at least one file carries no `GEOID10` or `GEOID20` tag and `--trust-year` accepted `--year` as your claim. The tool could not tell the decade, so it does not report 0. A job that accepts the claim must accept 3 on purpose. `--apply` still writes. |
| 2 | A file could not be read or is malformed, an output could not be written, or the report could not be written to stdout. argparse also exits 2 for a flag it does not know, such as `--ap`. |
| 64 | Usage error found by blockfit: a missing `--blocks`, `--year` or `--county`, a bad value, both or neither of `--assignment` and `--parts`, `--assign-out` without `--parts`, an output without `--apply`, `--apply` with no output, an output that is also an input, or `--out` and `--assign-out` naming the same file. |

Exit 1 and exit 2 are kept apart on purpose. A scheduled job reads 1 as "the numbers disagreed",
which is a fact about the data. A file that could not be written is a fact about the disk.

## Output

Without `--apply`, a normal run writes no file. The self-test lists the directory before and after
a run without it, and asserts that the listing is unchanged. `--self-test` is the one exception:
it writes 37 fixture files (the count I measured on Windows, Python 3.13) into a new folder in the system temporary directory, runs
against them, and deletes the folder when it ends, whether the checks passed or failed. It never writes beside the inputs or in the
current directory.

`--out` writes one row per district, sorted with whole numbers first, then text. `--assign-out`
writes `geoid,district`, sorted by GEOID. Both use LF line ends on every host, so two runs on the
same inputs produce the same bytes.

### Spreadsheet formulas

A spreadsheet runs a CSV cell that starts with `=`, `+`, `-`, `@`, a tab or a carriage return as a
formula. OWASP's CSV Injection page lists those characters, and a line feed too. Its sanitization steps include
putting a single quote in front of the cell, and blockfit does that. A district label comes from your files, and
so does the name of a count column, so blockfit does it for every text cell it writes. This
includes the header row. Numbers are not text and are written as they are, so the block and count
columns stay numeric.

```
$ python blockfit.py --blocks b.csv --parts p.csv --year 2020 --county 99001 --trust-year --out o.csv --assign-out a.csv --apply
$ cat o.csv
district,blocks,total
'-2,1,20
'=SUM(A1),1,100
Ward 3,1,3
$ cat a.csv
geoid,district
990010001001000,'=SUM(A1)
990010001001001,'-2
990010001001002,Ward 3
```

blockfit reads its own `--assign-out` file back as `--assignment`, so a district label with the
apostrophe is read as the label without it. The rule is exact. blockfit removes one apostrophe
from a label only when the apostrophes at the front are followed by one of those characters. A
label that is itself an apostrophe and then `=`, such as `'=C`, is written with a second
apostrophe (`''=C`), so it does not read back as `=C`. The self-test pins this round trip on seven
leading characters and on 21 awkward labels, and runs `--assign-out` into `--assignment` into
`--out` to show that the second district table equals the first byte for byte.
The reading rule applies to a `--parts` file too, because both go through one function. A label
you wrote as `'=C` in either input is read as `=C`. Write it as `''=C` to keep the apostrophe.

A tab, a carriage return or a line feed cannot reach a label or a column name. A leading one is
stripped when the file is read, and one inside the text is refused as not printable ASCII.
The self-test gives the guard those characters directly. It also shows a tab and a carriage
return stripped from a label, so that the formula character they hid is guarded afterwards. The
full-width variants of `=`, `+`, `-` and `@` that OWASP also lists are not ASCII, and blockfit
refuses a non-ASCII label or column name.

For the reconciled fixture that `--self-test` builds, `--out` writes this district table. It is
not the output of a refused run:

```
district,blocks,total,arealand
1,2,300,3000
2,4,430,8100
```

When the check refused, `--apply` writes nothing and says so. `--allow-unreconciled` writes the
short table anyway and the run still exits 1. A job that overrides the refusal cannot also report
success. The report is flushed before any file is written. If stdout is a closed pipe the run exits
2 and writes no file. On a closed pipe Python would flush its stdout buffer a second time at
shutdown, fail again, and exit 120. blockfit points its stdout descriptor at the null device first
so that the exit code stays 2. The self-test runs this against a real closed pipe in a child
process, and checks the descriptor redirect in process.

The file written by `--assign-out` goes back through the check as `--assignment`. The self-test
does that and it reconciles.

## Why the obvious version is wrong

The handwritten version assigns by centroid and adds up what it assigned:

```python
for block in blocks:
    district = district_containing(block.centroid)      # None on water: the block is dropped
    if district is not None:
        totals[district] += block.population            # no error, no warning
print(totals)                                           # the table looks fine
```

Nothing in that loop compares `sum(totals.values())` to the sum over `blocks`. A warning is the
tempting repair:

```python
if sum(totals.values()) != county_total:
    log.warning("district sum != county total")         # wrong
write_table(totals)
```

The table is still written, still loaded into a map, and the warning scrolls off. With `--apply`,
blockfit writes nothing when it refuses. `--allow-unreconciled` writes the short table on purpose,
and the run still exits 1.

Comparing only population hides a second loss. Under a centroid rule, a block that falls out may be
an empty one, such as water or a highway median. It moves no population total. The self-test
removes a block with 0 people and asserts that the run is refused anyway, because it counts blocks
and not only people.

## Limits

- **Fixtures are synthetic.** County `99001` does not exist. I did not run blockfit against a real
  county's block file or a real overlay for this release. The pl94 column layout it accepts was
  checked by loading a synthetic CSV with pl94's header, not a CSV pl94 wrote.
- **Vintage is inferred.** blockfit sees a header tag and a difference between two block sets. If a
  county's blocks were identical in both decades, a vintage mismatch would reconcile and nothing
  would show it. A one-sided difference is called `UNASSIGNED` or `ORPHAN`, not `VINTAGE`, because
  a single-sided gap is also what a centroid loss looks like. The Census Bureau publishes a 2010 to
  2020 block relationship file for moving counts between vintages. blockfit does not read it and
  does not convert between vintages.
- **15 digit GEOIDs.** The Census page on geographic identifiers describes a block GEOID as state,
  county, tract and block, 2 + 3 + 6 + 4 digits, and notes that some blocks carry a one character
  suffix. blockfit refuses a 16 character value rather than guess where the suffix goes.
- **No geometry.** blockfit never decides which district holds a block. It checks a table that
  something else made. With `--parts` it applies the largest-overlap rule to areas you supply and
  trusts them.
- **Exact integers only.** Counts must be whole numbers, and the reconciliation has no tolerance.
  One person off is a refusal.
- **One count column means people.** `--measure` names it. The other columns are summed and printed,
  and reconciled by the same argument, but only `--measure` goes into the reasons and the control.
- **Vintage is a tag and a difference.** `--year` matters only when a header carries a `GEOID10`
  or `GEOID20` tag, or when the two block sets differ. Two files with a plain `geoid` header on the
  wrong decade and identical block sets reconcile. A wrong `--year` given with consistent files
  reconciles. `--year` is a claim that blockfit cannot verify. pl94 writes a plain `geoid` header
  for both vintages, so without `--trust-year` a run with a plain file on either side is refused with
  `UNVERIFIED-VINTAGE` and exit 1. With `--trust-year` the report says "vintage: not verified" and
  that the year is your claim, the verdict line reads `RECONCILED (vintage not verified)`, and the
  exit code is 3, not 0. Earlier versions exited 0 here, which let a wrong `--year` look the same
  as a checked one to a scheduler. A job that passes `--trust-year` has accepted the claim, and it
  must treat 3 as success on purpose. One tagged file and one plain file also give exit 3: the
  tag is checked on the tagged file only, and the plain file's decade stays a claim. Only tags on
  both files give exit 0. An earlier build treated one tag as enough and exited 0 with a plain
  `RECONCILED:` line; the self-test now pins that case.
- **The control total is trusted.** `--control-total` checks the extract against the number. It
  cannot check the number. A wrong control gives a wrong verdict.
- **District labels are text.** A label is compared as text after trimming. `1` and `01` are two
  districts. blockfit does not know which labels are valid. It refuses the labels that GIS tools
  write for "no district" (see check 8), and only those. Any other placeholder, such as `99` or
  `water`, is a district of its own and reconciles, so read the district table. A label that starts with `=`, `+`, `-` or `@` is
  written with an apostrophe in front (see Spreadsheet formulas).
- **Two labels can read as one.** The reader removes one apostrophe from a label such as `'=x`. A
  hand-written file that holds both `=x` and `'=x` as separate districts is read as one district,
  with no warning. A file that blockfit wrote does not do this, because it writes `''=x` for
  the second label. A hand-written label that is an apostrophe and then a formula character, such
  as `'=C`, reads as `=C`. The same strip turns a hand-written `'-1` into `-1`, which is a
  no-district label, so that file is refused with `NULL-DISTRICT`.
- **The apostrophe is visible.** The guard changes the text. A spreadsheet that opens the CSV shows
  the apostrophe, because it is part of the cell, and blockfit's own reader removes it. OWASP warns
  that Excel can remove escape characters when it saves a CSV and opens it again, which would make
  a cell active again. I did not open the files in Excel, LibreOffice or Google Sheets for this
  release. The test is that no written cell starts with one of the seven characters.
- **No network code path.** blockfit.py has no `urllib`, `http` or `socket` use outside the
  self-test's trap, so there is nothing to exercise against a local `http.server` stub.
- **A spreadsheet can still reread plain labels.** The guard stops formulas, not data mangling. A
  spreadsheet may turn a label such as `1-2`, `3/4`, `1E3` or `01` into a date or a number. Read the
  CSV with a tool that keeps text.
- **Some non-ASCII header spellings pass as ASCII names.** The Kelvin sign (U+212A) lowercases to
  ASCII `k`, so a header written with it is accepted and shown as `k`. No formula character is
  reachable this way and the output stays ASCII.
- **The report is not guarded.** The district labels printed to stdout are written as they are,
  because the report is text for a terminal and not a CSV. Only the two CSV files are guarded.
- **The no-district list is fixed.** It is not complete. A label such as `#N/A`, which GIS and spreadsheet tools write, or `<Null>` is not on it, so it reconciles as a real district. (`NA` is on it, because R's `write.csv` writes `NA` for a missing value.) So do `0.0`, `-0` and `-1.0`, because only `-1` and runs of plain zeros are on it. Read the district table.
- **Spreadsheets drop leading zeros from a GEOID.** `--assign-out` writes the GEOID as bare
  digits. A spreadsheet that opens and saves the file can drop the zero from a state code such
  as `09`. blockfit then refuses the file on read-back with a 14 digit message and exit 2.
- **Parts input needs a column named exactly `area`.** An Intersect export often names it
  `SHAPE_Area` or `Shape_Area`. Rename it first, or blockfit exits 2 with "has no 'area' column".
- **A failed report write leaves stdout silenced.** blockfit points file descriptor 1 at the null
  device and does not restore it. A program that imports blockfit and calls `main()` loses its
  stdout for good after such a failure. The command line is not affected.
- **A trailing empty column is refused.** A CSV whose header ends in a comma, as some spreadsheet
  exports do, exits 2 with `empty or non-ASCII column name`. Remove the column first.
- **Areas are trusted.** `--parts` areas are not checked for units or projection. A mixed set gives
  a wrong largest part and no warning. Duplicate piece rows (the same GEOID, district and area)
  are summed as separate pieces and are not detected, so they can change which district wins. The
  areas are read with `float()`, which also accepts `1_0` and non-ASCII digits. GEOIDs and counts
  are stricter and take ASCII digits only.
- **Large numbers.** Recent Python releases cap `int()` at 4300 digits (3.11 and later, and the
  security releases of 3.9 and 3.10; I saw it on 3.13 and 3.9.25). A count cell or
  `--control-total` of more than 4300 digits ends in a traceback with exit 1, and exit 1 means
  "refused" to a scheduler. Do not feed the tool numbers longer than 4300 digits. Pieces of one
  block that sum past about 1.8e308 in area make `math.fsum` raise `OverflowError`, with the same
  result. A district label of any length is fine, because labels are sorted without `int()`; the
  self-test pins a label of 5000 digits.
- **A traceback is a crash.** Any uncaught exception exits 1, the same code as a data refusal. The
  only reachable ones found are the two above, and a missing `sys.stdout` (Python started with
  stdout closed, or `pythonw`), which raises `AttributeError` and exits 1 instead of 2. Treat a
  traceback as a crash even though the exit code is 1.
- **Outputs are not atomic.** `--out` and `--assign-out` are opened for writing in place, not
  written to a temporary file and renamed. A full disk part way through leaves a truncated table,
  and the run exits 2. With both flags, a failure on the second leaves the first file written. The
  exit code is 2.
- **The input check is by path.** The test that an output is an input uses `realpath` and
  `normcase`. On Windows, `realpath` resolves the 8.3 short name of an existing file to its long
  name (I checked this with `PROGRA~1`), so that alias is caught. The test does not follow hard links
  or NTFS alternate data streams. It is case sensitive on a case-insensitive POSIX file system, such as the default on macOS. Do not
  point `--out` at a hard link of an input.
- **The guard and the year check were mutation tested by hand.** For this release I made six changes and
  ran the self-test on each: no guard on a data row in `write_csv` (8 failures), none on the
  header (4), `return district` in place of `return uncell(district)` in `cell_district` (5), no
  second apostrophe for `'=C` in `cell` (7), `--trust-year` ignored in `reconcile`, and
  `main` always passing `require_tag=False`. All turned the self-test red. The counts depend on how
  each mutant is written, so I do not quote them for the last two. Removing the
  apostrophe stripping inside `uncell()` itself is a different mutant, and it fails 14 checks. I
  did not rerun the wider sweep described next.
- **Mutants the self-test cannot tell apart.** I ran a mutation sweep of the code above
  `self_test()` on an earlier build, before the vintage line and the `district_key` change. Two
  mutants survived that sweep and a later read showed they were not equivalent. One changes `sample()` so
  that exactly 5 items print with "(first 5 of 5)". The other removes the `if not args.apply: return code`
  guard, so a refused run without `--apply` writes the "nothing written" line to stderr. Neither
  changes a verdict, an exit code, stdout or a file. The self-test now pins both, and both
  mutants fail it. A further dozen or so survivors are cosmetic or sit on a boundary that
  the self-test does not pin. None of them could change a verdict or a write, and the decision core
  had no other survivor. I did not repeat the sweep after the vintage and `district_key` changes.
  The unpinned ones: the self-test does not pin
  the report's blank separator lines, the numbering of reasons (it starts at 1), the extract label
  in the header line, the assignment or parts word in the header line, the closing flush, or the
  `wrote` line for `--assign-out`. The upper boundary of the printable-ASCII rule for district
  labels (the tilde) is not pinned by the self-test. Replacing `math.fsum` with `sum` is caught on
  Python 3.9 and 3.10 in the runs made here. The Python documentation says the built-in `sum` is
  compensated from 3.12. I ran that mutant on 3.11.15 as well, and it is caught there (1 failure).
  The 3.9 and 3.10 runs catch it too.
- **Blank and odd lines.** A trailing line of spaces or commas is a malformed row and ends the run
  with exit 2, not a skipped blank line. Only comma separated files are read. A semicolon file exits 2 with a
  missing-GEOID-column message that does not name the delimiter. A tab file exits 2 with `has an
  empty or non-ASCII column name`, because the tab is rejected before the GEOID column is looked for. A blank
  district cell, as a spatial join writes for a block outside the district tiling, is exit 2, not
  an `UNASSIGNED` refusal with exit 1.
- **The output path is not checked for type.** A device name such as `NUL` or `/dev/null` is
  reported as written, and nothing is stored. The `NUL` case is a Windows behaviour that I did not
  check against Microsoft documentation. File names in the stdout report are echoed with
  non-ASCII escaped but ASCII control characters left as they are, so a hostile name can change
  what a terminal shows. File names in stderr messages are not escaped by blockfit at all. On a
  UTF-8 stream a non-ASCII name prints as typed. On an ASCII stream Python escapes it.
- **`--apply` replaces a file without asking.** An existing `--out` or `--assign-out` file that is
  not an input is overwritten. blockfit refuses only a path that is one of its own inputs.
- **`--self-test` ignores the output flags.** `--out` or `--assign-out` given with `--self-test`
  is dropped with no message, and nothing is written outside the temporary folder.
- **Float noise is not a tie.** Areas that are equal in exact arithmetic but differ by binary float
  noise in the file (0.30000000000000004 against 0.3) are not reported as ties.
- **`--parts` with `--allow-unreconciled` writes every overlay block.** `--assign-out` then holds
  each GEOID from the overlay, including blocks the extract does not have, so the written file
  reads back through `--assignment` as an `ORPHAN` refusal. This follows from the override.
- **Formula characters in a column name.** Only a count-column header starting with `=` is tested end
  to end; the other leading characters are tested through `cell()`.
- **Tab and carriage return.** A tab or carriage return cannot reach a written label or column name
  from the command line, because the reader strips or refuses it first. Direct calls to `cell()`,
  `cell_district()` and `write_csv()` pin the guard for those two characters.
- **Other leading characters.** The guard covers the seven characters OWASP lists. A character that
  a particular spreadsheet treats as special, such as a leading pipe, is written as it is.
- **Outer Unicode whitespace is trimmed.** A district label with a no-break space or another
  Unicode space at either end is read as the trimmed label. The same character inside a label is
  refused as not printable ASCII.
- **A missing `--measure` column is exit 2.** It is a usage mistake, but blockfit reports it as
  `no <name> column`, exit 2, and not as exit 64.
- **The Intersect remarks are from my own runs.** That Intersect copies the input attributes, and
  that `Shape_Area` is the usual name for the area column, are not on the Esri page cited under
  Sources checked.
- **No round trip to exit 0.** A file written by `--assign-out` has a plain `geoid` header, so reading
  it back as `--assignment` is refused with `UNVERIFIED-VINTAGE` (exit 1) unless you give
  `--trust-year`, and then it exits 3.
- **A short table has no marker.** A file written under `--allow-unreconciled` carries the same
  header as a good one. Only the exit code and the report on stdout say that it is short.
- **The self-test cleans up at the end, not after a crash.** The folder is removed after the checks
  run, passed or failed. A crash or a kill part way through leaves a `blockfit-*` folder in the
  system temporary directory. The self-test is the one run that writes without `--apply`, and
  only there.
- **A closed stdout after the report.** If the reader closes stdout after the report was delivered,
  blockfit may already have written the files and still exits 2, with `cannot write` and no file name.
- **Statewide block files.** A block assignment file for a whole state fails check 5 (COUNTY),
  because every block outside `--county` is refused. Cut the file to one county first.
- **Device names on Windows.** `--out CON` or `--out nul` is reported as written and nothing is
  stored. The exit code is 3 or 0, as for any other path.
- **Windows carriage returns.** The statement that Windows adds carriage returns to a redirected
  capture is from my own runs. No entry in Sources checked cites Microsoft or Python for it.
- **Windows facts have no Microsoft citation.** The `NUL` device behaviour, `realpath` resolving
  8.3 aliases and the carriage returns in a redirected capture are all from my own runs. Sources
  checked holds no Microsoft page for any of them.
- **The pl94 header was not re-checked.** The 15 column, 14 count claim comes from the synthetic CSV
  the self-test loads. I did not open pl94 or a file it wrote for this release.
- **A path you pass is opened as typed.** A UNC path given to `--blocks`, `--assignment`, `--parts`
  or `--out` makes the operating system contact that host. Paths come only from the command line,
  never from file data.
- **Wrong exit code with no stdout.** With stdout closed before the process starts (`>&-`, or
  `pythonw`), the run ends in an `AttributeError` traceback and exits 1, not 2.
- **Hard links.** Under `--apply`, an `--out` that is a hard link of an input overwrites that input
  and the run exits 3. I verified this by rewriting a test input.
- **Where the self-test has not run.** It has not run on macOS. It has run on
  Windows with Python 3.9, 3.10, 3.12 and 3.13, and on Python 3.11 (228 assertions, 0 failed), and on Ubuntu with Python 3.12.
  The self-test never imports `arcpy`, so it says nothing about how blockfit behaves on data
  that came out of ArcGIS Pro.

## Sources checked

Read on 2026-10-22, except where a line says otherwise.

- Census Bureau, geographic identifiers (`census.gov/programs-surveys/geography/guidance/geo-identifiers.html`):
  a block GEOID is state + county + tract + block, 2 + 3 + 6 + 4 digits, 15 in all; some blocks
  carry a one character suffix.
- Census Bureau, glossary (`census.gov/programs-surveys/geography/about/glossary.html`): blocks
  are "numbered uniquely with a four-digit census block number from 0000 to 9999 within census
  tract", and the first digit is the block group.
- Census Bureau, "Data Gem: Can I Compare 2020 Census and 2010 Census Redistricting Data?"
  (`census.gov/data/academy/data-gems/2021/compare-2020-census-and-2010-census-redistricting-data.html`):
  most blocks, tracts and block groups were redrawn between the two censuses, so a direct block
  comparison across decades is not advised. This is my paraphrase. I did not re-confirm the exact
  wording of the transcript on 2026-10-23, so it is not in quotation marks.
- Census Bureau, relationship files page (`census.gov/geographies/reference-files/time-series/geo/relationship-files.2020.html`):
  the block relationship files compare the universe of 2010 tabulation blocks to the universe of
  2020 tabulation blocks.
- Python documentation, `signal` module, "Note on SIGPIPE" (`docs.python.org/3/library/signal.html`,
  read on 2026-11-11): the recipe for `BrokenPipeError`, which redirects the stdout descriptor to
  `os.devnull` with `os.dup2`. The phrase "Python flushes standard streams on exit" is a comment
  in that page's example code, not its prose. blockfit's
  `write_failed` follows it.
- Python documentation, `csv` module (`docs.python.org/3/library/csv.html`, read on 2026-11-11): a
  file object given to the reader "should be opened with newline=''", and the footnote adds that
  without it an extra \r is written on platforms that use \r\n line endings. blockfit opens its
  output with `newline=""` and reads through `io.StringIO(text, newline="")`.
- Esri, Intersect tool (`pro.arcgis.com/en/pro-app/latest/tool-reference/analysis/intersect.htm`)
  and `SearchCursor` (`pro.arcgis.com/en/pro-app/latest/arcpy/data-access/searchcursor-class.htm`),
  read on 2026-11-11. Esri now redirects both with HTTP 301 to
  `doc.esri.com/en/arcgis-pro/latest/tool-reference/analysis/intersect.html` and
  `doc.esri.com/en/arcgis-pro/latest/arcpy/data-access/searchcursor-class.html`, and both sentences
  are on the new pages (checked 2026-11-11). The quoted sentences: "Features or portions of features that overlap in all layers or feature
  classes will be written to the output feature class", and, after the token `SHAPE@AREA` and a dash, "A double of the feature's area."
- Python documentation, "What's New In Python 3.12" (`docs.python.org/3/whatsnew/3.12.html`, read
  on 2026-11-11): "sum() now uses Neumaier summation to improve accuracy and commutativity when
  summing floats or mixed ints and floats." That is why `math.fsum` matters on 3.11 and earlier.
- maup README (`github.com/mggg/maup`): the behaviour of `assign` and `doctor`, the MIT licence,
  and the geographic coordinates warning.
- OWASP, CSV Injection (`owasp.org/www-community/attacks/CSV_Injection`, read on 2026-11-11 at
  its new address `community.owasp.org/attacks/CSV_Injection`): the leading characters `=`, `+`,
  `-`, `@`, tab (0x09), carriage return (0x0D), line feed (0x0A) and the full-width `=`, `+`, `-`
  and `@`; the suggestion to prepend each cell field with a single quote; and the warning that
  Excel may remove quotes or escape characters when a file is saved and opened again. The page
  also suggests a tab inside a quoted field for Excel. blockfit uses the apostrophe, because it
  can strip an apostrophe on read without guessing.

I did not read anything about SQL Server, PROJ or FEMA for this tool, because blockfit relies on
none of them.

## Related

- [pl94](https://github.com/uhsear/pl94) reads the PL 94-171 bulk file and refuses a block extract
  that does not reconcile to the county record in the same file. blockfit is its companion: pl94
  decides the extract is right, and blockfit decides the districts account for all of it.
- [maup](https://github.com/mggg/maup) assigns blocks, precincts and districts to each other from
  real geometry. Use it to make an assignment. Use blockfit to check one.
- Other repositories are called `blockfit` or close to it. `gh search repos blockfit --limit 10`
  on 2026-10-24, before this repository was published, returned ten, and this repository was not
  among them. A reader cannot repeat that check, because the repository is public now.
  The ones with a real description were a genetic-algorithm shape-packing program (`BlockFitter`),
  a hackathon project from 2018 and its demo, and a minimal heap allocator in C (`kundurz/blockfit`).
  None is about Census blocks as far as the descriptions say. The rest had no description or a
  placeholder, and I did not open them. A later search may list different repositories.

## Contributing

Open an issue or pull request on GitHub.
