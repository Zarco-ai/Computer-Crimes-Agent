from bs4 import BeautifulSoup
from pinecone import Pinecone
import json
import os
import math
from Utils.logger import get_embed_logger, get_index_costs_logger
from Utils.emb import create_embedding, emb_cost_est
from Utils.batch import chunks

#Connect Index
pc = Pinecone(api_key=os.getenv("pinecone_apikey"))
index = pc.Index("cyberlaw")

k = "/Users/christopherzarco/Desktop/AIE 1/pe.33.htm" # File Path

def parse_penal_code(html_file_path):   # The whole '.htm' file is parsed using a single function around the structure of the file
                                        # Every '.htm' file is differently structured.
    # 1. Load the HTML content
    with open(html_file_path, 'r', encoding='utf-8') as f:  # 'encoding' parameter defines the character set used to interpret the raw bytes 
                                                            # from the file into human-readable text. By setting it to "utf-8", you are instructing Python to read the file using the UTF-8 character encoding, 
                                                            # which is the modern standard for Unicode characters (supporting almost all languages and emojis).
        soup = BeautifulSoup(f, "html.parser")  # 'BeautifulSoup' class expects bytes-like object or string, so setting the encoding parameter really helped in achieving the byte like object. 

    extracted_data = []     # Initiates a list to hold the entire data pulled from the website
    current_section = {}    # Gets ALL the data from the specific section.
    
    # Track where we are in the text block (BODY or HISTORY)
    state = "SEARCHING"     # Come back to later

    # 2. Iterate through every paragraph tag in the document  ### IMPORTANT: This is the main logic that pulls the data from the file.
    for p in soup.find_all('p'):
        # Get the text, replacing multiple spaces with a single space 
        text = p.get_text(" ", strip=True)  # right here 'text' is a variable that is a string that looks like "" only IF 
                                            # the paragraph tag '<p>' was empty or contained only whitespace; otherwise, 
                                            # it will contain the actual cleaned text from that section of the HTML.
                                            # 'strip=True' makes paragraphs that contained only whitespace was turned into an empty string
        
        if not text:    # Here the code is saying, "if the text is only whitespace, continue to the next paragraph"
            continue
        # 3. Look for the Section Header
        # The header is inside an <a> tag with bold styling                                     Make sure you practice using lambda within your future coding projects
        header_link = p.find('a', style=lambda value: value and 'font-weight:bold' in value)    # As of right now the code is finding the '<a' tags within the '<p' tags
                                                                                                # it is using a lambda function to filter based on the sytle of the tag, hence why the lambda function is in the 'style' parameter
                                                                                                # 'style=lambda value:' initiates a lambda function
                                                                                                # 'value and...' first checks to see if tag has the style attribute
                                                                                                # 'font-weight:bold' in value' checks to see if the string font exsits in the style attribute
                                                                                                
        # Organize the section that contains the header
        if header_link and header_link.text.startswith("Sec."):
            # If we were already building a section, save it before starting the new one (The header is its own section)
            if current_section: # Check if the dictionary is holding data
                current_section['section_body'] = "\n".join(current_section['section_body'])    # Converts list of strings into one string, puts a new line in between each of items in the list of strings
                current_section['section_added_acts_and_amended_by'] = "\n".join(current_section['section_added_acts_and_amended_by'])  # Takes all 'added by' or 'amended by' lines and turns them into one readable block of text
                extracted_data.append(current_section) # Pushes completed dictionary into master list

            title = header_link.text.strip() # Turns the header_link variable into readable text for ammending to our dictionary
            
            # --- NEW: Extract the URL ---
            # Get the 'href' attribute. If it's relative, you can prepend the base URL.
            raw_url = header_link.get('href', '')
            base_url = "https://statutes.capitol.texas.gov/Docs/PE/htm/"
            full_url = raw_url if raw_url.startswith("http") else f"{base_url}{raw_url}"
            
            # The first paragraph often contains the title AND the start of the body.
            ### We strip out the title to just get the body text.
            body_start = text.replace(title, "", 1).strip()

            current_section = {
                'section_name_and_number': title,
                'url': full_url,
                'section_body': [body_start] if body_start else [], # Will only append the start of the body if there is a value inside
                'section_added_acts_and_amended_by': []
            }
            state = "BODY" # Switch to body extraction mode
            continue

        # 4. Extract Body and History based on our current "state"
        if state in ["BODY", "HISTORY"]:
            # Check if the paragraph starts with history keywords to switch modes ### We check this first, in this section, because our previous section 'header'/'state=SEARCHING'
            if text.startswith("Added by Acts") or text.startswith("Amended by:") or text.startswith("Amended by"):
                state = "HISTORY"   # These two lines of code check to see if the words inside the 'text' variable is a history on the act, 
                                    # we change this state to make it easier to filter our data for extraction by understanding the difference between body and history

            if state == "BODY": 
                # Ignore random editorial notes like "For text of section as amended by..."
                if not text.startswith("For text of section"):
                    current_section['section_body'].append(text)
            elif state == "HISTORY":
                current_section['section_added_acts_and_amended_by'].append(text)

    # 5. Append the final section to the list (since there is no "next" section to trigger the save)
    # These next few lines turn our list of strings into readable human text where we use "\n" to depict the next line within the code
    if current_section:
        current_section['section_body'] = "\n".join(current_section['section_body'])
        current_section['section_added_acts_and_amended_by'] = "\n".join(current_section['section_added_acts_and_amended_by'])
        extracted_data.append(current_section)

    return extracted_data

# Run the function (Assuming the file is named pe.33.htm in your directory)
data = parse_penal_code(k)

# Print the results nicely
#print(json.dumps(data, indent=4)) # 'json.dumps()' is basically used to turn my python object (a list of dictionaries) into a prettier output format for readability!

##############################################################################################################################################################################################################################


'''Preprocess Data'''
body = [i["section_body"] for i in data] # Will be used for embeddings
#This is for Pinecone Indexing
ids = [f"{i}" for i, _ in enumerate(data, 0)]
metadata = [
    {"title": i["section_name_and_number"], "acts_and_amended_by": i["section_added_acts_and_amended_by"], "text": i["section_body"], "url": i["url"]}  for i in data 
    #Each new item in this list MUST be a dictionary because the metadata needs to be structured as a list
]
print(metadata)

# Create a place holder for your vectors
vectors = []
for k, j in zip(ids, metadata):
    vectors.append({
        "id": k,
        "values": [],
        "metadata": j
    })
# Estimate Cost of embeddings
emprice = emb_cost_est(body)
# Create embeddings
embeddings = create_embedding(body)
#Log each time you do your embeddings 
emlogger = get_embed_logger(name=__name__, log_file="Logs/embed.log")
emlogger.info(emprice)
# Store each embedding in the 'value' key within each dictionary of the d1 list
for vector, embedding in zip(vectors, embeddings):
    vector['values'] = embedding
    
    
'''Calculate Upsert Costs'''
# Use DataCamp Batch method (for now)
b = 0
wu = 0
upsert_costs = 0
for chunk in chunks(vectors, batch_size=100):
    print('New Chunk')
    byte = len(json.dumps(chunk).encode('utf-8'))
    # Show Bytes
    print("Bytes", byte)
    
    # Convert bytes to KB 
    k = 1024
    kb = byte / k # Total amount of KB. ###Remember 1kb = 1wu
    print("KB:", round(kb, 0)) # Figure out how many bytes is each batch (b) ; Just one batch approx. 314,250 bytes
    
    #Floor Check
    wu += max(5, math.ceil(kb)) # Bumps up any chunk less than 5kb, up to 5kb (required for Pinecone)
    print("Write Units:", wu)
    
    # Turn Write Units Into costs:
    upsert_costs = 4 * (wu / 1_000_000) 
    print(upsert_costs)
    
# Log Costs
costlogger = get_index_costs_logger(name=__name__, log_file="Logs/indexcosts.log")
costs = f"Upsert Costs: {upsert_costs}, Write Units: {wu}"
costlogger.info(costs)

'''Process Data'''
#Ingest Vectors
index.upsert(vectors=vectors)
print(index.describe_index_stats())
