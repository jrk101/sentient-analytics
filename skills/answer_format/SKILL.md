---
name: answer-format
description: How to submit the final answer for OfficeQA tasks.
---

# CRITICAL

The verifier only reads:

/app/answer.txt

If this file does not exist, the score is automatically 0.

After solving the problem:

1. Write ONLY the final answer to /app/answer.txt
2. Verify the file exists
3. Read it back with cat

Example:

echo "123.45" > /app/answer.txt
cat /app/answer.txt

# Rules

- No explanations
- No reasoning
- No markdown
- No units unless the question requires them
- Write exactly the requested format

Examples:

2602
1608.80%
[0.096, -184.143]
[10102000000, 4.73]

The task is NOT complete until /app/answer.txt exists.