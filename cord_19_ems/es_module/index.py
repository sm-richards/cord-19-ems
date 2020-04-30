import json
import time
import glob

from elasticsearch import Elasticsearch
from elasticsearch import helpers
from elasticsearch_dsl import Index, Document, Text, Integer, Long, Nested, InnerDoc
from elasticsearch_dsl.connections import connections
from elasticsearch_dsl.analysis import analyzer, token_filter
import networkx as nx
from cord_19_ems.notebooks.Citation_Network import generate_citation_graph
from collections import defaultdict

# Connect to local host server
connections.create_connection(hosts=['127.0.0.1'])

# Create elasticsearch object
es = Elasticsearch(timeout=30, max_retries=10, retry_on_timeout=True)

# "text_analyzer" tokenizer splits at word boundaries, preserving internal hyphens.

# the additional custom filter breaks down hyphenated compound words into their subwords,
# but also preserves the original hyphenated form.

# the "flatten_graph" filter is necessary because the word delimiter graph filter can mess with
# indexing by creating multi-position tokens. this can cause trouble for exact phrase matching.
de_hyphenator = token_filter('de_hyphenator',type='word_delimiter_graph', preserve_original=True)
text_analyzer = analyzer('custom',
                       tokenizer='pattern', pattern=r'\b[\w-]+\b',
                       filter=['lowercase','porter_stem', de_hyphenator, 'flatten_graph'])


# Special datatype for author names. They contain a "first_name" and "last_name" field.
class Name(InnerDoc):
    first = Text()
    last = Text()

# Special datatype for Citations They contain a "title" and "year" field.
class Citation(InnerDoc):
    title = Text()
    year = Integer()

class Article(Document):
    id_num = Text(analyzer='standard')
    # authors field is a Nested list of Name objects
    authors = Nested(Name)
    title = Text(analyzer=text_analyzer, boost=3)
    abstract = Text(analyzer=text_analyzer)
    body = Text(analyzer=text_analyzer)
    # citations field is a Nested list of Citation objects
    citations = Nested(Citation)
    pr = Long()

    # override the Document save method to include subclass field definitions
    def save(self, *args, **kwargs):
        return super(Article, self).save(*args, **kwargs)

# Populate the index
def buildIndex():
    """
    buildIndex creates a new film index, deleting any existing index of
    the same name.
    It loads a json file containing the movie corpus and does bulk loading
    using a generator function.
    """

    citation_graph = generate_citation_graph('../data')
    pagerank_scores = nx.pagerank(citation_graph)
    ddict = defaultdict(float, pagerank_scores)

    article_index = Index('covid_index')
    if article_index.exists():
        article_index.delete()  # Overwrite any previous version
    article_index.document(Article)  # register the document mapping
    article_index.create()

    # Open the json film corpus
    articles = dict()
    i = 0
    for file in glob.iglob('../data/comm_use_subset/pdf_json' + "/*.json"):
        with open(file, 'r', encoding='utf-8') as f:
            # a single article document
            doc = json.loads(f.read())
            articles[str(i)] = doc
        i += 1
    for file in glob.iglob('../data/comm_use_subset/pmc_json' + "/*.json"):
        with open(file, 'r', encoding='utf-8') as f:
            # a single article document
            doc = json.loads(f.read())
            articles[str(i)] = doc
        i += 1
    for file in glob.iglob("../data/noncomm_use_subset" + "/*.json"):
        with open(file, 'r', encoding='utf-8') as f:
            # a single article document
            doc = json.loads(f.read())
            articles[str(i)] = doc
        i += 1

    for file in glob.iglob("../data/biorxiv_medrxiv/pdf_json" + "/*.json"):
        with open(file, 'r', encoding='utf-8') as f:
            # a single article document
            doc = json.loads(f.read())
            articles[str(i)] = doc
        i += 1

    size = len(articles)

    def actions():
        for mid in range(1, size):
            article = articles[str(mid)]
            try:
                citations = article['bib_entries']
            except KeyError:
                citations= [{}]
            try:
                title = article['metadata']['title']
            except KeyError:
                title = ''
            try:
                abstract = ' '.join([abs['text'] for abs in article['abstract']])
            except KeyError:
                abstract = ''
            yield {
                "_index": "covid_index",
                "_type": '_doc',
                "_id": mid,
                "title": title,
                "id_num": article['paper_id'],
                "abstract": abstract,
                "authors": [{"first": author['first'], "last": author["last"]}
                            for author in article['metadata']['authors']],
                "body": ' '.join([sec['text'] for sec in article['body_text']]),
                "citations": [{"title": citations[bib]['title'], "year": citations[bib]['year']} for bib in citations.keys()],
                "pr": ddict[article['metadata']['title']],
            }
    helpers.bulk(es, actions(), raise_on_error=True) # one doc in corpus contains a NAN value and it has to be ignored.


# command line invocation builds index and prints the running time.
def main():
    start_time = time.time()
    buildIndex()
    print("=== Built index in %s seconds ===" % (time.time() - start_time))


if __name__ == '__main__':
    main()