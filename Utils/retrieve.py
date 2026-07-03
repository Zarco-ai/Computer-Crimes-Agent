import os
from dotenv import load_dotenv
from openai import OpenAI
from pinecone import Pinecone
from Utils.emb import emb_cost_est
import weave
load_dotenv()

os.environ.get("WANDB_API_KEY")
weave.init("zzarcai/RAG Prompt Tracking")

#Setting Up Our APIs and Index
client = OpenAI(api_key = os.getenv("OPENAI_API_KEY"))
pc = Pinecone(api_key=os.getenv("pinecone_apikey"), pool_threads=30)
index = pc.Index('cyberlaw')


'''Retrievel Function'''
@weave.op
def retrieve(query, top_k, namespace, emb_model='text-embedding-3-small'): #I think I should Place in here, a way to track the price of the embeddings
    em_cost, query_tokens = emb_cost_est(query)
    queryres = client.embeddings.create(input=query, model=emb_model)
    queryemb = queryres.data[0].embedding
    
    retrieveddocs = []
    sources = []
    docs = index.query(vector=queryemb, top_k=top_k, namespace=namespace, include_metadata=True, )
    
    for doc in docs['matches']:
        retrieveddocs.append(doc['metadata']['text']) # This is the text my model will base it's answer on
        sources.append((doc['metadata']['title'], doc['metadata']['url'])) # This is the section name and number, as well as the url to follow. 
    return retrieveddocs, sources, em_cost, query_tokens