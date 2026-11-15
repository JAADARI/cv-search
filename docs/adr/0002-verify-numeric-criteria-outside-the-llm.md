# Numeric and seniority criteria are verified by code, not by the LLM

The LLM turns a query into criteria and grades topical ones with quoted evidence, but "at least 10 years in consulting" or "senior" is decided by comparing computed figures (years excluding internships, per sector, seniority band) to the requested threshold. Language models are unreliable at date arithmetic across heterogeneous CVs, and an auditable figure is what a recruiter can defend. Search results mark each criterion as `rules` or `llm` so the origin of every verdict is visible.

**Consequences:** extraction quality of dates and sectors directly bounds search quality; a profile whose dates cannot be read has unknown experience and is never invented a number.
