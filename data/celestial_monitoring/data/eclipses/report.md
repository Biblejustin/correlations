# NASA eclipse monitor

As of 2026-09-06. Complete modeled catalog for 1900–2100; one fixed Jerusalem point at 31°46′N, 35°14′E, source elevation 808.9 m. This point does not describe all-Israel visibility. Original selected historical CSV remains separate.

| Model family | Global catalog events | Jerusalem-visible geometry |
|---|---:|---:|
| Solar | 454 | 74 |
| Lunar | 459 | 310 |

Model snapshots: solar canon elements published October 2006; NASA JSEX program version 1 (2007); lunar elements April 2007; NASA JLEX program version 1 (23 May 2007).

Type codes: solar P = partial, A = annular, T = total, H = hybrid; lunar N = penumbral, P = partial, T = total.

Counts include future predictions through 2100 and are not a record of human sightings. Visibility means the source model’s horizon criterion is met during at least part of a phase. Clouds, buildings, terrain, extinction and visual contrast are not modeled. Penumbral geometry does not guarantee naked-eye detection.

## Upcoming Jerusalem-visible geometry

| Kind / global → local type | Catalog date (TD) | Visible start → end (UT1) | Maximum time (UT1) / altitude | Above-horizon phase durations |
|---|---|---|---|---|
| lunar N → N | 2027-02-20 | 2027-02-20T21:12:19 → 2027-02-21T01:13:19 | 2027-02-20T23:12:50 / 60.5° | penumbral 241.0 min |
| solar T → P | 2027-08-02 | 2027-08-02T08:40:30 → 2027-08-02T11:18:01 | 2027-08-02T10:00:49 / 75.6° | partial 157.5 min |
| lunar P → P | 2028-01-12 | 2028-01-12T02:07:36 → 2028-01-12T04:45:26 | 2028-01-12T04:12:56 / 5.8° | penumbral 157.8 min; umbral 56.0 min |
| lunar P → P | 2028-07-06 | 2028-07-06T16:47:04 → 2028-07-06T20:54:58 | 2028-07-06T18:19:40 / 15.4° | penumbral 247.9 min; umbral 141.5 min |
| lunar T → T | 2028-12-31 | 2028-12-31T14:38:30 → 2028-12-31T19:40:01 | 2028-12-31T16:51:58 / 25.3° | penumbral 301.5 min; umbral 208.8 min; total 71.3 min |
| lunar T → T | 2029-06-26 | 2029-06-26T00:34:34 → 2029-06-26T02:34:17 | 2029-06-26T03:22:05 / -9.1° (below horizon) | penumbral 119.7 min; umbral 62.0 min; total 3.1 min |
| lunar T → T | 2029-12-20 | 2029-12-20T19:42:53 → 2029-12-21T01:40:51 | 2029-12-20T22:41:54 / 72.9° | penumbral 358.0 min; umbral 213.3 min; total 53.7 min |
| solar A → P | 2030-06-01 | 2030-06-01T03:42:42 → 2030-06-01T06:10:06 | 2030-06-01T04:50:55 / 26.6° | partial 147.4 min |
| lunar P → P | 2030-06-15 | 2030-06-15T16:38:14 → 2030-06-15T20:52:22 | 2030-06-15T18:33:15 / 18.8° | penumbral 254.1 min; umbral 144.4 min |
| lunar N → N | 2030-12-09 | 2030-12-09T20:07:55 → 2030-12-10T00:47:09 | 2030-12-09T22:27:32 / 73.9° | penumbral 279.2 min |

UT1 is calculated from source TD minus source ΔT. These timestamps are not exact leap-second-aware UTC. Gregorian dates and timezone 0 are used; contacts retain their own dates across midnight. Future Earth-rotation uncertainty and the original ephemeris model limit timing accuracy. Decimal output is computational precision, not a timing guarantee.

Solar horizons retain NASA’s −0.00524 radian threshold and sunrise/sunset clipping. Lunar horizons retain NASA’s parallax/semidiameter/refraction convention; small negative visible lunar altitudes are reported as 0 by the source, and its simplified lunar altitude formula does not use elevation. Lunar maximum means global greatest eclipse, which can occur below the local horizon; solar maximum is source horizon-clipped local maximum.

## Validation and provenance

Validation: **passed**, 8,389 checks. One independent published Jerusalem solar case; three lunar contact/qualitative-map cases. No independent lunar numeric-altitude validation.

Pinned catalog raw type, normalized type counts and unique greatest-TD identity join only. Solar numeric elements contain no categorical global P/A/T/H field; independent element/global type agreement applies to lunar only.

Source programs are unmodified, GPLv2-or-later NASA Eclipse Explorer code. Source bytes, versions, hashes, reference pages and the frozen plan are pinned for offline replay. A changed source or failed validation prevents snapshot promotion. Live source checks create review candidates separately.

Eclipse Predictions by Fred Espenak and Jean Meeus (NASA’s GSFC); local Eclipse Explorer predictions by Fred Espenak and Chris O’Byrne (NASA’s GSFC).

[Pinned raw source archive](https://github.com/Biblejustin/astronomical-signs/tree/main/sources/nasa) · [Solar catalog](https://eclipse.gsfc.nasa.gov/SEcat5/SEcatalog.html) · [Lunar catalog](https://eclipse.gsfc.nasa.gov/LEcat5/LEcatalog.html) · [Solar local model](https://eclipse.gsfc.nasa.gov/JSEX/JSEX-key.html) · [Lunar local model](https://eclipse.gsfc.nasa.gov/JLEX/JLEX-key.html)
