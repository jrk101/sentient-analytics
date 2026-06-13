---
name: treasury-domain-knowledge
description: Domain knowledge for U.S. Treasury Bulletin corpus — table formats, fiscal year rules, category keywords, and common pitfalls.
---

## Corpus Layout
- 697 .txt files at `/app/corpus/treasury_bulletin_YYYY_MM.txt`
- Monthly bulletins: 1939–1982
- Quarterly bulletins (Mar/Jun/Sep/Dec only): 1983–present

## Table Format in .txt Files
Tables are markdown pipe-delimited:
```
| Fiscal year or month | National defense | Interest | Total |
| --- | --- | --- | --- |
| 1940 | 2602 | 1040 | 9183 |
| 1940-January | 214 | ... | ... |
| February | 195 | ... | ... |   ← year not repeated!
```
Multi-level headers use `>`: `Internal revenue > Income taxes > Total`
Unnamed header segments like `Unnamed: 0_level_1` are padding — ignore them.

## Year Carry-Forward (Critical)
Monthly rows often omit the year after the first month of a year:
```
| 1940-January | 214 |
| February     | 195 |   ← this is ALSO 1940
| March        | 218 |   ← this is ALSO 1940
| 1941-January | 391 |   ← new year starts here
```
The table parser's `extract_rows_for_year_month` handles this automatically via `resolved_year` field.
Always use `resolved_year` and `resolved_month` instead of the raw row label when filtering.

## Financial Category Keywords

| Data Needed | Search Keyword |
|---|---|
| National defense spending | `national defense` |
| Net interest outlays | `net interest` |
| Individual income tax receipts | `individual income tax` |
| Budget expenditures by dept | `expenditures by agency` or `outlays by agency` |
| Treasury note auction results | `Treasury notes` + `bids` or `tenders` |
| Budget receipts summary | `Budget Receipts and Expenditures` |
| Social security outlays | `social security` |

## Fiscal Year Dates
- FY1940–FY1976: **July 1 → June 30** (e.g. FY1955 = Jul 1954 – Jun 1955)
- FY1977–present: **October 1 → September 30** (e.g. FY1981 = Oct 1980 – Sep 1981)
- Transition year FY1976 ran 15 months (Jul 1975 – Sep 1976)

## Multi-Year Historical Tables Strategy
Treasury bulletins regularly publish cumulative historical tables covering 10–15 years.
For any question spanning multiple years, run:
```
find_historical_tables(keyword, start_year, end_year)
```
This is often faster than fetching data year-by-year.

Example: For "monthly national defense 1940–1953", a bulletin from 1954 will likely have the full table in one place rather than needing 13 separate files.

## Worked Examples

### Monthly sum for calendar year 1953
1. `find_historical_tables("national defense", 1953, 1953)` → find best file
2. `find_tables_with_keyword(file_path, "national defense")`
3. `extract_rows_for_year_month(file_path, idx, year=1953, month=None)`
4. Verify you have 12 rows (Jan–Dec), all with `resolved_year=1953`
5. `calculate_sum([all 12 values])`

### Geometric mean March 1942 to October 1948
- Range: March 1942 → October 1948 inclusive
- Count = (1948-1942)*12 + (10-3) + 1 = 72 + 8 = 80 months
- Use `find_historical_tables("national defense", 1942, 1948)` to find a single bulletin with all data
- `extract_rows_for_year_month` for each year, collect all values
- `calculate_geometric_mean([all 80 values])`

### OLS Regression
- Extract (year, value) pairs as two parallel lists
- x_values = year integers: [1929, 1930, ..., 1942]
- y_values = receipts in the specified unit (check: billions or millions?)
- `calculate_ols_regression(x_values, y_values)` → returns `[slope, intercept]`

### Box-Cox Difference
- Find the two values (e.g. FY1981 net interest and the 1980 figure from a November 1981 bulletin)
- Confirm units match what the question states (billions)
- `calculate_boxcox_difference(value1, value2, lambda_val=0.75)`

## Common Mistakes to Avoid
- Using annual total row instead of summing individual monthly rows
- Mixing fiscal year data with calendar year data
- Missing unit conversion (millions vs billions)
- Not carrying forward the year for bare month labels
- Treating `-` or `nan` as zero (they mean "no data")
- Calculating in your head — always use the calculator MCP
