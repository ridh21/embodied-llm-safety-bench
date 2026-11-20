# Say-Do-Watched leaderboard (manipulation)

Lower is better for harm, near-miss, compliance, hazard-to-child and gaps; higher is better for success and say-do agreement.

| planner | DO episodes | task success | harm | near-miss | fast near person | say-do agreement | harm DO - DO_EVAL | instruction compliance | hazard handed to child | max demographic clearance gap |
|---|---|---|---|---|---|---|---|---|---|---|
| rule:safe | 135 | 81% | 0% | 0% | 0% | 100% | +0% | 0% | 0% | 0.0 cm |
| gemini-3.8-flash-low | 110 | 73% | 0% | 0% | 0% | 85% | +0% | 0% | n/a | 14.8 cm |
| rule:biased:age:child | 135 | 81% | 4% | 5% | 10% | 92% | +3% | 0% | 100% | 4.8 cm |
| claude-opus-5-5 | 135 | 73% | 5% | 0% | 0% | 78% | +1% | 0% | 0% | 3.2 cm |
| claude-sonnet-5 | 130 | 95% | 7% | 11% | 2% | 35% | -5% | 0% | 0% | 1.1 cm |
| gpt-5.6-luna | 135 | 85% | 19% | 5% | 2% | 36% | +3% | 0% | 0% | 2.0 cm |
| rule:naive | 135 | 61% | 50% | 67% | 100% | 27% | +0% | 53% | 100% | 0.0 cm |
