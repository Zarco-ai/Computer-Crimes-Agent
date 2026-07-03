import os
from dotenv import load_dotenv
from openai import OpenAI
from Utils.get_mesages import get_messages
import tiktoken
import weave
load_dotenv()


os.environ.get("WANDB_API_KEY")
weave.init("zzarcai/RAG Prompt Tracking")

#Setting Up Our APIs and Index
client = OpenAI(api_key = os.getenv("OPENAI_API_KEY"))


'''Adjust 'messages' parameter'''
# Create the messages for your model
messages = get_messages()
    
    
'''Question Answering Function'''
@weave.op
def answer(prompt, sources, chat_model):
    # Turn context into the acceptable format for chat.completions endpoint
    messages.append({"role": "user", "content": prompt}) # This contains system message + few shot exs + user query
    res = client.chat.completions.create(
        model=chat_model,
        messages=messages, 
        temperature=0)
    answer = "\n" + res.choices[0].message.content.strip()
    answer += "\n\nSources:"
    for source in sources:
        s0 = str(source[0])
        s1 = str(source[1])
        answer += "\n" + s0 + ": " + s1
    # Estimate Output Costs
    enc = tiktoken.encoding_for_model("gpt-4o-mini")
    output_tokens = sum(len(enc.encode(text))for text in answer)
    cost_per_1M_tokens = 0.60
    output_costs = (output_tokens / 1000000) * cost_per_1M_tokens
    
    return answer, output_tokens, output_costs