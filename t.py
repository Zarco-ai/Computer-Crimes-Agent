import pinecone
from pinecone import Pinecone
import os
from dotenv import load_dotenv
load_dotenv()
pc = Pinecone(api_key=os.getenv("pinecone_apikey"), pool_threads=30)
index = pc.Index('cyberlaw')
print(index.describe_index_stats())
'''ids = ['0', '1', '2']
fetched_vectors = index.fetch(ids=ids, namespace='__default__')
print(fetched_vectors)
# Extract the metadata from each result in fetched_vectors
metadatas = [fetched_vectors['vectors'][id]['metadata'] for id in ids]
print(metadatas)
#Display index a different way
disp = index.fetch(ids=ids)
# 1. Grab the read_units once from the top level
total_read_units = disp.get('usage', {}).get('read_units', 0) #First, It looks for the usage key at the top level of the response. If found, it grabs read_units; if not, it defaults to 0.
                                                                  #The top of the response has the values of 'namespace=', 'vectors=', 'usage', and '_response_info='
                                                                  # '.get()' is a tool for dictionaries, it's job is to look up a key without the risk of crashing your code if that key is missing. Will return the second parameter, '{}', if not found.
                                                                  #The value of 'usage' is a dictionary, the next .get() gets the key 'read_units' and returns an integer, integer is key's value.
t_res_info = disp.get('_response_info', {}).get('raw_headers', {}).items()  #By taking what I have learned about the '.get()' function, I created this step to get the remainder of our data found within the 'FetchResponse()' we got when we fetched our indexes
                                                                                #Inside of the 'FetchResponse()' are variables, one of these variables being '_response_info=' that is a dictionary, inside of this dictionary is a key called 'raw_headers' whose value
                                                                                    #is the remaining data of our 'FetchResponse()' and all key value pairs of dictionary in 'raw_headers'
                                                                                #By adding '.items()' at the end/next to our '.get()' to open then 'raw_headers' key-value, I am basically telling the interpreter to add all of the key-value-pairs within this dictionary to our response. it turns key value pairs into a list of tuples
                                                                               
# 2. Use it in your list comprehension
clean_print = [
        {
            "id": vid, 
            "values": vdata["values"][:2], #It uses slicing ([:2]) to keep only the first two numbers of the 1536-dimension vector.
            "metadata": vdata.get("metadata", {}), #It copies the existing metadata (like "genre")
            "read_units_for_request": total_read_units, # Attaches the total_read_units we calculated in Step 1 to every item in the new list.
            "response_info": t_res_info
        }
        for vid, vdata in disp["vectors"].items() #provides the ID (e.g., "0", "1") and the Data (id/values/metadata) for each user record.
    ]

print(clean_print)'''


with open("test/test_set_v1_1.csv", "w") as csvfile:
        fieldnames = ["query", "context", "output"]
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()
        for row in test_set:
            writer.writerow(row)
            
'''More examples for my test set.'''

,
{
    "query": "What is a Computer Virus?",
    "expected_context": """Answer the question based on the context below. 

Context:
In this chapter:
(1)  "Access" means to approach, instruct, communicate with, store data in, retrieve or intercept data from, alter data or computer software in, or otherwise make use of any resource of a computer, computer network, computer program, or computer system.
(2)  "Aggregate amount" means the amount of:
(A)  any direct or indirect loss incurred by a victim, including the value of money, property, or service stolen, appropriated, or rendered unrecoverable by the offense; or
(B)  any expenditure required by the victim to:
(i)  determine whether data or a computer, computer network, computer program, or computer system was altered, acquired, appropriated, damaged, deleted, or disrupted by the offense; or
(ii)  attempt to restore, recover, or replace any data altered, acquired, appropriated, damaged, deleted, or disrupted.
(3)  "Communication common carrier" means a person who owns or operates a telephone system in this state that includes equipment or facilities for the conveyance, transmission, or reception of communications and who receives compensation from persons who use that system.
(4)  "Computer" means an electronic, magnetic, optical, electrochemical, or other high-speed data processing device that performs logical, arithmetic, or memory functions by the manipulations of electronic or magnetic impulses and includes all input, output, processing, storage, or communication facilities that are connected or related to the device.
(5)  "Computer network" means the interconnection of two or more computers or computer systems by satellite, microwave, line, or other communication medium with the capability to transmit information among the computers.
(6)  "Computer program" means an ordered set of data representing coded instructions or statements that when executed by a computer cause the computer to process data or perform specific functions.
(7)  "Computer services" means the product of the use of a computer, the information stored in the computer, or the personnel supporting the computer, including computer time, data processing, and storage functions.
(8)  "Computer system" means any combination of a computer or computer network with the documentation, computer software, or physical facilities supporting the computer or computer network.
(9)  "Computer software" means a set of computer programs, procedures, and associated documentation related to the operation of a computer, computer system, or computer network.
(10)  "Computer virus" means an unwanted computer program or other set of instructions inserted into a computer's memory, operating system, or program that is specifically constructed with the ability to replicate itself or to affect the other programs or files in the computer by attaching a copy of the unwanted program or other set of instructions to one or more computer programs or files.
(10-a)  "Critical infrastructure facility" means:
(A)  a chemical manufacturing facility;
(B)  a refinery;
(C)  an electrical power generating facility, substation, switching station, electrical control center, or electrical transmission or distribution facility;
(D)  a water intake structure, water treatment facility, wastewater treatment plant, or pump station;
(E)  a natural gas transmission compressor station;
(F)  a liquid natural gas terminal or storage facility;
(G)  a telecommunications central switching office;
(H)  a port, railroad switching yard, trucking terminal, or other freight transportation facility;
(I)  a gas processing plant, including a plant used in the processing, treatment, or fractionation of natural gas;
(J)  a transmission facility used by a federally licensed radio or television station; or
(K)  a cable television or video service provider headend.
(11)  "Data" means a representation of information, knowledge, facts, concepts, or instructions that is being prepared or has been prepared in a formalized manner and is intended to be stored or processed, is being stored or processed, or has been stored or processed in a computer.  Data may be embodied in any form, including but not limited to computer printouts, magnetic storage media, laser storage media, and punchcards, or may be stored internally in the memory of the computer.
(11-a)  "Decryption," "decrypt," or "decrypted" means the decoding of encrypted communications or information, whether by use of a decryption key, by breaking an encryption formula or algorithm, or by the interference with a person's use of an encryption service in a manner that causes information or communications to be stored or transmitted without encryption.
(12)  "Effective consent" includes consent by a person legally authorized to act for the owner.  Consent is not effective if:
(A)  induced by deception, as defined by Section 31.01, or induced by coercion;
(B)  given by a person the actor knows is not legally authorized to act for the owner;
(C)  given by a person who by reason of youth, mental disease or defect, or intoxication is known by the actor to be unable to make reasonable property dispositions;
(D)  given solely to detect the commission of an offense;  or
(E)  used for a purpose other than that for which the consent was given.
(13)  "Electric utility" has the meaning assigned by Section 31.002, Utilities Code.
(13-a)  "Encrypted private information" means encrypted data, documents, wire or electronic communications, or other information stored on a computer or computer system, whether in the possession of the owner or a provider of an electronic communications service or a remote computing service, and which has not been accessible to the public.
(13-b)  "Encryption," "encrypt," or "encrypted" means the encoding of data, documents, wire or electronic communications, or other information, using mathematical formulas or algorithms in order to preserve the confidentiality, integrity, or authenticity of, and prevent unauthorized access to, such information.
(13-c)  "Encryption service" means a computing service, a computer device, computer software, or technology with encryption capabilities, and includes any subsequent version of or update to an encryption service.
(14)  "Harm" includes partial or total alteration, damage, or erasure of stored data, interruption of computer services, introduction of a computer virus, or any other loss, disadvantage, or injury that might reasonably be suffered as a result of the actor's conduct.
(14-a)  "Identifying information" has the meaning assigned by Section 32.51.
(15)  "Owner" means a person who:
(A)  has title to the property, possession of the property, whether lawful or not, or a greater right to possession of the property than the actor;
(B)  has the right to restrict access to the property;  or
(C)  is the licensee of data or computer software.
(15-a)  "Privileged information" means:
(A)  protected health information, as that term is defined by Section 182.002, Health and Safety Code;
(B)  information that is subject to the attorney-client privilege; or
(C)  information that is subject to accountant-client confidentiality under Section 901.457, Occupations Code, or other law, if the information is on a computer, computer network, or computer system owned by a person possessing a license issued under Subchapter H, Chapter 901, Occupations Code.
(16)  "Property" means:
(A)  tangible or intangible personal property including a computer, computer system, computer network, computer software, or data;  or
(B)  the use of a computer, computer system, computer network, computer software, or data.

Question: What is a Computer Virus?
Answer:""",
    "output": "According to sec. 33.01., 'Definitions', a 'computer virus' means an unwanted computer program or other set of instructions inserted into a computer's memory, operating system, or program that is specifically constructed with the ability to replicate itself or to affect the other programs or files in the computer by attaching a copy of the unwanted program or other set of instructions to one or more computer programs or files."
},
{
    "query": "Say an ethical hacker is given permission to access a company’s most vulnerable data via hacking. He does hack the system, gives the vulnerabilities to the company, but what the company doesn’t know is that he secretly stole their most vulnerable data. Later on he sells it, the company loses money, and so the company sues him for violating terms of contract. What could happen if they sue him?",
    "expected_context": """Answer the question based on the context below. 

Context:

Question: Say an ethical hacker is given permission to access a company’s most vulnerable data via hacking. He does hack the system, gives the vulnerabilities to the company, but what the company doesn’t know is that he secretly stole their most vulnerable data. Later on he sells it, the company loses money, and so the company sues him for violating terms of contract. What could happen if they sue him?
Answer:""",
    "output": "According to, ‘sec.33.02. BREACH OF SECURITY’, of the Texas Penal code the ethical hacker may face charges depending on how much damage they have caused; ranging from a Class C misdemeanor to a felony of the first degree. There will be no defense to the ethical hacker."
},
{
    "query": "",
    "expected_context": """Answer the question based on the context below. 

Context:

Question: 
Answer:""",
    "output": ""
},