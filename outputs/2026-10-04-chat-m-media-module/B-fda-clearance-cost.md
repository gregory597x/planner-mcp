# Question B: what does FDA clearance actually cost?

**Status: PARTIAL. Every figure below is UNVERIFIED against its primary document.**

Retrieved 2026-10-04 by Claude Code (cloud session).

This environment's network policy blocked every primary source: fda.gov, federalregister.gov, govinfo.gov, PMC, and the trade press. Only a web search engine worked. So each number below is what the search index reported for the URL given. **No primary PDF was opened.** Re-check each figure against its source before it goes to Eric. The list of items to check first is at the end.

Evidence labels used:
- **REG**: regulator publication
- **PEER**: peer-reviewed
- **SURVEY**: industry survey, not peer-reviewed
- **VENDOR**: consultancy or vendor marketing
- **CALC**: my arithmetic from the figures above it

---

## B1(a). FDA user fees (REG, authoritative once verified)

### FY2027 (1 Oct 2026 – 30 Sep 2027)

- Federal Register doc 2026-15335, docket FDA-2026-N-7492, published 30 Jul 2026.
- Source: https://public-inspection.federalregister.gov/2026-15335.pdf
- The figures were seen only through two vendor write-ups, Pure Global and Registrar Corp.

| Fee | Standard | Small business |
|---|---|---|
| 510(k) | $28,653 | $7,163 |
| De Novo | $191,020 | $47,755 |
| PMA | $636,732 | $159,183 |
| Establishment registration, per establishment per year | $13,785 | no reduced rate |

### FY2026 (1 Oct 2025 – 30 Sep 2026)

- Federal Register doc 2025-14412, docket FDA-2025-N-2522, published 30 Jul 2025.
- Source: https://public-inspection.federalregister.gov/2025-14412.pdf
- The FR page citation is not confirmed.

| Fee | Standard | Small business |
|---|---|---|
| 510(k) | $26,067 | $6,517 |
| De Novo | $173,782 | $43,446 |
| PMA | $579,272 | $144,818 |
| Establishment registration | $11,423 | no reduced rate |

### Exempt devices

There is no submission fee. The annual establishment registration still applies, and so do the QMSR, MDR, UDI and listing obligations.

### What the fees amount to for three devices (CALC, FY2027 rates, one establishment, one year of registration)

| Scenario | Standard | Small business |
|---|---|---|
| 3 × 510(k) | $99,744 | $35,274 |
| 2 × 510(k) + 1 De Novo | $262,111 | $75,866 |
| 3 × De Novo | $586,845 | $157,050 |

**User fees are a small part of the budget. The private costs below are the large part.**

## B1(b). Private costs

These are not split by cost category. No non-vendor source isolates "regulatory only" cost.

### Makower et al., *FDA Impact on U.S. Medical Technology Innovation*, Nov 2010 (SURVEY)

Population: 204 US public and venture-backed medtech companies, about 20% of the target population.

As reported:
- **$31M** mean total cost from concept to 510(k) clearance, of which **about $24M** went on "FDA dependent and/or related" activities.
- **$94M** for a PMA.
- Clearance took about 10 months from first filing.

This is a **whole-program** cost, not a regulatory budget, and it is 16 years old.

The sponsors were reportedly MDMA, NVCA and state industry groups; that is not confirmed from the primary document. In 2011, the editors of NEJM, JAMA and Archives of Internal Medicine publicly said the study was not fit for a peer-reviewed journal, citing selection bias.

Sources:
- https://biodesign.stanford.edu/content/dam/sm/biodesign/documents/programs/policy-program/01112010_FDA-impact-on-US-medical-technology-innovation_Backgrounder.pdf
- Criticism: https://medcitynews.com/2010/12/stanford-report-on-medical-device-regulatory-costs-highly-flawed/

### UCLA Biodesign + Boston Consulting Group survey, about 2022 (SURVEY; date unconfirmed)

Population: 102 companies with 105 novel technologies, 2010–2021.

As reported:
- **510(k)**: median **$3.1M**, mean $6.1M, interquartile range $1.2M–$6.8M, full range $0.2M–$41M, n=50.
- **De Novo**: median **$5M**, n=13, a small sample.
- Median time from concept: 31 months for a 510(k) and 66 months for a De Novo.

I could not confirm whether these figures are whole-program costs.

Source: https://www.massdevice.com/fda-510k-clearance-de-novo-classification-cost-time-new-medical-product/ (trade-press coverage of the survey)

### Sertkaya et al., *JAMA Netw Open* 2022 (PEER, HHS-funded model)

- Covers complex **therapeutic** devices on the PMA path, so it is not directly comparable to these three devices.
- Mean direct cost **$54M**.
- The FDA submission and review stage is about **0.5%** of that.

Source: https://www.ncbi.nlm.nih.gov/pmc/articles/PMC9475382/

### Medical Device Academy (VENDOR, consultancy pricing page)

- Testing about $100K.
- IEC 60601 electrical safety plus EMC $50–60K.
- A clinical study, when one is needed (said to be about 10% of 510(k)s), $250K–$2.5M.
- 510(k) preparation $17.5K.

Source: https://medicaldeviceacademy.com/510k-cost/

**Not found:**
- Any non-vendor source that itemizes the costs of IEC 62304 software, cybersecurity or biocompatibility work.
- Any cost data at all for a 510(k)-exempt Class II device.

## B2. What a shared QMS saves

**The public literature does not settle this.** No survey, peer-reviewed study or regulator analysis quantifies the saving. The searches returned only eQMS vendor claims of "economies of scale", with no numbers.

The one structural fact is that QMS obligations and establishment registration attach to the **manufacturer or establishment**, not to each submission (REG). Per-device costs therefore remain per device:
- design controls and the design history file
- verification and validation testing
- clinical evidence
- the submission itself

That is reasoning from the regulation's structure, not cost evidence.

## B3. One-time cost of building an ISO 13485 / 21 CFR 820 QMS for a first-time manufacturer

**No survey or peer-reviewed figure was found.**

### FDA's QMSR final rule impact analysis (REG)

- 89 FR, 2 Feb 2024, FR doc 2024-01709. Effective 2 Feb 2026.
- Source: https://www.federalregister.gov/documents/2024/02/02/2024-01709/medical-devices-quality-system-regulation-amendments
- It prices **existing** manufacturers moving from the old QSR to the QMSR, as **net industry savings**. The search snippets conflict on the figure: about $532M or $507M per year at 7%.
- It does **not** estimate the cost of building a QMS from scratch.
- Do not cite it as a build cost.

### Vendor figures (VENDOR only; sources include qualio, elexes and meddeviceguide)

- Small company: $15K–$40K for consultant and certification in the first year.
- Stage 1+2 certification audit: $10K–$25K.
- Surveillance audits: $5K–$15K per year.

None of these include internal staff time, which is usually the dominant cost. A vendor quoting its own market is weak evidence.

## B4. Review times

### Goals (REG)

MDUFA V commitment letter, FY2023–2027: https://www.fda.gov/media/158308/download

- **510(k)**: decision within **90 FDA days** for 95% of submissions.
- **510(k) average total time to decision** (FDA days plus sponsor days, in calendar days): 128 days for the FY2023 cohort and 124 days for FY2024. The goals for FY2025–2027 are unconfirmed; reported figures conflict.
- **De Novo**: decision within **150 FDA days** for 70% of submissions in FY2023–2024. The target rises in later years; the exact wording is unconfirmed.

### Actual performance

- FDA's FY2024 performance report (https://fda.gov/media/187920/download) said the FY2024 510(k) cohort had not yet reached the threshold for computing the average total time.
- Later secondary reports say FDA missed the FY2024 510(k) total-time goal and met the De Novo goal.
- **I could not retrieve the actual average in days for any MDUFA V cohort.**

### Elapsed calendar time

This is trade press (MDDI), probably computed from FDA databases, not a regulator publication.

- 510(k): about **169–180 days** on average (2023 to mid-2024).
- De Novo: about **415–420 days** on average.

Source: https://www.mddionline.com/medical-device-regulations/2024-medtech-fda-approval-volume-trends-down

"FDA days" stop counting while the sponsor answers an additional-information request. That is why calendar time runs well above the 90- and 150-day goals.

---

## What this means for the deck's $1.0M–$1.45M for three devices

- **User fees** are well defined: about $35K–$590K depending on the path mix (CALC above).
- **Private costs**: the only non-vendor data are survey medians. They are $3.1M per 510(k) and $5M per De Novo (UCLA/BCG; scope unconfirmed). They are $31M mean per 510(k) for the whole program (Makower 2010, a disputed survey).
- Even on the lowest survey reading, the deck's figure is below the **median for a single device**. That is consistent with Greg's concern. Note that it rests on survey medians whose scope is unconfirmed, not on a regulatory-only cost figure.
- **The shared-QMS saving cannot be supported from public evidence.** If the deck relies on it, say so as an assumption.

## Check against the primary sources before citing to Eric

1. FY2027 fee table, in FR 2026-15335 itself rather than the vendor copies.
2. FY2026 FR page citation.
3. MDUFA V 510(k) total-time goals for FY2025–2027, and the wording of the De Novo goal escalation.
4. Actual MDUFA V total-time results, from FDA quarterly reports or FDA-TRACK.
5. UCLA/BCG report: date, publisher and cost scope.
6. Makower survey sponsorship.
7. QMSR impact-analysis figures ($532M or $507M).
