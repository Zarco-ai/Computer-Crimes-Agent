import json
import weave
import os
from dotenv import load_dotenv
load_dotenv()
os.environ.get('WANDB_API_KEY')
weave.init('zzarcai/RAG Prompt Tracking')

def get_messages():
    
    # 1. Load the System Prompt
    with open('prompts/sys.json', 'r') as f:
        sys_prompt = json.load(f)['sys_prompt']
        # Version System Prompt
        prompt1 = weave.MessagesPrompt(sys_prompt)
        weave.publish(prompt1, name="sys_prompt")
        
    # 2. Load Few-Shot Examples
    with open('prompts/fsp.json', 'r') as f:
        few_shots = json.load(f)
        # Version System Prompt
        prompt2 = weave.MessagesPrompt(sys_prompt)
        weave.publish(prompt2, name="fs_prompt")
        
    # 3. Assemble the payload
    messages = [{"role": "system", "content": sys_prompt}]
    
    # Use .extend() to add the list of few-shot dicts to our messages list
    messages.extend(few_shots)
    
    return messages