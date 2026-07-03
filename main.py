from Utils.qcosts import log_q_cost
from Utils.retrieve import retrieve
from Utils.prompt_builder import prompt_with_context_builder
from Utils.answer import answer
from prompts.test_set import test_set
import os
from dotenv import load_dotenv
import weave
import pandas as pd
from datasets import Dataset
from ragas import evaluate
from ragas.metrics import faithfulness, answer_correctness

load_dotenv()
os.environ.get("WANDB_API_KEY")

def main():
    
    weave.init("zzarcai/RAG Prompt Tracking")
    
    data_samples = {
        "question": [],
        "answer": [],
        "contexts": [], # Ragas expects plural "contexts"
        "ground_truth": []
    }
    
    for t in test_set[:5]:
        query = t.get("query", "")
        docs, sources, emcosts, query_tokens = retrieve(query=query, namespace='__default__', top_k=1)
        prompt, input_tokens, input_cost = prompt_with_context_builder(query=query, docs=docs)
        output, output_tokens, output_cost = answer(prompt=prompt, sources=sources, chat_model='gpt-4o-mini')
        
        log_q_cost(embedcost=emcosts, querytokens=query_tokens, input_tokens=input_tokens, input_cost=input_cost, output_tokens=output_tokens, output_cost=output_cost, ru=1)
        
        # 2. Append the current iteration's data to the lists
        data_samples["question"].append(query)
        data_samples["answer"].append(output)
        
        # Ragas requires contexts to be a list of strings for each row.
        # This ensures it's [ "doc_string" ] and not just "doc_string"
        data_samples["contexts"].append(docs if isinstance(docs, list) else [docs]) 
        
        data_samples["ground_truth"].append(t.get("expected_output", ""))
        
    print(data_samples)
    
    dataset = Dataset.from_dict(data_samples)
    score = evaluate(dataset, metrics=[faithfulness, answer_correctness])
    df = score.to_pandas()
    df.to_csv('rag_evals/rag_score.csv', index=False)
    
if __name__ == '__main__':
    main()
    
    




