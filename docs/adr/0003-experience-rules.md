# Years of experience: business rules

Years of experience exclude internships, count overlapping positions once, ignore positions without a start date, and end ongoing positions at the date of ingestion. Without any dated position the CV's own stated figure is used, and failing that only a seniority band can be read from explicit title words (junior, lead, directeur); years stay at zero rather than guessed. Bands: junior under 2 years, confirmed 2 to 5, senior 5 or more.

Chosen because the HR queries talk about "expérience", which in French consulting hiring means post-graduation work. The rules are in one module with unit tests, so changing a threshold is a one-line change.
