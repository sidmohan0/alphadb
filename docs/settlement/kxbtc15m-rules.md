# KXBTC15M Settlement Rules Evidence

## Source Reviewed

- Linear issue: `ALP-48`
- Attachment: `CRYPTO15M.pdf`
- Source: Kalshi crypto 15-minute contract terms PDF downloaded from Kalshi
- PDF metadata creation date: 2026-03-25

## Confirmed Rules

- The source agency is CF Benchmarks.
- The underlying uses the relevant CF crypto index averaged over the 60 seconds before the listed expiration time.
- Revisions to the underlying after expiration are not used to determine the expiration value.
- If expiration-time data is unavailable or incomplete, affected strikes resolve to No.
- `above X` is a strict greater-than comparison.
- `below X` is a strict less-than comparison.
- `exactly X` pays on equality at the specified decimal precision.
- `at least X` pays when the expiration value is greater than or equal to X.
- `between X and Y` is inclusive at both endpoints.

## Not Confirmed

The reviewed PDF does not define an opening-window-derived reference value for `KXBTC15M`.
It describes listed `<price>` levels and payout comparators. AlphaDB should therefore model
the threshold as a listed payout threshold supplied by concrete market metadata unless a later
authoritative source proves a different rule.

## Implementation Consequence

`KXBTC15M` settlement rules should encode a listed payout threshold, payout comparator semantics,
and a final 60-second average over official CF Benchmarks index inputs. Downstream settlement-state
fixtures and calculators should not assume an opening-reference `K` unless a later source changes
this evidence.
