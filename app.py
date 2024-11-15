from qdrant_client.http.models import Filter, FieldCondition, MatchValue
import logging
from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import tempfile
import os
import uuid

# Import the necessary functions from utils.py
from utils import process_pdf, send_to_qdrant, qdrant_client, qa_ret, OpenAIEmbeddings

app = FastAPI()

# Frontend URL
FRONTEND_URL = os.getenv("FRONTEND_URL") 

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", FRONTEND_URL],  # Allow requests from your React app (adjust domain if necessary)
    allow_credentials=True,
    allow_methods=["*"],  # Allow all methods (POST, GET, etc.)
    allow_headers=["*"],  # Allow all headers
)

# Define a model for the question API
class QuestionRequest(BaseModel):
    question: str

@app.post("/upload-pdf/")
async def upload_pdf(file: UploadFile = File(...)):
    """
    Endpoint to upload a PDF file, process it, and store in the vector DB with a unique identifier.
    """
    try:
        pdf_id = str(uuid.uuid4())  # Use UUID for globally unique identifier
        # Save uploaded file to a temporary location
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as temp_file:
            temp_file.write(file.file.read())
            temp_file_path = temp_file.name

        # Process the PDF to get document chunks and embeddings
        document_chunks = process_pdf(temp_file_path)

        # Add the pdf_id to each chunk's metadata
        for chunk in document_chunks:
            chunk.metadata["pdf_id"] = pdf_id
        # Create the embedding model (e.g., OpenAIEmbeddings)
        embedding_model = OpenAIEmbeddings(
            openai_api_key=os.getenv("OPENAI_API_KEY"),
            model="text-embedding-ada-002"
        )

        # Send the document chunks (with embeddings) to Qdrant
        success = send_to_qdrant(document_chunks, embedding_model)

        # Remove the temporary file after processing
        os.remove(temp_file_path)

        if success:
            return {"message": "PDF successfully processed and stored in vector DB", "pdf_id": pdf_id}
        else:
            raise HTTPException(status_code=500, detail="Failed to store PDF in vector DB")

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to process PDF: {str(e)}")

@app.post("/ask-question/")
async def ask_question(question_request: QuestionRequest, pdf_id: str = None):
    """
    Endpoint to ask a question and retrieve a response from the stored document content.
    """
    try:
        # Retrieve the Qdrant vector store
        qdrant_store = qdrant_client()

        # Build filters for pdf_id if provided
        filters = {"must": [{"key": "metadata.pdf_id", "match": {"value": pdf_id}}]}
        print(filters)
        # Use the question-answer retrieval function to get the response
        response = qa_ret(qdrant_store, question_request.question, pdf_id=pdf_id)

        return {"answer": response}

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to retrieve answer: {str(e)}")

# A simple health check endpoint
@app.get("/")
async def health_check():
    return {"status": "Success"}

