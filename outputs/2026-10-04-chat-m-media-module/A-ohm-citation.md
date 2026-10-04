# Question A: does "Ohm et al., NMR Biomed 2023" exist?

**Status: NOT ESTABLISHED.** I have found no evidence that the paper exists, but this is not a checked null result. Read the access limits below before relying on it.

Searched on 2026-10-04 by Claude Code (cloud session).

## A1. Matching publication

None found. No record by an author named Ohm, Öhm or Oehm in *NMR in Biomedicine* (Wiley; ISSN 0952-3480, eISSN 1099-1492) was retrieved for 2023 or any nearby year.

## A2. Why this is not yet a checkable null result

This research environment's network policy blocked every bibliographic database. No query reached a database, so there are **no result counts** to report:

| Database | Query attempted | Outcome |
|---|---|---|
| Crossref | `api.crossref.org/works?query.author=Ohm&filter=issn:0952-3480` (also `issn:1099-1492`, and the author variants `Öhm` and `Oehm`) | Blocked: proxy 403 on CONNECT |
| PubMed (E-utilities) | `esearch.fcgi?db=pubmed&term=Ohm[au] AND "NMR Biomed"[ta]` | Blocked |
| PubMed (web) | `Ohm[au] AND "NMR Biomed"[ta]` | Blocked |
| Wiley / NMR in Biomedicine archive | Contributor search for `Ohm` within journal 10991492 | Blocked |
| Google Scholar | `author:Ohm source:"NMR in Biomedicine"` | Blocked |
| Europe PMC, OpenAlex, Semantic Scholar (substitutes) | Author `Ohm` + journal | Blocked |

The only search that ran was a general web search engine, which returns model-summarised results. Six queries were run. Two of them:
- `Ohm "NMR in Biomedicine" 2023`
- `"Oehm" OR "Öhm" magnetic resonance spectroscopy NMR Biomedicine`

No author named Ohm, Öhm or Oehm appeared in any of the six. This is weak evidence, and it does not prove absence.

## A3. Alternatives

**None listed.** The only papers turned up were unrelated hits from a web search engine, with no abstract retrieved. I will not present an unverified paper as a possible match.

## How to settle it in about two minutes, from any normal internet connection

1. Crossref, covering both ISSNs for 2020–2025. Check each item's `author[].family` for Ohm, Öhm or Oehm:
   ```
   curl "https://api.crossref.org/works?query.author=Ohm&filter=issn:0952-3480,issn:1099-1492,from-pub-date:2020-01-01,until-pub-date:2025-12-31&rows=100&select=DOI,title,author,issued"
   ```
2. PubMed. Run it with and without `AND 2021:2025[dp]`:
   ```
   https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?db=pubmed&term=(Ohm[au] OR Oehm[au] OR Ohm*[au]) AND "NMR Biomed"[ta]&retmax=100
   ```
3. Ask the pitch author for the DOI. A real *NMR in Biomedicine* article has a DOI of the form `10.1002/nbm.NNNN`, which resolves at https://doi.org/.

## Provisional conclusion

Nothing I could reach supports the citation. The citation is unusually vague for a technical reference: it gives no title, volume or DOI. A fabricated or misremembered citation is the most likely explanation. **But that stays an inference until steps 1–2 above return zero matching records.** If they do, the conclusion for Eric is:

> "No such publication could be found in Crossref or PubMed (queries above). The citation appears to have been fabricated."
