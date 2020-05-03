from __future__ import absolute_import
import json
import time
import os
import pickle
from elasticsearch import Elasticsearch
from elasticsearch import helpers
from elasticsearch_dsl import Index, Document, Text, Integer, Long, Nested, InnerDoc
from elasticsearch_dsl.connections import connections
from elasticsearch_dsl.analysis import analyzer, token_filter
import networkx as nx
from cord_19_ems.notebooks.Citation_Network import generate_citation_graph
from collections import defaultdict
import cord_19_ems.es_module.extras as utils

# connect to local host server
connections.create_connection(hosts=['127.0.0.1'])

# create elasticsearch object
es = Elasticsearch(timeout=30, max_retries=10, retry_on_timeout=True)

# data paths
data_dir = '../data'
metadata_path = '../data_extras/all_sources_metadata_2020-03-13.csv'
ner_path = '../data_extras/CORD-NER-ner.json'
meta_ner_path = '../data_extras/cross_ref_data_all_sources.json'

# name of index
index_name = 'another_covid_index'


# "text_analyzer" tokenizer splits at word boundaries, preserving internal hyphens.
# the additional custom filter breaks down hyphenated compound words into their subwords,
# but also preserves the original hyphenated form.
# the "flatten_graph" filter is necessary because the word delimiter graph filter can mess with
# indexing by creating multi-position tokens. this can cause trouble for exact phrase matching.
de_hyphenator = token_filter('de_hyphenator', type='word_delimiter_graph', preserve_original=True)
text_analyzer = analyzer('custom', tokenizer='pattern', pattern=r"\b[\w-]+\b",
                         filter=['lowercase', 'porter_stem', de_hyphenator, 'flatten_graph'])
entity_analyzer = analyzer('custom', tokenizer='whitespace', filter=['lowercase'])


# special datatype for author names. They contain a "first_name" and "last_name" field.
class Name(InnerDoc):
    first = Text(analyzer='standard')
    last = Text()


# special datatype for Citations They contain a "title" and "year" field.
class Citation(InnerDoc):
    title = Text()
    year = Integer()
    in_corpus = Integer()
    authors = Nested(Name)


class Article(Document):
    id_num = Text(analyzer='standard')
    authors = Nested(Name)                  # authors field is a Nested list of Name objects
    title = Text(analyzer=text_analyzer, boost=3)
    abstract = Text(analyzer=text_analyzer)
    body = Text(analyzer=text_analyzer)
    citations = Nested(Citation)            # citations field is a Nested list of Citation objects
    pr = Long()
    gene_or_genome = Text(analyzer=entity_analyzer)
    publish_time = Integer()

    # override the Document save method to include subclass field definitions
    def save(self, *args, **kwargs):
        return super(Article, self).save(*args, **kwargs)


# populate the index
def buildIndex():
    """
    buildIndex creates a new film index, deleting any existing index of
    the same name.
    It loads a json file containing the movie corpus and does bulk loading
    using a generator function.
    """

    citation_graph = pickle.load(open('../notebooks/graph.p','rb'))
    pagerank_scores = nx.pagerank(citation_graph)
    ddict = defaultdict(float, pagerank_scores)

    article_index = Index(index_name)
    if article_index.exists():
        article_index.delete()  # overwrite any previous version
    article_index.document(Article)  # register the document mapping
    article_index.create()

    # load articles
    articles = utils.load_dataset_to_dict(data_dir)
    titles_to_ids = {v['metadata']['title'].lower():k for k,v in enumerate(articles.values())}
    # builds a default dictionary mapping article titles to index IDs, with
    # -1 as the default value for a key error.
    titles_to_ids = defaultdict(lambda: -1, titles_to_ids)

    print("SIZE OF ARTICLES: ", len(articles.keys()))

    # open ner and metadata dict
    with open(meta_ner_path, 'r') as f:
        meta_ner_all = json.load(f)
    print("SIZE OF META DATA: ", len(meta_ner_all.keys()))

    def actions():
        for i, article in enumerate(articles.values()):
            sha = article['paper_id']

            # extract contents of entity and metadata dict
            if sha in meta_ner_all.keys():  # entities, source, doi, publish_time, has_full_text, journal
                ent_types = meta_ner_all[sha]['entities']
                publish_time = utils.extract_year(meta_ner_all[sha]["publish_time"])
                gene_or_genome = utils.untokenize(ent_types['GENE_OR_GENOME']) \
                    if 'GENE_OR_GENOME' in ent_types.keys() else ''
            else:
                publish_time = 0
                gene_or_genome = ''

            # extract contents of article dict
            title = article['metadata']['title'] if 'title' in article['metadata'].keys() else ''
            cits = article['bib_entries'] if 'bib_entries' in article.keys() else [{}]
            cits = [{"title": cit['title'], "year": cit['year'], "in_corpus": titles_to_ids[cit['title'].lower()],
                     "authors": [{"first": auth['first'], "last": auth["last"]} for auth in cit['authors']]} for cit in cits.values() if cit['title'] != '']
            authors = [{"first": auth['first'], "last": auth["last"]} for auth in article['metadata']['authors']]
            pr = ddict[article['metadata']['title']]
            abstract = ' '.join([abs['text'] if 'text' in abs.keys() else '' for abs in article['abstract']]) if 'abstract' in article.keys() else ''
            body = '\n'.join([sect['text'] for sect in article['body_text']])

            yield {
                "_index": index_name,
                "_type": '_doc',
                "_id": i,
                "title": title,
                "id_num": sha,
                "abstract": abstract,
                "body": body,
                "authors": authors,
                "publish_time": publish_time,
                "citations": cits,
                "pr": pr,
                "gene_or_genome": gene_or_genome
            }

    helpers.bulk(es, actions(), raise_on_error=True)  # one doc in corpus contains a NAN value and it has to be ignored.


# command line invocation builds index and prints the running time.
def main():
    start_time = time.time()
    # if extra datafiles have not been cross-referenced, do this
    if not os.path.isfile(meta_ner_path):
        utils.all_ner_metadata_cross_reference(metadata_path, ner_path, meta_ner_path)
    buildIndex()
    print(f"=== Built {index_name} in %s seconds ===" % (time.time() - start_time))


if __name__ == '__main__':
    main()
