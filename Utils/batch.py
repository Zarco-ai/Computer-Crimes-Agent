import itertools

# BATCHING FUNCTION
def chunks(iterable, batch_size=100):
    it = iter(iterable) #This turns our iterable (data types like: strings, list, dictionaries...), and stores it within this function for function's purpose.
    chunk = tuple(itertools.islice(it, batch_size)) #'islice' is the "iterator version" of a slice. It tells the iterator it: "Give me the next batch_size items, one by one, and then stop."
                                                    #'tuple()' takes the batch of 100 data points within our data and stores it in a tuple/container that looks like; (data1, data2, data3...)
                                                    #tuples are immutable(cannot be changed once created), and are slightly more memory efficient!
    while chunk: #This loop runs until there are no chuncks left
        yield chunk #Right here the function will pause, 'yield', take that chunk and give it to whatever code is calling this chunk (likely a for-loop),
        chunk = tuple(itertools.islice(it, batch_size))
        