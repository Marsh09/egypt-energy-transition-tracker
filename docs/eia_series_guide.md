# EIA series guide (from the real pull of 2026-10-10)

What is inside the 16,404 EIA rows for Egypt, and which series answer the project questions.
Transformation owns the final choice; this is the starting point. All numbers below were read from the real files.

## 1. What is in the data

- 68 products x 13 activities, annual, mostly 1980 to 2024 (rows exist from 1973; 2025 has 10 rows).
- Activities: Production (1), Consumption (2), Imports (3), Exports (4), Reserves (6), Capacity (7), Emissions (8), Generation (12), Bunker (13), Distribution losses (9), Net imports (23), Population (33), GDP (34).
- Key to a series = `activityId` + `productId` + `unit`. The same activity and product usually exists in several units, so always filter on `unit`.
- Missing values are the text `NA` or `--`.

## 2. Three ways to build the "energy mix" (they are not the same thing)

| Option | Series | Unit | Coverage | Good for |
|---|---|---|---|---|
| **A. Primary energy consumption by fuel** | activity 2 with products 4411 Coal, 4413 Natural gas, 4415 Petroleum and other liquids, 4417 Nuclear, 4418 Renewables and other (total: 44 Primary energy) | QBTU | 1980 to 2024, no gaps | The whole energy system (what the World Bank indicator is closest to) |
| **B. Electricity generation by source** | activity 12 with products 30 Coal, 31 Natural gas, 32 Oil, 33 Hydroelectricity, 34 Non-hydro renewables (35 Geothermal, 36 Solar/tide/wave, 37 Wind, 38 Biomass), 27 Nuclear; totals 2 Electricity, 28 Fossil fuels, 29 Renewables | BKWH | 1980 to 2024; **Coal, Gas, Oil are `NA` for 1980 to 1999** | Targets stated for electricity |
| **C. Installed capacity** | activity 7 with products 33 Hydro, 29 Renewables, 28 Fossil fuels, 36/37/116 Solar and Wind | MK (thousand kW) | 1980 to 2024; some `NA` | Capacity targets, Benban-style solar growth |

Each option has a single unit per series, so there is no unit conversion to do inside an option.
Option B also has MTOE, QBTU and TJ versions of the renewable products; use BKWH for the whole option to stay consistent.

## 3. The renewable share depends on the definition

Same country, three different numbers:

| Definition | Source | Value |
|---|---|---|
| Renewables share of **primary energy** (4418 / sum of 4411, 4413, 4415, 4417, 4418, QBTU) | EIA | about **2.1%** in 2021 and 2024 |
| Renewables share of **electricity generation** (29 Renewables / 2 Electricity, BKWH) | EIA | about **12%** in 2024 (26.8 of 218.5 BKWH) |
| Renewable % of **total final energy consumption** (`EG.FEC.RNEW.ZS`) | World Bank | **6.1%** in 2021 (last year available) |

Consequences:
- **Transformation:** the planned cross-source check (EIA renewable share vs World Bank) will show a large gap by design. Pick the EIA definition closest to the World Bank one, state the allowed difference after looking at these numbers, and write the decision in `docs/`.
- **Analytics & BI:** Egypt's official target (42% by 2035) is normally stated as a share of **electricity**. Compare it with option B, not with the World Bank number, and record that decision.

## 4. Other facts worth knowing

- Renewables in 2024 (BKWH): hydro 15.0, wind 6.3, solar 5.2, other non-hydro about 0.3. Fossil: gas 167.7, oil 24.0, coal 0.
- Population (activity 33, product 4702) and GDP (activity 34, product 4701) are in the file if per-capita figures are wanted.
- `dataFlagId` is set on about 8% of rows. Meaning is in `dataFlagDescription`.

## 5. Should the pull be narrowed?

Not for now. The raw layer should be complete and it is only 5.5 MB. If we ever want a smaller pull, set `eia.facets` in `config/config.yaml`, for example:

```yaml
eia:
  facets:
    activityId: ["2", "7", "12"]
    unit: ["QBTU", "BKWH", "MK"]
```
