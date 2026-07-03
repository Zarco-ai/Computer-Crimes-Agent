from dotenv import load_dotenv
from openai import OpenAI
import os
import tiktoken #can convert any text into tokens
load_dotenv()

client = OpenAI(api_key = os.getenv("OPENAI_API_KEY"))

def create_embedding(text):
    response = client.embeddings.create(
        model="text-embedding-3-small",
        input=text
    )
    em = response.model_dump()
    
    return [data['embedding'] for data in em['data']]

###Before inserting a sizable dataset into a collection, it's important to get an idea of the cost.###
'''Estimating Embedding Costs'''
def emb_cost_est(docs):
    enc = tiktoken.encoding_for_model("text-embedding-3-small")            #By using include=["documents"], you are explicitly telling Chroma what you want, but you are also implicitly telling it "don't send me the heavy embedding vectors."
    #print("Visualizing data from 'results' variable:", docs)      #hence the "none" value for the embedding key when visualized
    embed_tokens = sum(len(enc.encode(text))for text in docs) #for each text in documents, encode using encode, take length to obtain number of tokens in text, and sum the results
    cost_per_1M_tokens = 0.02
    total_cost = (embed_tokens / 1000000) * cost_per_1M_tokens
    return total_cost, embed_tokens