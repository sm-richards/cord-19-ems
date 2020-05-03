""" Building a traversable directed graph of citations in the Non-Commercial Subset.

See https://networkx.github.io/documentation/networkx-2.0/index.html for documentation on
how to use DiGraph objects in networkx. """

import json
import os
from collections import defaultdict

import networkx as nx
import pandas as pd

import pickle

def generate_citation_graph(data_path):
    """
    Generates a networkx graph of citations in the COVID-19 corpus, based
    on citation titles.

    :param data_path: path to a folder of .json files in the non-comm-use Kaggle dataset.
    :return: networkx DiGraph object representing citation relationships in the dataset.
    """
    # Keep track of titles corresponding to articles in the corpus, and their corresponding paper IDs
    titles_to_shas = defaultdict(str)

    refdict = defaultdict(list)
    for dir, subdir, files in os.walk(data_path):
        for file in files:
            try:
                with open(os.path.join(dir, file), 'r') as f:
                    data = json.load(f)
                    reftitle = data['metadata']['title'].lower()
                    titles_to_shas[reftitle] = data['paper_id']

                    # Each entry in "bib_entries" for a given article is named "BIB01", "BIB02", etc... and is the key to a dictionary
                    # of values corresponding to identifying data for the particular citation.

                    for bib in data['bib_entries'].values():
                        title = bib['title'].lower()
                        if title != '':
                            refdict[reftitle].append(title)
            except UnicodeDecodeError:
                continue

    # Code adapted from https://www.kaggle.com/baptistemetge/simple-citation-network-and-pagerank-score
    # Create a Pandas dataframe from the citation data, and a networkx graph from the dataframe

    citations = [{"title": ref, "citation": citation} for ref in refdict for citation in refdict[ref]]
    citations = pd.DataFrame(citations)
    graph = nx.from_pandas_edgelist(citations, source='title', target='citation', create_using=nx.DiGraph)
    return graph, titles_to_shas

if __name__=='__main__':
    graph, titles_to_shas = generate_citation_graph('../data')
    with open('graph.p', 'wb') as f:
        pickle.dump(graph, f)
    with open('dict.p', 'wb') as g:
        pickle.dump(titles_to_shas, g)



