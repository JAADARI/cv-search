# Embeddings are pluggable: local multilingual model by default, Azure OpenAI in the cloud

The gateway supplied for the exercise exposes a chat model only (every embedding deployment name and API version tried returned 404), so embeddings cannot come from it. Locally and in tests the system uses `multilingual-e5-large` (1,024 dimensions, French and English) through ONNX; on Azure Terraform deploys an Azure OpenAI `text-embedding-3-small` and requests 1,024 dimensions so the database schema is identical in both modes.

**Consequences:** vectors from the two providers are not comparable. Switching provider requires re-ingesting the CVs, which is cheap and automated because the original files are stored in the database.
