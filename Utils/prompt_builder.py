import tiktoken
import weave
import os


os.environ.get("WANDB_API_KEY")
weave.init("zzarcai/RAG Prompt Tracking")


'''Prompt With Context Builder Function''' #This creates a contextual prompt for the model
@weave.op
def prompt_with_context_builder(query, docs):
    delim = '\n\n---\n\n'   #This is so the AI creates a structural boundary between different pieces of context you get from Pinecone.
    prompt_start = 'Answer the question based on the context below. \n\nContext:\n'
    prompt_end = f'\n\nQuestion: {query}\nAnswer:'
    
    prompt = prompt_start + delim.join(docs) + prompt_end #Here, 'docs' is a list of strings we gathered from our previous step of retrieving data based on query.
    # Estimate input costs
    enc = tiktoken.encoding_for_model("gpt-4o-mini") 
    input_tokens = sum(len(enc.encode(text))for text in docs) #for each text in documents, encode using encode, take length to obtain number of tokens in text, and sum the results
    cost_per_1M_tokens = 0.15
    input_costs = (input_tokens / 1000000) * cost_per_1M_tokens
    return prompt, input_tokens, input_costs