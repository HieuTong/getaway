
---

## 9. Later findings from the evaluation

| Problem | Cause | Fix |
|---|---|---|
| 3 picks with no known drive time under a 70-minute limit | The model ignored a rule written in the prompt | `_drive_filter` enforces the limit in code, before the model runs |
| A plan failed with `504 DEADLINE_EXCEEDED` | Only 429 and 503 counted as "try the next model" | 500, 503 and 504 now fall back too; regression test added |
| A run scored 5/15 with picks | The Routes API's daily quota was exhausted, so no place had a verified drive time | Not an agent bug: the evaluation should report infrastructure failures separately |

**Lesson:** a prompt is a request; code is a guarantee. And an evaluation must tell infrastructure failures apart from model failures, or a quota problem looks like a bad model.
