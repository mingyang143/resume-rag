from fastapi import FastAPI
from pydantic import BaseModel
import torch
from sentence_transformers import SentenceTransformer

app = FastAPI()

# Define Pydantic models for input validation
class EmbedRequest(BaseModel):
    sentences: list[str]

# Set up device for torch
device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')

# Load BGE-M3 model
embed_model = SentenceTransformer('BAAI/bge-m3', trust_remote_code=True).to(device)

# Embedding endpoint
@app.post("/embed")
def embed(request: EmbedRequest):
    embeddings = embed_model.encode(request.sentences, convert_to_tensor=True).to(device)
    return {"embeddings": embeddings.cpu().tolist()}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=5006)  # Adjust port as necessary