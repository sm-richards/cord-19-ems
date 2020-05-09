from __future__ import absolute_import
import json
import time
import os
import pickle
from elasticsearch import Elasticsearch
from elasticsearch import helpers
from elasticsearch_dsl import Index, Document, Text, Integer, Float, Nested, InnerDoc, Boolean
from elasticsearch_dsl.connections import connections
from elasticsearch_dsl.analysis import analyzer, token_filter
import networkx as nx
from cord_19_ems.notebooks.Citation_Network import generate_citation_graph
from collections import defaultdict
import cord_19_ems.es_module.extras as utils
from cord_19_ems.es_module.extras import timer
import langid
from collections import Counter

# connect to local host server
connections.create_connection(hosts=['127.0.0.1'])

# create elasticsearch object
es = Elasticsearch(timeout=100, max_retries=100, retry_on_timeout=True, mapping_nested_objects_limit=15000)


# data paths
data_dir = '../data'
metadata_path = '../data_extras/all_sources_metadata_2020-03-13.csv'
ner_path = '../data_extras/CORD-NER-ner.json'
meta_ner_path = '../data_extras/cross_ref_data_all_sources.json'

# name of index
index_name = 'another_covid_index'

entity_types = {'GPE', 'BACTERIUM', 'LOC', 'TISSUE', 'GENE_OR_GENOME', 'IMMUNE_RESPONSE', 'VIRAL_PROTEIN', 'CELL_OR_MOLECULAR_DYSFUNCTION', 'ORGANISM', 'CELL_FUNCTION','DISEASE_OR_SYNDROME', 'MOLECULAR_FUNCTION', 'CELL_COMPONENT', 'WILDLIFE', 'VIRUS','SIGN_OR_SYMPTOM', 'LIVESTOCK'}



# "text_analyzer" tokenizer splits at word boundaries, preserving internal hyphens.
# the additional custom filter breaks down hyphenated compound words into their subwords,
# but also preserves the original hyphenated form.
# the "flatten_graph" filter is necessary because the word delimiter graph filter can mess with
# indexing by creating multi-position tokens. this can cause trouble for exact phrase matching.
de_hyphenator = token_filter('de_hyphenator', type='word_delimiter_graph', preserve_original=True)
text_analyzer = analyzer('custom', tokenizer='pattern', pattern=r"\b[\w-]+\b",
                         filter=['lowercase', 'porter_stem', de_hyphenator, 'flatten_graph'])
entity_analyzer = analyzer('custom', tokenizer='whitespace', filter=['lowercase'])


class AnchorText(InnerDoc):
    text = Text(analyzer='standard')
    id = Integer()

# special datatype for author names. They contain a "first_name" and "last_name" field.
class Name(InnerDoc):
    first = Text()
    last = Text()


# special datatype for Citations They contain a "title" and "year" field.
class Citation(InnerDoc):
    title = Text()
    year = Integer()
    in_corpus = Integer()
    authors = Nested(Name)

class Section(InnerDoc):
    text = Text(analyzer=text_analyzer)
    name = Text(analyzer='keyword')

class Article(Document):
    id_num = Text(analyzer='standard')
    authors = Nested(Name)                  # authors field is a Nested list of Name objects
    title = Text(analyzer=text_analyzer, boost=3)
    abstract = Text(analyzer=text_analyzer)
    body = Nested(Section)
    citations = Nested(Citation)            # citations field is a Nested list of Citation objects
    pr = Float(doc_values=True)
    cited_by = Nested(AnchorText)
    anchor_text = Text(analyzer='standard')
    ents = Text(analyzer=entity_analyzer)
    publish_time = Integer()
    in_english = Boolean()

    # override the Document save method to include subclass field definitions
    def save(self, *args, **kwargs):
        return super(Article, self).save(*args, **kwargs)


# populate the index
@timer
def build_index():
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

    # load articles from data source
    if not os.path.exists('articles.p'):
        utils.load_dataset_to_dict(data_dir)
    f = open('articles.p', 'rb')
    articles = pickle.load(f)
    f.close()

    # build a default dictionary to map titles do ids (for eventual use in citations 'more like this')
    titles_to_ids = {v['metadata']['title'].lower(): k for k, v in enumerate(articles.values())}
    titles_to_ids = defaultdict(lambda: -1, titles_to_ids)  # -1 is default value for a key error

    #get anchor text:
    anchor_text_dict = utils.get_anchor_text(articles, titles_to_ids)

        # open ner and metadata dict
    with open(meta_ner_path, 'r') as f:
        meta_ner_all = json.load(f)

    # get entity frequencies (to filter out unique entities)
    ent_freqs = defaultdict(int)
    get_entity_counts(ent_freqs, meta_ner_all)

    def actions():
        for i, article in enumerate(articles.values()):
            sha = article['paper_id']

            # extract contents of entity and metadata dict
            if sha in set(meta_ner_all.keys()):  # entities, source, doi, publish_time, has_full_text, journal
                ents = []
                for type, entlist in meta_ner_all[sha]['entities'].items():
                    if type in entity_types:
                        ents.extend(entlist)
                ents = [ent for ent in ents if ent_freqs[ent] > 1]  # get only ents that occur > 1 in corpus
                ents_str = utils.untokenize(ents)  # transform to string type for indexing

                publish_time = utils.extract_year(meta_ner_all[sha]["publish_time"])
                journal = meta_ner_all[sha]['journal']
            else:
                publish_time = 0
                ents_str = ''
                journal = ''

            # extract contents of article dict
            title = article['metadata']['title'] if 'title' in article['metadata'].keys() else '(Untitled)'
            cits = article['bib_entries'] if 'bib_entries' in article.keys() else [{}]
            cits = [{"title": cit['title'], "year": cit['year'], "in_corpus": titles_to_ids[cit['title'].lower()],
                     "authors": [{"first": auth['first'], "last": auth["last"]} for auth in cit['authors']]} for cit in cits.values() if cit['title'] != '']
            authors = [{"first": auth['first'], "last": auth["last"]} for auth in article['metadata']['authors']]
            pr = ddict[article['metadata']['title'].lower()]
            abstract = ' '.join([abs['text'] if 'text' in abs.keys() else '' for abs in article['abstract']]) if 'abstract' in article.keys() else ''
            anchor_text = ' '.join([cit['text'] for cit in anchor_text_dict[title.lower()]])
            section_dict = defaultdict(list)
            for txt in article['body_text']:
                section = txt['section']
                section_dict[section].append(txt['text'])
            body = [{"name": k, "text": v} for k,v in section_dict.items()]
            cited_by = anchor_text_dict[title.lower()]

            body_text = ' '.join([sect['text'] for sect in article['body_text']])

            # check that article is in English
            in_english = (langid.classify(body_text)[0] == 'en')

            yield {
                "_index": index_name,
                "_type": '_doc',
                "_id": i,
                "title": title,
                "id_num": sha,
                "abstract": abstract,
                "body": body,
                "body_text": body_text,
                "authors": authors,
                "publish_time": publish_time,
                "journal": journal,
                "citations": cits,
                "in_english": in_english,
                "pr": pr,
                "anchor_text": anchor_text,
                "cited_by": cited_by,
                "ents": ents_str,
            }

    helpers.bulk(es, actions(), raise_on_error=True)  # one doc in corpus contains a NAN value and it has to be ignored.

@timer
def get_entity_counts(ent_freqs, meta_ner_all):
    for sha, info in meta_ner_all.items():
        ent_types = info['entities']  # {GENE: [ent1, ent2], GPE: [ent1, ent2], ...}
        for type, entlist in ent_types.items():
            entlist = utils.filter_entities(entlist)  # clean up entities before hashing to freq dict
            meta_ner_all[sha]['entities'][type] = entlist  # also update original dict with cleaned entities
            for ent, count in Counter(entlist).items():
                ent_freqs[ent] += count


# command line invocation builds index and prints the running time.
def main():
    # if extra datafiles have not been cross-referenced, do this
    if not os.path.isfile(meta_ner_path):
        utils.all_ner_metadata_cross_reference(metadata_path, ner_path, meta_ner_path)
    build_index()

if __name__ == '__main__':
    main()
