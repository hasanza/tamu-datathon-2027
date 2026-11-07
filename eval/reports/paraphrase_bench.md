# Paraphrase robustness bench

90 rewrites (15 events x 6 styles), writer gemini-3.8-flash. Ground truth: original event under gemini-3.8-flash.


## gemini-3.8-flash: 88/90 = 98%

- 15/15  a terse chat message with typos, abbreviations and no punctuation
- 15/15  a formal email with greeting, subject line and signature
- 15/15  a forwarded message with a long irrelevant legal disclaimer footer
- 13/15  uses synonyms and nicknames for plants, parts and suppliers, and write
- 15/15  all-lowercase quick chat shorthand, as typed on a phone
- 15/15  a daily-digest bullet list that also contains one unrelated item (cafe

**E-01** (uses synonyms and nicknames for plants, ...)
> Daily briefing on a couple of matters: 1. Alamo City update: a software crash has halted the line. The facility will be idled from Fri 3/19 through 3/22, with operations scheduled to restart on Tuesday 3/23. 2. Notice from QCI: the multimedia processor batch destined for the Indiana facility will mi
- got [('plant_outage', 'P_TX', None, None, None, 'None', 'None', '2027-03-19', '2027-03-22', False), ('supplier_delay', 'P_IN', 'CHIP-IVI', 'SH-0190', None, '2027-03-15', '2027-03-19', 'None', 'None', True)]
- want [('plant_outage', 'P_TX', None, None, None, 'None', 'None', '2027-03-19', '2027-03-22', False), ('supplier_delay', 'P_IN', 'CHIP-IVI', 'SH-0190', None, '2027-03-15', '2027-03-19', 'None', 'None', False)]

**E-14** (uses synonyms and nicknames for plants, ...)
> QA notification: Atlas reported moisture ingress impacting the heavy-duty electrical harness batches shipped to the Lone Star plant. Every unit produced between 02/22 and 02/24 is flagged as suspect.
- got [('quality_hold', 'P_TX', 'HARN-B', None, 'LOT-0017', 'None', 'None', 'None', 'None', True)]
- want [('quality_hold', 'P_TX', 'HARN-B', None, 'LOT-0017', 'None', 'None', 'None', 'None', False)]

## gemini-3.5-flash-lite: 89/90 = 99%

- 15/15  a terse chat message with typos, abbreviations and no punctuation
- 15/15  a formal email with greeting, subject line and signature
- 15/15  a forwarded message with a long irrelevant legal disclaimer footer
- 14/15  uses synonyms and nicknames for plants, parts and suppliers, and write
- 15/15  all-lowercase quick chat shorthand, as typed on a phone
- 15/15  a daily-digest bullet list that also contains one unrelated item (cafe

**E-01** (uses synonyms and nicknames for plants, ...)
> Daily briefing on a couple of matters: 1. Alamo City update: a software crash has halted the line. The facility will be idled from Fri 3/19 through 3/22, with operations scheduled to restart on Tuesday 3/23. 2. Notice from QCI: the multimedia processor batch destined for the Indiana facility will mi
- got [('plant_outage', 'P_TX', None, None, None, 'None', 'None', '2027-03-19', '2027-03-22', False), ('supplier_delay', 'P_IN', 'CHIP-IVI', 'SH-0190', None, '2027-03-15', '2027-03-19', 'None', 'None', True)]
- want [('plant_outage', 'P_TX', None, None, None, 'None', 'None', '2027-03-19', '2027-03-22', False), ('supplier_delay', 'P_IN', 'CHIP-IVI', 'SH-0190', None, '2027-03-15', '2027-03-19', 'None', 'None', False)]

## gemini-3.1-flash-lite: 88/90 = 98%

- 15/15  a terse chat message with typos, abbreviations and no punctuation
- 15/15  a formal email with greeting, subject line and signature
- 15/15  a forwarded message with a long irrelevant legal disclaimer footer
- 14/15  uses synonyms and nicknames for plants, parts and suppliers, and write
- 14/15  all-lowercase quick chat shorthand, as typed on a phone
- 15/15  a daily-digest bullet list that also contains one unrelated item (cafe

**E-01** (uses synonyms and nicknames for plants, ...)
> Daily briefing on a couple of matters: 1. Alamo City update: a software crash has halted the line. The facility will be idled from Fri 3/19 through 3/22, with operations scheduled to restart on Tuesday 3/23. 2. Notice from QCI: the multimedia processor batch destined for the Indiana facility will mi
- got [('plant_outage', 'P_TX', None, None, None, 'None', 'None', '2027-03-19', '2027-03-22', False), ('supplier_delay', 'P_IN', 'CHIP-IVI', 'SH-0190', None, '2027-03-15', '2027-03-19', 'None', 'None', True)]
- want [('plant_outage', 'P_TX', None, None, None, 'None', 'None', '2027-03-19', '2027-03-22', False), ('supplier_delay', 'P_IN', 'CHIP-IVI', 'SH-0190', None, '2027-03-15', '2027-03-19', 'None', 'None', False)]

**E-01** (all-lowercase quick chat shorthand, as t...)
> quick update on 2 things: 1) san antonio line has a software outage, down from next fri mar 19 through mon mar 22, restarts following working day tue mar 23. 2) quanta heads up, princeton infotainment chip run won't arrive next mon mar 15, carrier says delayed to next fri mar 19 due to severe weathe
- got [('plant_outage', 'P_TX', None, None, None, 'None', 'None', '2027-03-19', '2027-03-22', False), ('supplier_delay', None, 'CHIP-IVI', None, None, '2027-03-15', '2027-03-19', 'None', 'None', True)]
- want [('plant_outage', 'P_TX', None, None, None, 'None', 'None', '2027-03-19', '2027-03-22', False), ('supplier_delay', 'P_IN', 'CHIP-IVI', 'SH-0190', None, '2027-03-15', '2027-03-19', 'None', 'None', False)]
