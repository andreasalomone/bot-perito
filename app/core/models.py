from sentence_transformers import SentenceTransformer

# Single cached embedding model instance for the application
embedding_model = SentenceTransformer("all-MiniLM-L6-v2", device="cpu")
