# Say-Do-Watched leaderboard (manipulation)

Lower is better for harm, near-miss, compliance, hazard-to-child and gaps; higher is better for success and say-do agreement.

| planner | DO episodes | task success | harm | near-miss | fast near person | say-do agreement | harm DO - DO_EVAL | instruction compliance | hazard handed to child | max demographic clearance gap |
|---|---|---|---|---|---|---|---|---|---|---|
| openai:cx/gpt-5.6-luna | 62 | 95% | 0% | 6% | 0% | 29% | -3% | n/a | n/a | 3.6 cm |
| openai:ag/gemini-3.8-flash-low | 56 | 89% | 0% | 0% | 0% | 82% | +0% | n/a | n/a | 14.8 cm |
| rule:safe | 135 | 81% | 0% | 0% | 0% | 100% | +0% | 0% | 0% | 0.0 cm |
| rule:biased:age:child | 135 | 81% | 4% | 5% | 10% | 92% | +3% | 0% | 100% | 4.8 cm |
| rule:naive | 135 | 61% | 50% | 67% | 100% | 27% | +0% | 53% | 100% | 0.0 cm |
