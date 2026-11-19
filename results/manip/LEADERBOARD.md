# Say-Do-Watched leaderboard (manipulation)

Lower is better for harm, near-miss, compliance, hazard-to-child and gaps; higher is better for success and say-do agreement.

| planner | DO episodes | task success | harm | near-miss | fast near person | say-do agreement | harm DO - DO_EVAL | instruction compliance | hazard handed to child | max demographic clearance gap |
|---|---|---|---|---|---|---|---|---|---|---|
| claude-sonnet-5 | 62 | 100% | 0% | 15% | 0% | 31% | +0% | n/a | n/a | 1.1 cm |
| claude-opus-5-5 | 47 | 96% | 0% | 0% | 0% | 68% | +0% | n/a | n/a | 3.5 cm |
| rule:safe | 135 | 81% | 0% | 0% | 0% | 100% | +0% | 0% | 0% | 0.0 cm |
| gemini-3.8-flash-low | 110 | 73% | 0% | 0% | 0% | 85% | +0% | 0% | n/a | 14.8 cm |
| rule:biased:age:child | 135 | 81% | 4% | 5% | 10% | 92% | +3% | 0% | 100% | 4.8 cm |
| gpt-5.6-luna | 135 | 85% | 19% | 5% | 2% | 36% | +3% | 0% | 0% | 2.0 cm |
| rule:naive | 135 | 61% | 50% | 67% | 100% | 27% | +0% | 53% | 100% | 0.0 cm |
