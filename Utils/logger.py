import logging

def get_embed_logger(name, log_file):
    # Activate Custom Logger
    logger = logging.getLogger(name)
    # Connect to file you are logging to
    handler =  logging.FileHandler(log_file) 
    # Format Logger
    formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    # Set the level of which I want written to the log
    logger.setLevel(logging.INFO) # Remember to add this otherwise my INFO message will not show in the console
    # First format handler
    handler.setFormatter(formatter) 
    # Second add hammer to the logger
    logger.addHandler(handler)
    return logger

def get_index_costs_logger(name, log_file):
    # Activate Custom Logger
    logger = logging.getLogger(name)
    # Connect to file you are logging to
    handler =  logging.FileHandler(log_file) 
    # Format Logger
    formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    # Set the level of which I want written to the log
    logger.setLevel(logging.INFO) # Remember to add this otherwise my INFO message will not show in the console
    # First format handler
    handler.setFormatter(formatter) 
    # Second add hammer to the logger
    logger.addHandler(handler)
    return logger