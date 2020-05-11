"""extras.py
This module contains helper functions for index.py
project: CORD-19 COSI134A FINAL PROJECT
date: May 2020
authors: Samantha Richards, Molly Moran, Emily Fountain
"""
import functools, time, os, re, csv, jsonlines, json, pickle
from collections import defaultdict
from collections import Counter
import networkx as nx
import pandas as pd

def timer(func):
    """ Creates a wrapper around functions so that, when 'timer' is called on them,
    a report of the elapsed time is printed after the function executes."""
    @functools.wraps(func)
    def wrapper_timer(*args, **kwargs):
        start_t = time.perf_counter()
        f_value = func(*args, **kwargs)
        elapsed_t = time.perf_counter() - start_t
        mins = elapsed_t // 60
        print(f'{func.__name__} elapsed time: {mins} minutes, {elapsed_t - mins * 60:0.2f} seconds')
        return f_value

    return wrapper_timer
"""
Creates a dict mapping sha's to entities and other metadata for all sources.
Since we index by sha's, and not all our data sources are based on sha's, we need
to manually cross reference all our data.
"""
@timer
def all_ner_metadata_cross_reference(metadata_csv, ner_json, out):
    # open json, get ents for each paper by doc_ids
    ner_data = {}
    with jsonlines.open(ner_json) as reader:
        for obj in reader:
            doc_id = obj['doc_id']
            doc_sents = obj['sents']
            doc_ents = defaultdict(list)
            for sent in doc_sents:
                ent_list = sent['entities']
                for ent in ent_list:
                    doc_ents[ent['type']].append(ent['text'])
            ner_data[doc_id] = doc_ents

    # open csv file containing the article ids (sha)
    # the index of each line in the csv files corresponds to the doc_ids in the ner_json file
    article_data = {}
    with open(metadata_csv, 'r') as csvf:
        reader = csv.reader(csvf)
        next(reader)
        for i, line in enumerate(reader):
            sha = line[0]
            source = line[1]
            doi = line[3]
            publish_time = line[8]
            journal = line[10]
            has_full_text = line[13]
            if sha:
                article_data[sha] = {"entities": ner_data[i]}
                article_data[sha]['source'] = source
                article_data[sha]['doi'] = doi
                article_data[sha]['publish_time'] = publish_time
                article_data[sha]['journal'] = journal
                article_data[sha]['has_full_text'] = has_full_text

    with open(out, 'w') as f:
        json.dump(article_data, f)

    return article_data

def extract_year(publish_time):
    m = re.match(r"[12][0-9][0-9][0-9]", publish_time)
    if m:
        yr = m.group(0)
    else:
        return 0
    return yr

def untokenize(ent_list):
    if len(ent_list) > 0:
        ents = " ".join([re.sub(r"\s", "_", ent) for ent in ent_list])
        return ents
    else:
        return ""


@timer
def load_dataset_to_dict(module_dir, data_dir):
    """
    Get dataset in dict form and pickle.
    """
    articles = {}
    for dirname, subdirs, files in os.walk(data_dir):
        for file in files:
            if file != '.DS_Store':
                with open(os.path.join(dirname, file), 'r') as f:
                    if file.endswith('.json'):
                        text_data = json.load(f)
                        articles[text_data['paper_id']] = text_data

    with open(os.path.join(module_dir, 'articles.p'), 'wb') as f:
        pickle.dump(articles, f)


def filter_entities(entlist):
    filtered_ents = []
    for ent in entlist:
        ent = ent.lower()
        ent = re.sub(r"[^A-Za-z0-9\-]", " ", ent)   # remove non-alphanumeric characters, except hyphens
        ent = re.sub(r"\s{2,}", " ", ent)           # remove duplicate spaces
        if len(ent) > 2:                            # remove any entities shorter than 3 characters
            if not re.match(r"fig", ent):           # remove ent that is 'fig' or 'figure'
                filtered_ents.append(ent)
    return filtered_ents

@timer
def get_anchor_text(articles, titles_to_ids):
    anchor_text_dict = defaultdict(list)
    for i, article in enumerate(articles.values()):
        # articles cited by this article
        cit_nums = {refname: article['bib_entries'][refname]['title'] for refname in article['bib_entries'].keys()}
        texts = [(sect['text'], sect['cite_spans']) for sect in article['body_text'] if sect['cite_spans'] != []]
        for text, cite_spans in texts:
            for span in cite_spans:
                ref = span['ref_id']
                start = span['start']
                end = span['end']
                if ref is not None:
                    name = cit_nums[ref].lower()
                    if name in titles_to_ids and not name.isspace() and name is not '':
                        while start > 0 and text[start] != '.':
                            start -= 1
                        while end < len(text) and text[end] != '.':
                            end += 1
                        surrounding_text = text[start:end]
                        if surrounding_text !='':
                            anchor_text_dict[name].append({"id": i, "text": surrounding_text})
    return anchor_text_dict


@timer
def get_entity_counts(meta_ner_all):
    """
    This function takes in the metadata collection and returns a dictionary of counts
    of those entities in the database.
    """
    ent_freqs = defaultdict(int)
    for sha, info in meta_ner_all.items():
        ent_types = info['entities']  # {GENE: [ent1, ent2], GPE: [ent1, ent2], ...}
        for type, entlist in ent_types.items():
            entlist = filter_entities(entlist)  # clean up entities before hashing to freq dict
            meta_ner_all[sha]['entities'][type] = entlist  # also update original dict with cleaned entities
            for ent, count in Counter(entlist).items():
                ent_freqs[ent] += count
    return ent_freqs


def generate_citation_graph(data_path, es_module_dir):
    """
    Generates a networkx graph of citations in the COVID-19 corpus, based
    on citation titles.

    :param data_path: path to a folder of .json files in the non-comm-use Kaggle dataset.
    :return: networkx DiGraph object representing citation relationships in the dataset.
    """
    # Keep track of titles corresponding to articles in the corpus, and their corresponding paper IDs
    titles_to_ids = defaultdict(int)

    refdict = defaultdict(list)
    i = 0
    for dir, subdir, files in os.walk(data_path):
        for file in files:
            try:
                with open(os.path.join(dir, file), 'r') as f:
                    data = json.load(f)
                    reftitle = data['metadata']['title'].lower()
                    titles_to_ids[reftitle] = i
                    # Each entry in "bib_entries" for a given article is named "BIB01", "BIB02", etc... and is the key
                    # to a dictionary of values corresponding to identifying data for the particular citation.
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

    with open(os.path.join(es_module_dir, 'graph.p'), 'wb') as f:
        pickle.dump(graph, f)

    return graph
