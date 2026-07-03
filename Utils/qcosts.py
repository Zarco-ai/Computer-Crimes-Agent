import json
import datetime
from datetime import datetime
'''Log Quey Costs'''
def log_q_cost(embedcost, querytokens, input_tokens, input_cost, output_tokens, output_cost, ru, version="v1.1"):
    price_per_ru = 16 / 1_000_000
    db_cost = ru * price_per_ru
    
    log_entry = {
        "timestamp": datetime.utcnow().isoformat(),
        "prompt_version": version,
        "query_embed_cost": embedcost,
        "user_query_tokens": querytokens,
        "input_tokens": input_tokens,
        "input_cost": input_cost,
        "output_tokens": output_tokens, 
        "output_cost": output_cost,
        "total_tokens": input_tokens + output_tokens,
        "total_cost_usd": input_cost + output_cost + db_cost,
        "breakdown": {"llm": input_cost + output_cost, "db": db_cost}
    }
    
    with open("Logs/query_logs.jsonl", "a") as f:
        f.write(json.dumps(log_entry) + "\n")