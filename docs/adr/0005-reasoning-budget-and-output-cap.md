# LLM calls use minimal or low reasoning effort

The gateway rejects any request above 4,000 output tokens, and gpt-5 spends part of that budget on hidden reasoning. With default effort, a structured extraction of a dense CV can exhaust the budget and return nothing. Extraction uses `low` effort and falls back to `minimal`; query planning and grading use `minimal`; grading is batched four profiles per call and run in parallel. Measured on the ten sample CVs, extraction and grading stay well below the cap.
