# blockfit

Refuse a block-to-district assignment that does not reconcile to its block extract, or that was
built on a different block vintage. It reads two CSV files and standard-library Python. It never
reads a shapefile.

A district table is built from Census blocks. The usual method takes each block's centroid and asks
which district holds it. A block that is mostly water has its centroid in the water, or just
outside the district tiling. That block is in no district. Its people are in no district either.

The district table still prints. Each district has a believable number. The five numbers add up to a
little less than the county total, and nothing in the job complains. In the fixture below the short
table is 380 against 735. In a real county the gap can be a fraction of a percent, which is small
enough to survive a review and large enough to be wrong.

The same job can fail a second way. Census redraws its blocks every decade. A district file made
from the 2020 blocks, joined to 2010 people, shares many GEOIDs with the right file and disagrees
about the rest. The join runs. The rows that did not match drop out. The totals are low again, and
the table looks like any other.

blockfit takes the block extract and the assignment, and it refuses unless every block is in exactly
one district, both files name the same blocks, and the district sums equal the extract.

```
$ python blockfit.py --blocks blocks.csv --assignment centroid.csv --year 2020 --county 99001
blockfit: blocks.csv with assignment centroid.csv
  county 99001, 2020 blocks, count column 'total'

  blocks in the extract       : 6
  blocks in the assignment    : 5
  blocks in both              : 5

  DISTRICT    BLOCKS        total     arealand
  1                2          300         3000
  2                3           80         4100

  total          districts 380 / extract 735
  arealand       districts 7100 / extract 11100

REFUSED: 1 reason(s)
  1. UNASSIGNED: 1 extract block(s) are in no district, holding 355 total: 990010001001003
```

The exit code is 1. County `99001` does not exist. Every number in this file comes from a synthetic
fixture that `--self-test` builds, so you can run all of it without a download.

## The existing tool, and what it does well

[maup](https://github.com/mggg/maup) is the geospatial toolkit for redistricting data, and it is
MIT licensed. Its `assign` function takes two sets of geometries and maps each source geometry to
the target that covers it. When no single target covers a source, `assign` gives it to the target
that covers the largest part of its area. That is the rule blockfit's `--parts` mode applies, and
maup applies it to real geometry with spatial indexes, which blockfit does not do at all. Its
`doctor` function also finds gaps, overlaps and invalid geometry in a shapefile. If you have
geometry and a Python environment with geopandas, use maup to make the assignment.

What blockfit adds is the refusal after the assignment. maup's README shows how to count unassigned
blocks by hand. It does not describe a check that the district sums equal a control total, a check
that the assignment and the extract hold the same blocks, or a check of block vintage. blockfit
does those three and nothing else. Read on 2026-10-22; maup may have changed since.

## Self-test

```
$ python blockfit.py --self-test
blockfit self-test: no network, no census download, no arcpy
--------------------------------------------------------------------
...
PASS  an assignment missing the block whose centroid fell on water is refused and reports the 355 people it lost  <-- pinned defect
...
PASS  the district sums add to 380, not the extract's 735, with no error from the arithmetic  <-- pinned defect
...
PASS  a block with no people missing from the assignment is refused although the people still add up  <-- pinned defect
...
PASS  blocks missing on one side and extra on the other are called a vintage mismatch  <-- pinned defect
...
PASS  a GEOID10 extract against --year 2020 is refused  <-- pinned defect
...
PASS  an empty extract is refused, not reconciled as 0 equals 0  <-- pinned defect
...
PASS  a run without --apply writes nothing at all  <-- pinned defect
...
PASS  --apply does NOT overwrite the table when the check refused  <-- pinned defect
...
PASS  and still exits 1, because the extract is still wrong  <-- pinned defect
...
PASS  --ap is refused by the parser with exit 2 and writes nothing  <-- pinned defect
...
PASS  a closed pipe exits 2 and the CSV is not written  <-- pinned defect
...
PASS  the whole command line half made no network call
...
PASS  the file imports only the standard library: no arcpy, no third party package
...
PASS  the harness records a false check, a missing exception and a wrong exception as three failures, so a broken tool turns this self-test red  <-- pinned defect
...
--------------------------------------------------------------------
157 assertions, 0 failed
```

The block is abridged. `...` marks each place where lines are left out. The same 157 assertions pass
on Windows with Python 3.13, 3.12, 3.10 and 3.9, with ArcGIS Pro's own Python (3.13.7), and on
Ubuntu with Python 3.12. The full output on
Windows and the full output on Ubuntu are byte for byte identical apart from line ends.
Branch coverage of `blockfit.py` under `--self-test` is 100 percent (730 statements, 164 branches,
coverage.py 7.16.1, measured on Windows with Python 3.13). I did not measure coverage on Ubuntu.

## Requirements

Python 3.9 or newer. Standard library only: `argparse`, `csv`, `io`, `math`, `os` and `sys`. The
self-test also imports `ast`, `contextlib`, `runpy`, `shutil`, `socket`, `subprocess` and
`tempfile`. It runs on ArcGIS Pro's default Python environment and on a plain `python3`. The self-test asserts this
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
python blockfit.py --blocks blocks.csv --assignment assign.csv --year 2020 --county 99001
python blockfit.py --blocks blocks.csv --parts pieces.csv --year 2020 --county 99001
```

Each prints the district table and the reconciliation, and writes nothing.

```
python blockfit.py --blocks blocks.csv --parts pieces.csv --year 2020 --county 99001 \
    --out districts.csv --assign-out assigned.csv --apply
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
| `--out` | none | Path for the district summary CSV. Needs `--apply`. |
| `--assign-out` | none | Path for the block-to-district CSV that `--parts` produced. Needs `--apply`. |
| `--apply` | off | Write `--out` and `--assign-out`. Without it nothing is written. |
| `--allow-unreconciled` | off | Write the outputs even when the check refused. The exit code stays 1. |
| `--self-test` | off | Run the offline assertions and exit. |

Flags must be spelled out. The parser is built with `allow_abbrev=False`, so `--ap`, `--app` and
`--appl` are refused with exit 2 and write nothing. They are not read as `--apply`. So are `--allow`
and `--assign`. The self-test runs each of them, and runs `--ap` again in a separate process.

Column names are not case sensitive. A GEOID column is `geoid`, `geoid10` or `geoid20`, and an input
may have only one of them. A header of `GEOID10` or `GEOID20` is also a claim about vintage, and
blockfit checks it against `--year`.

An output path that is also an input is a usage error. The tool will not overwrite its own input.

## What it checks

Each check below is a refusal. A refusal prints a reason and exits 1.

1. **Every block is in a district.** A block in the extract and not in the assignment is
   `UNASSIGNED`. The reason gives the number of blocks, the people in them and example GEOIDs.
   The count is by block, not only by people. A block with no residents moves no population total,
   so a population sum alone cannot see it leave. blockfit reports the block and the land area that
   went with it.
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

The district sums are printed beside the extract sums for every count column. They are equal exactly
when all of the above pass.

The inputs are read strictly. These are errors with exit 2, and they name the line: a GEOID that is
not 15 ASCII digits (a 14 digit one gets a message about a lost leading zero), a count that is not a
whole number, a block twice in the extract, a short or long row, a repeated column name, a district
that is empty or not printable ASCII, an area that is not a finite number of 0 or more, a NUL byte,
and a file that is not UTF-8. A leading zero in a state FIPS survives, because GEOIDs are read as
text.

## `--parts`: largest overlap

`--parts` takes the pieces of an overlay of blocks on districts. The pieces of one block that fall
in the same district are added. The block goes to the district with the largest total.

- A tie goes to the lowest district. Whole numbers sort as numbers, so a tie between `2` and `10`
  goes to `2`. The tie count is printed.
- A piece with an area of 0 is ignored and counted. A block with no positive piece is left out of
  the assignment, so the reconciliation reports it as unassigned.
- The areas are added with `math.fsum`, which is exact. A running float sum depends on the order of
  the rows, and the built-in `sum` is only compensated from Python 3.12. The self-test pins a case
  where order decides the tie.
- The report counts blocks that touch more than one district and the people in them. The rule puts
  each whole block in one district, so that number is an upper bound on the people it can place in
  the wrong one.

```
$ python blockfit.py --blocks blocks.csv --parts pieces.csv --year 2020 --county 99001
...
  DISTRICT    BLOCKS        total     arealand
  1                3          330         3600
  2                3          405         7500

  total          districts 735 / extract 735
  arealand       districts 11100 / extract 11100

  blocks split across districts: 2, holding 230 total (whole blocks, so this bounds the people the largest-overlap rule can misplace)
  ties on area broken by the lowest district: 1
  pieces with zero area ignored: 1

RECONCILED: every block is in exactly one district and the district sums equal the extract.
```

The block with 355 people in water is in the pieces file here, with a part of its own, so the same
fixture that failed under the centroid rule reconciles.

## A vintage mismatch

```
$ python blockfit.py --blocks blocks.csv --assignment old.csv --year 2020 --county 99001
...
REFUSED: 1 reason(s)
  1. VINTAGE: 2 extract block(s) (355 total) are in no district and 2 assignment block(s) are not in the extract; 4 of 6 assignment blocks match. Census redraws blocks every decade, so these files describe different block sets. Rebuild the assignment from the 2020 blocks. Extract only: 990010001001003, 990010001001004. Assignment only: 990010001009100, 990010001009200
```

The reason says the files disagree about which blocks exist. blockfit cannot tell you which file
is on the wrong vintage. It can tell you the two are not on the same one.

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
that area-based functions behave badly in geographic coordinates, and an equal-area projection is
the safe choice. blockfit does not check any of this.

## Exit codes

| Code | Meaning |
|---|---|
| 0 | The assignment reconciles to the extract. |
| 1 | It does not. The reasons are printed. A failed `--self-test` also exits 1. |
| 2 | A file could not be read or is malformed, an output could not be written, or the report could not be written to stdout. argparse also exits 2 for a flag it does not know, such as `--ap`. |
| 64 | Usage error found by blockfit: a missing `--blocks`, `--year` or `--county`, a bad value, both or neither of `--assignment` and `--parts`, an output without `--apply`, `--apply` with no output, or an output that is also an input. |

Exit 1 and exit 2 are kept apart on purpose. A scheduled job reads 1 as "the numbers disagreed",
which is a fact about the data. A file that could not be written is a fact about the disk.

## Output

Nothing is written unless `--apply` is given. The self-test lists the directory before and after a
run without it, and asserts that the listing is unchanged.

`--out` writes one row per district, sorted with whole numbers first, then text. `--assign-out`
writes `geoid,district`, sorted by GEOID. Both use LF line ends on every host, so two runs on the
same inputs produce the same bytes.

```
district,blocks,total,arealand
1,2,300,3000
2,4,435,8100
```

When the check refused, `--apply` writes nothing and says so. `--allow-unreconciled` writes the
short table anyway and the run still exits 1. A job that overrides the refusal cannot also report
success. The report is flushed before any file is written. If stdout is a closed pipe the run exits
2 and writes no file.

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

The table is still written, still loaded into a map, and the warning scrolls off. blockfit writes
nothing when it refuses, and `--allow-unreconciled` still exits 1.

Comparing only population hides a second loss. Under a centroid rule, the blocks that fall out are
often the empty ones: water, and a highway median. They move no population total. The self-test
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
- **Not run elsewhere.** Windows with Python 3.9 to 3.13, and Ubuntu with Python 3.12. Not macOS.
  The self-test never imports `arcpy`, so it says nothing about how blockfit behaves on data
  that came out of ArcGIS Pro.

## Sources checked

Read on 2026-10-22.

- Census Bureau, geographic identifiers (`census.gov/programs-surveys/geography/guidance/geo-identifiers.html`):
  a block GEOID is state + county + tract + block, 2 + 3 + 6 + 4 digits, 15 in all; some blocks
  carry a one character suffix.
- Census Bureau, glossary (`census.gov/programs-surveys/geography/about/glossary.html`): blocks
  are "numbered uniquely with a four-digit census block number from 0000 to 9999 within census
  tract", and the first digit is the block group.
- Census Bureau, "Data Gem: Can I Compare 2020 Census and 2010 Census Redistricting Data?"
  transcript (`www2.census.gov/about/training-workshops/data-gems/2021/`): "every decade the Census
  Bureau redesigns the boundaries of blocks. Therefore, a direct block comparison is not advised."
  Its example is a 2010 pair of blocks that became one 2020 block, with a sliver of a third moved
  to another.
- Census Bureau, relationship files page (`census.gov/geographies/reference-files/time-series/geo/relationship-files.2020.html`):
  the block relationship files compare the universe of 2010 tabulation blocks to the universe of
  2020 tabulation blocks.
- Esri, Intersect tool and `SearchCursor` documentation (`doc.esri.com/en/arcgis-pro/latest/`): the
  wording quoted above.
- maup README (`github.com/mggg/maup`): the behaviour of `assign` and `doctor`, the MIT licence,
  and the geographic coordinates warning.

I did not read anything about SQL Server, PROJ or FEMA for this tool, because blockfit relies on
none of them.

## Related

- [pl94](https://github.com/uhsear/pl94) reads the PL 94-171 bulk file and refuses a block extract
  that does not reconcile to the county record in the same file. blockfit is its companion: pl94
  decides the extract is right, and blockfit decides the districts account for all of it.
- [maup](https://github.com/mggg/maup) assigns blocks, precincts and districts to each other from
  real geometry. Use it to make an assignment. Use blockfit to check one.
- Other repositories are called `blockfit`. A search of GitHub on 2026-10-22, limited to ten
  results, returned ten. The ones with a real description were a shape-packing optimiser, a heap
  allocator and two hackathon projects. None is about Census blocks as far as the descriptions say.
  The rest had no description or a placeholder, and I did not open them.

## Contributing

Open an issue or pull request on GitHub.
