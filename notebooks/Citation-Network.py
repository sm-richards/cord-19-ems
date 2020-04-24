""" Building a traversable directed graph of citations in the Non-Commercial Subset.

See https://networkx.github.io/documentation/networkx-2.0/index.html for documentation on
how to use DiGraph objects in networkx. """

import pandas as pd
import json
from collections import defaultdict
import os
import networkx as nx
from networkx import DiGraph
import matplotlib.pyplot as plt

# Keep track of titles corresponding to articles in the corpus
in_corpus_titles = set()

def generate_citation_graph(data_path):
    """
    Generates a networkx graph of citations in the COVID-19 corpus, based
    on citation titles.

    :param data_path: path to a folder of .json files in the non-comm-use Kaggle dataset.
    :return: networkx DiGraph object representing citation relationships in the dataset.
    """
    refdict = defaultdict(list)
    for dirname, _, filenames in os.walk(data_path):
        for file in filenames:
            with open(os.path.join(dirname, file), 'r') as f:
                data = json.load(f)
                reftitle = data['metadata']['title'].lower()
                in_corpus_titles.add(reftitle)

                # Each entry in "bib_entries" for a given article is named "BIB01", "BIB02", etc... and is the key to a dictionary
                # of values corresponding to identifying data for the particular citation.

                for bib in data['bib_entries'].values():
                    title = bib['title'].lower()
                    if title != '':
                        refdict[reftitle].append(title)

    # Code adapted from https://www.kaggle.com/baptistemetge/simple-citation-network-and-pagerank-score
    # Create a Pandas dataframe from the citation data, and a networkx graph from the dataframe

    citations = [{"title": ref, "citation": citation} for ref in refdict for citation in refdict[ref]]
    citations = pd.DataFrame(citations)
    graph = nx.from_pandas_edgelist(citations, source='title', target='citation', create_using=nx.DiGraph)
    return graph

# # Helper functions demonstrating some uses of the graph

def pagerank(g):
    """
    Generate a dataframe of pagerank scores for documents.
    Code adapted from https://www.kaggle.com/baptistemetge/simple-citation-network-and-pagerank-score

    :param g: a networkx graph
    :return: a pandas dataframe of article titles mapped to pagerank scores.

    """
    pr = nx.pagerank(g)
    pagerank = pd.DataFrame(pr.items(), columns=["title", "pagerank"]).sort_values(by="pagerank", ascending=True)
    return pagerank

def get_citation_overlap(g, title1, title2):
    """
    Returns the overlap between the citations of two titles.

    :param g: a networkx graph
    :param title1: article title, a string
    :param title2: article title, a string
    :return: overlap of citaitons between title1 and title2: a set
    """
    title1_refs = g.successors(title1)
    title2_refs = g.successors(title2)
    if title1 not in in_corpus_titles or title1_refs==[]:
        print(f"No citation data for {title1}.")
    elif title2 not in in_corpus_titles or title2_refs==[]:
        print(f"No citation data for {title2}.")
    else:
        return title1_refs.union(title2_refs)


