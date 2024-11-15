from langchain_community.document_loaders import PyPDFLoader
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_community.vectorstores import Qdrant
from langchain_community.embeddings import OpenAIEmbeddings
from qdrant_client import QdrantClient
from langchain.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnablePassthrough, RunnableParallel
from langchain_core.output_parsers import StrOutputParser
from langchain_openai import ChatOpenAI
import os

# Load environment variables (if needed)
from dotenv import load_dotenv
load_dotenv()

# API keys and URLs from environment variables
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
QDRANT_URL = os.getenv("QDRANT_URL")
QDRANT_API_KEY = os.getenv("QDRANT_API_KEY")


def process_pdf(pdf_path):
    """Process the PDF, split it into chunks, and return the chunks as Document objects."""
    loader = PyPDFLoader(pdf_path)
    pages = loader.load()
    document_text = "".join([page.page_content for page in pages])

    # Split the document into chunks
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=300,
        chunk_overlap=40
    )
    chunks = text_splitter.create_documents([document_text])

    # Ensure metadata is initialized for all chunks
    for chunk in chunks:
        if not chunk.metadata:
            chunk.metadata = {}

    return chunks



# Function to send document chunks (with embeddings) to the Qdrant vector database
def send_to_qdrant(documents, embedding_model):
    """Send the document chunks to the Qdrant vector database."""
    try:
        qdrant = Qdrant.from_documents(
            documents,
            embedding_model,
            url=QDRANT_URL,
            prefer_grpc=False,
            api_key=QDRANT_API_KEY,
            collection_name="xeven_chatbot",  # Replace with your collection name
            force_recreate=True  # Create a fresh collection every time
        )
        return True
    except Exception as ex:
        print(f"Failed to store data in the vector DB: {str(ex)}")
        return False


# Function to initialize the Qdrant client and return the vector store object
def qdrant_client():
    """Initialize Qdrant client and return the vector store."""
    embedding_model = OpenAIEmbeddings(
        openai_api_key=OPENAI_API_KEY, model="text-embedding-ada-002"
    )
    qdrant_client = QdrantClient(url=QDRANT_URL, api_key=QDRANT_API_KEY)
    qdrant_store = Qdrant(
        client=qdrant_client,
        collection_name="xeven_chatbot",
        embeddings=embedding_model
    )
    return qdrant_store


from qdrant_client.http.models import Filter, FieldCondition, MatchValue

def qa_ret(qdrant_store, input_query, pdf_id=None):
    """
    Retrieve relevant documents and generate a response from the AI model.
    Supports optional filtering based on pdf_id in nested metadata.
    """
    try:
        # Template for response generation
        template = """
        Context:
        {context}

        **Question:** {question}

        Provide a concise and clear answer based on the context above. If the context does not contain enough information, indicate that politely.
        """
        prompt = ChatPromptTemplate.from_template(template)

        # Setup the filter to search by pdf_id in metadata
        filters = None
        if pdf_id:
            filters = Filter(
                must=[
                    FieldCondition(
                        key="metadata.pdf_id", 
                        match=MatchValue(value=pdf_id)
                    )
                ]
            )

        # Setup retriever with similarity search and pdf_id filter if provided
        retriever = qdrant_store.as_retriever(
            search_type="similarity",
            search_kwargs={
                "k": 4,  # Adjust to the number of results you want
                "filter": filters  # Apply pdf_id filter here
            }
        )

        setup_and_retrieval = RunnableParallel(
            {"context": retriever, "question": RunnablePassthrough()}
        )

        model = ChatOpenAI(
            model_name="gpt-4o-mini",
            temperature=0.7,
            openai_api_key=OPENAI_API_KEY,
            max_tokens=150
        )

        output_parser = StrOutputParser()

        rag_chain = setup_and_retrieval | prompt | model | output_parser
        response = rag_chain.invoke(input_query)
        return response

    except Exception as ex:
        return f"Error: {str(ex)}"
